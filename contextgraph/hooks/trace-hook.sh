#!/usr/bin/env bash
# trace-hook.sh — Claude Code hook for agentic execution lineage
#
# Handles: SessionStart, UserPromptSubmit, PostToolUse, Stop
# Writes structured Trace nodes to Neo4j + episodes to Graphiti (both background, fire-and-forget)
# Always returns {"continue": true} immediately — never blocks Claude Code.

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────
NEO4J_URL="${TRACE_NEO4J_URL:-http://localhost:7475}"
NEO4J_AUTH="${TRACE_NEO4J_AUTH:-neo4j:tracegraph2026}"
GRAPHITI_URL="${TRACE_GRAPHITI_URL:-http://localhost:8100}"
GROUP_ID="${TRACE_GROUP_ID:-claude-traces}"
STATE_BASE="/tmp/claude-traces"

# ── Read stdin ──────────────────────────────────────────────────
INPUT=$(cat)

# ── Extract session_id and bump sequence (fast, no python) ──────
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id','unknown'))" 2>/dev/null) || SESSION_ID="unknown"
[ "$SESSION_ID" = "unknown" ] && { echo '{"continue": true}'; exit 0; }

STATE_DIR="${STATE_BASE}/${SESSION_ID}"
mkdir -p "$STATE_DIR"
SEQ_FILE="${STATE_DIR}/seq"

if [ -f "$SEQ_FILE" ]; then
    SEQ=$(cat "$SEQ_FILE")
    SEQ=$((SEQ + 1))
else
    SEQ=0
fi
echo "$SEQ" > "$SEQ_FILE"

TRACE_ID="${SESSION_ID}:${SEQ}"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# ── Background: Python does ALL the heavy lifting ───────────────
# One python3 process generates both the Neo4j Cypher payload and Graphiti payload,
# then executes both curls. This avoids all bash string escaping issues.
(
echo "$INPUT" | python3 -c "
import sys, json, subprocess, os

d = json.load(sys.stdin)

# Config from environment
neo4j_url = '${NEO4J_URL}'
neo4j_auth = '${NEO4J_AUTH}'
graphiti_url = '${GRAPHITI_URL}'
group_id = '${GROUP_ID}'
state_dir = '${STATE_DIR}'
seq = ${SEQ}
trace_id = '${TRACE_ID}'
timestamp = '${TIMESTAMP}'
prev_trace_id = '${SESSION_ID}:' + str(seq - 1)

def trunc(s, n=500):
    s = str(s) if s else ''
    return s[:n]

event = d.get('hook_event_name', '')
session_id = d.get('session_id', 'unknown')
cwd = trunc(d.get('cwd', ''), 200)
project = os.path.basename(cwd) if cwd else 'unknown'

tool_name = ''
input_summary = ''
output_summary = ''
status = 'ok'
error_signal = ''

if event == 'PostToolUse':
    tool_name = d.get('tool_name', '')
    inp = d.get('tool_input', {})
    if isinstance(inp, dict):
        input_summary = trunc(
            inp.get('command',
            inp.get('file_path',
            inp.get('pattern',
            inp.get('query',
            inp.get('prompt',
            json.dumps(inp, default=str))))))
        )
    else:
        input_summary = trunc(inp)
    output_summary = trunc(d.get('tool_result', ''))

    # Error detection
    result_str = str(d.get('tool_result', ''))
    for sig in ['Error:', 'error:', 'FAILED', 'fatal:', 'command not found',
                'No such file', 'Permission denied', 'non-zero exit',
                'ModuleNotFoundError', 'SyntaxError', 'TypeError',
                'FileNotFoundError', 'ConnectionRefused', 'Traceback']:
        if sig in result_str:
            status = 'failed'
            idx = result_str.index(sig)
            error_signal = trunc(result_str[idx:idx+200], 200)
            break

elif event == 'UserPromptSubmit':
    input_summary = trunc(d.get('user_prompt', ''))

elif event == 'Stop':
    input_summary = trunc(d.get('reason', ''))

elif event == 'SessionStart':
    input_summary = trunc(f'session started in {d.get(\"cwd\", \"\")}')

# Map event type
event_type_map = {
    'SessionStart': 'session_start',
    'UserPromptSubmit': 'user_prompt',
    'PostToolUse': 'tool_call',
    'Stop': 'stop',
}
event_type = event_type_map.get(event, 'unknown')

# ── Build Neo4j Cypher using parameterized query ──
# Use Cypher parameters to avoid ALL escaping issues
cypher = '''
MERGE (s:Session {session_id: \$sid})
ON CREATE SET s.started_at = datetime(\$ts), s.cwd = \$cwd, s.project = \$project
CREATE (t:Trace {
  trace_id: \$trace_id,
  session_id: \$sid,
  seq: \$seq,
  event_type: \$event_type,
  tool_name: \$tool_name,
  input_summary: \$input_summary,
  output_summary: \$output_summary,
  status: \$status,
  error_signal: \$error_signal,
  cwd: \$cwd,
  timestamp: datetime(\$ts)
})
CREATE (t)-[:BELONGS_TO]->(s)
WITH t
OPTIONAL MATCH (prev:Trace {trace_id: \$prev_trace_id})
FOREACH (_ IN CASE WHEN prev IS NOT NULL THEN [1] ELSE [] END |
  CREATE (prev)-[:FOLLOWED_BY]->(t)
)
'''

params = {
    'sid': session_id,
    'ts': timestamp,
    'cwd': cwd,
    'project': project,
    'trace_id': trace_id,
    'seq': seq,
    'event_type': event_type,
    'tool_name': tool_name,
    'input_summary': input_summary,
    'output_summary': output_summary,
    'status': status,
    'error_signal': error_signal,
    'prev_trace_id': prev_trace_id,
}

# Retry detection
retry_cypher = ''
if status == 'ok' and tool_name:
    try:
        with open(os.path.join(state_dir, 'last_failed_tool')) as f:
            last_failed_tool = f.read().strip()
        with open(os.path.join(state_dir, 'last_failed_id')) as f:
            last_failed_id = f.read().strip()
        if last_failed_tool == tool_name and last_failed_id:
            retry_cypher = '''
WITH t
MATCH (failed:Trace {trace_id: \$failed_id})
CREATE (t)-[:RETRIED_AFTER]->(failed)
'''
            params['failed_id'] = last_failed_id
            os.remove(os.path.join(state_dir, 'last_failed_tool'))
            os.remove(os.path.join(state_dir, 'last_failed_id'))
    except (FileNotFoundError, IOError):
        pass

if status == 'failed' and tool_name:
    with open(os.path.join(state_dir, 'last_failed_tool'), 'w') as f:
        f.write(tool_name)
    with open(os.path.join(state_dir, 'last_failed_id'), 'w') as f:
        f.write(trace_id)

full_cypher = cypher + retry_cypher

# ── Send to Neo4j ──
neo4j_payload = json.dumps({
    'statements': [{
        'statement': full_cypher,
        'parameters': params,
    }]
})

try:
    subprocess.run(
        ['curl', '-s', '-o', '/dev/null', '-u', neo4j_auth,
         '-H', 'Content-Type: application/json',
         '-d', neo4j_payload,
         f'{neo4j_url}/db/neo4j/tx/commit'],
        timeout=5, capture_output=True
    )
except Exception:
    pass

# ── Send to Graphiti ──
content = f'[trace:{event_type}] seq={seq} tool={tool_name} status={status}'
if input_summary:
    content += f' | input: {input_summary[:300]}'
if error_signal:
    content += f' | ERROR: {error_signal}'

graphiti_payload = json.dumps({
    'group_id': group_id,
    'messages': [{
        'content': content[:1000],
        'role_type': 'user',
        'role': 'claude-hook',
        'name': f'trace-{trace_id}',
        'source_description': 'agent-trace',
        'timestamp': timestamp,
    }]
})

try:
    subprocess.run(
        ['curl', '-s', '-o', '/dev/null', '-X', 'POST',
         '-H', 'Content-Type: application/json',
         '-d', graphiti_payload,
         f'{graphiti_url}/messages'],
        timeout=5, capture_output=True
    )
except Exception:
    pass
" 2>/dev/null
) &

# ── Always return immediately ──────────────────────────────────
echo '{"continue": true}'
