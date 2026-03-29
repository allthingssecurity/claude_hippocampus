#!/usr/bin/env bash
# session-context-hook.sh — Injects compressed learnings at session start
#
# NOT raw lineage. Distilled lessons:
#   - "Bash fails when X → do Y instead"
#   - "This project's tests need Z before running"
#   - "Avoid tool X for this type of task"
#
# Runs on SessionStart only. Queries Neo4j for patterns, Graphiti for knowledge.

set -euo pipefail

NEO4J_URL="${TRACE_NEO4J_URL:-http://localhost:7475}"
NEO4J_AUTH="${TRACE_NEO4J_AUTH:-neo4j:${NEO4J_PASSWORD:-changeme}}"
GRAPHITI_URL="${TRACE_GRAPHITI_URL:-http://localhost:8100}"
GROUP_ID="${TRACE_GROUP_ID:-claude-traces}"

INPUT=$(cat)

EVENT=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('hook_event_name',''))" 2>/dev/null) || EVENT=""

if [ "$EVENT" != "SessionStart" ]; then
    echo '{"continue": true}'
    exit 0
fi

CWD=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null) || CWD=""
PROJECT=$(basename "$CWD" 2>/dev/null) || PROJECT="unknown"

LESSONS=$(python3 -c "
import json, subprocess

neo4j_url = '${NEO4J_URL}'
neo4j_auth = '${NEO4J_AUTH}'
graphiti_url = '${GRAPHITI_URL}'
group_id = '${GROUP_ID}'
project = '${PROJECT}'

def cypher(q, params=None):
    payload = {'statements': [{'statement': q}]}
    if params:
        payload['statements'][0]['parameters'] = params
    try:
        r = subprocess.run(
            ['curl', '-s', '-u', neo4j_auth, '-H', 'Content-Type: application/json',
             '-d', json.dumps(payload), f'{neo4j_url}/db/neo4j/tx/commit'],
            capture_output=True, text=True, timeout=5
        )
        data = json.loads(r.stdout)
        rows = data.get('results', [{}])[0].get('data', [])
        cols = data.get('results', [{}])[0].get('columns', [])
        return [dict(zip(cols, row['row'])) for row in rows]
    except Exception:
        return []

def graphiti_search(query, n=5):
    try:
        r = subprocess.run(
            ['curl', '-s', '-X', 'POST', '-H', 'Content-Type: application/json',
             '-d', json.dumps({'group_ids': [group_id], 'query': query, 'max_facts': n}),
             f'{graphiti_url}/search'],
            capture_output=True, text=True, timeout=5
        )
        return json.loads(r.stdout) if r.stdout.strip() else []
    except Exception:
        return []

lessons = []

# 1. Failure patterns → compressed into 'avoid X' lessons
patterns = cypher('''
MATCH (t:Trace) WHERE t.status = \"failed\" AND t.tool_name <> \"\"
WITH t.tool_name AS tool, t.error_signal AS err, count(*) AS n
WHERE n >= 2
RETURN tool, n, collect(DISTINCT err)[..2] AS errors
ORDER BY n DESC LIMIT 3
''')
for p in patterns:
    errs = [e[:60] for e in p.get('errors', []) if e]
    if errs:
        lessons.append(f\"{p['tool']} has failed {p['n']}x with: {'; '.join(errs)}. Consider alternative approaches.\")

# 2. Successful retries → 'when X fails, Y works' lessons
retries = cypher('''
MATCH (ok:Trace)-[:RETRIED_AFTER]->(fail:Trace)
WHERE ok.status = \"ok\"
RETURN fail.tool_name AS failed_tool, fail.error_signal AS error,
       ok.tool_name AS fix_tool, substring(ok.input_summary, 0, 80) AS fix_input
ORDER BY ok.timestamp DESC LIMIT 3
''')
for r in retries:
    err = r.get('error', '')[:60]
    fix = r.get('fix_input', '')[:60]
    if err:
        lessons.append(f\"When {r['failed_tool']} fails with '{err}', retry with: {fix}\")

# 3. Project-specific: what tools are used here (helps Claude pick the right approach)
project_tools = cypher('''
MATCH (t:Trace)-[:BELONGS_TO]->(s:Session)
WHERE s.project = \$project AND t.tool_name <> \"\"
RETURN t.tool_name AS tool, count(t) AS uses
ORDER BY uses DESC LIMIT 5
''', {'project': project})
if project_tools:
    tools = [f\"{t['tool']}({t['uses']}x)\" for t in project_tools]
    lessons.append(f\"Most used tools in {project}: {', '.join(tools)}\")

# 4. Graphiti crystallized facts (the permanent knowledge)
facts = graphiti_search(f'lessons patterns decisions for {project}', 5)
for f in facts:
    fact_text = f.get('fact', '') if isinstance(f, dict) else str(f)
    if fact_text and len(fact_text) > 10:
        lessons.append(fact_text[:150])

# Output only if we have something useful
if lessons:
    print('\\n'.join(f'- {l}' for l in lessons[:8]))
" 2>/dev/null) || LESSONS=""

if [ -n "$LESSONS" ] && [ "$LESSONS" != "" ]; then
    python3 -c "
import json
lessons = '''$LESSONS'''
if lessons.strip():
    msg = 'Lessons from past sessions:\\n' + lessons.strip()
    print(json.dumps({'continue': True, 'suppressOutput': True, 'userMessage': msg}))
else:
    print(json.dumps({'continue': True}))
" 2>/dev/null
else
    echo '{"continue": true}'
fi
