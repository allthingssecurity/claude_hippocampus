#!/usr/bin/env bash
# crystallize-lessons.sh — Compress raw traces into permanent lessons
#
# Reads failure/retry patterns from Neo4j, synthesizes lessons,
# and writes them to Graphiti as permanent facts.
#
# Run weekly via cron or manually:
#   ./scripts/crystallize-lessons.sh
#
# Cron: 0 4 * * 0  /path/to/crystallize-lessons.sh >> /tmp/crystallize.log 2>&1

set -euo pipefail

NEO4J_URL="${TRACE_NEO4J_URL:-http://localhost:7475}"
NEO4J_AUTH="${TRACE_NEO4J_AUTH:-neo4j:${NEO4J_PASSWORD:-changeme}}"
GRAPHITI_URL="${TRACE_GRAPHITI_URL:-http://localhost:8100}"
GROUP_ID="${TRACE_GROUP_ID:-claude-traces}"

echo "$(date -Iseconds) Crystallizing lessons from traces..."

python3 -c "
import json, subprocess
from datetime import datetime, timezone

neo4j_url = '${NEO4J_URL}'
neo4j_auth = '${NEO4J_AUTH}'
graphiti_url = '${GRAPHITI_URL}'
group_id = '${GROUP_ID}'

def cypher(q):
    try:
        r = subprocess.run(
            ['curl', '-s', '-u', neo4j_auth, '-H', 'Content-Type: application/json',
             '-d', json.dumps({'statements': [{'statement': q}]}),
             f'{neo4j_url}/db/neo4j/tx/commit'],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(r.stdout)
        rows = data.get('results', [{}])[0].get('data', [])
        cols = data.get('results', [{}])[0].get('columns', [])
        return [dict(zip(cols, row['row'])) for row in rows]
    except Exception as e:
        print(f'  Neo4j error: {e}')
        return []

def add_lesson(title, content):
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        'group_id': group_id,
        'messages': [{
            'content': f'[lesson] {title}: {content}',
            'role_type': 'system',
            'role': 'crystallizer',
            'name': f'lesson-{title[:50]}',
            'source_description': 'crystallized-lesson',
            'timestamp': now,
        }]
    }
    try:
        r = subprocess.run(
            ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', '-X', 'POST',
             '-H', 'Content-Type: application/json',
             '-d', json.dumps(payload), f'{graphiti_url}/messages'],
            capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip() == '202'
    except Exception:
        return False

lessons_added = 0

# 1. Tool failure patterns → 'avoid' lessons
print('  Analyzing failure patterns...')
failures = cypher('''
MATCH (t:Trace) WHERE t.status = \"failed\" AND t.tool_name <> \"\"
WITH t.tool_name AS tool, collect(DISTINCT t.error_signal)[..5] AS errors, count(*) AS n
WHERE n >= 3
RETURN tool, n, errors
ORDER BY n DESC LIMIT 5
''')
for f in failures:
    errs = [e[:80] for e in f['errors'] if e]
    if errs:
        title = f\"{f['tool']} common failure pattern\"
        content = f\"{f['tool']} has failed {f['n']} times. Common errors: {'; '.join(errs)}. Consider checking prerequisites before using this tool or trying alternative approaches.\"
        if add_lesson(title, content):
            lessons_added += 1
            print(f'  + {title}')

# 2. Successful retry patterns → 'when X fails, do Y' lessons
print('  Analyzing retry patterns...')
retries = cypher('''
MATCH (ok:Trace)-[:RETRIED_AFTER]->(fail:Trace)
WHERE ok.status = \"ok\"
WITH fail.tool_name AS tool, fail.error_signal AS error,
     collect({fix_tool: ok.tool_name, fix_input: substring(ok.input_summary, 0, 100)})[0] AS fix,
     count(*) AS n
WHERE n >= 1
RETURN tool, error, fix, n
ORDER BY n DESC LIMIT 5
''')
for r in retries:
    err = r.get('error', '')[:80]
    fix = r.get('fix', {})
    if err and fix:
        title = f\"Recovery pattern for {r['tool']}\"
        content = f\"When {r['tool']} fails with '{err}', successfully recovered by using {fix.get('fix_tool', '?')} with: {fix.get('fix_input', '?')[:100]}\"
        if add_lesson(title, content):
            lessons_added += 1
            print(f'  + {title}')

# 3. Project workflow patterns → 'this project typically' lessons
print('  Analyzing project patterns...')
projects = cypher('''
MATCH (s:Session)<-[:BELONGS_TO]-(t:Trace)
WHERE s.project IS NOT NULL AND s.project <> 'unknown'
WITH s.project AS project, count(DISTINCT s) AS sessions,
     collect(DISTINCT t.tool_name) AS tools
WHERE sessions >= 3
RETURN project, sessions, tools[..10] AS top_tools
ORDER BY sessions DESC LIMIT 5
''')
for p in projects:
    tools = [t for t in p.get('top_tools', []) if t]
    if tools:
        title = f\"Workflow pattern for {p['project']}\"
        content = f\"Project {p['project']} has had {p['sessions']} sessions. Primary tools used: {', '.join(tools[:8])}. This indicates the typical workflow for this project.\"
        if add_lesson(title, content):
            lessons_added += 1
            print(f'  + {title}')

# 4. Session outcomes → 'sessions about X tend to' lessons
print('  Analyzing session outcomes...')
outcomes = cypher('''
MATCH (s:Session)<-[:BELONGS_TO]-(t:Trace)
WITH s, count(t) AS steps,
     sum(CASE WHEN t.status = 'failed' THEN 1 ELSE 0 END) AS failures
WHERE steps > 10
RETURN s.project AS project, avg(steps) AS avg_steps, avg(failures) AS avg_failures,
       count(s) AS session_count
ORDER BY avg_failures DESC LIMIT 3
''')
for o in outcomes:
    if o.get('avg_failures', 0) > 2:
        title = f\"High failure rate in {o['project']}\"
        content = f\"Sessions in {o['project']} average {o['avg_steps']:.0f} steps with {o['avg_failures']:.1f} failures. Consider more careful planning before executing in this project.\"
        if add_lesson(title, content):
            lessons_added += 1
            print(f'  + {title}')

print(f'\\nCrystallized {lessons_added} lessons into knowledge graph.')
"

echo "$(date -Iseconds) Crystallization complete"
