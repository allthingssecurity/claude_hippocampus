#!/bin/bash
# Purge old Graphiti episodes while preserving crystallized entities/facts.
#
# Graphiti's entity extraction means entities and facts that appear in
# multiple episodes survive even after their source episodes are deleted.
# Only entities exclusively referenced by deleted episodes are removed.
#
# Usage: ./scripts/purge-old-traces.sh [retention_days]
# Cron:  0 3 * * * /path/to/contextgraph/scripts/purge-old-traces.sh 30

set -e

RETENTION_DAYS=${1:-30}
GRAPHITI_URL="${GRAPHITI_URL:-http://localhost:8100}"
GROUP_ID="${GRAPHITI_GROUP_ID:-claude-traces}"

echo "$(date -Iseconds) Purge starting (retention: ${RETENTION_DAYS} days)"

# Check MCP server is up
if ! curl -sf "${GRAPHITI_URL}/health" >/dev/null 2>&1; then
    echo "  ERROR: Graphiti MCP not reachable at ${GRAPHITI_URL}"
    exit 1
fi

# Calculate cutoff date
if date -v-1d +%Y-%m-%d >/dev/null 2>&1; then
    # macOS
    CUTOFF=$(date -v-${RETENTION_DAYS}d -u +%Y-%m-%dT%H:%M:%SZ)
else
    # Linux
    CUTOFF=$(date -u -d "-${RETENTION_DAYS} days" +%Y-%m-%dT%H:%M:%SZ)
fi
echo "  Cutoff date: ${CUTOFF}"

# Get episodes via Graphiti MCP endpoint
# The MCP tool get_episodes returns recent episodes for a group
EPISODES_RESPONSE=$(curl -sf "${GRAPHITI_URL}/mcp" \
    -H "Content-Type: application/json" \
    -d "{
        \"jsonrpc\": \"2.0\",
        \"id\": 1,
        \"method\": \"tools/call\",
        \"params\": {
            \"name\": \"get_episodes\",
            \"arguments\": {
                \"group_id\": \"${GROUP_ID}\",
                \"last_n\": 1000
            }
        }
    }" 2>/dev/null)

if [ -z "$EPISODES_RESPONSE" ]; then
    echo "  No episodes found or API error"
    exit 0
fi

# Extract episode UUIDs older than cutoff and delete them
# Parse with python3 (available on macOS)
DELETED=0
OLD_EPISODES=$(echo "$EPISODES_RESPONSE" | python3 -c "
import json, sys
from datetime import datetime
cutoff = datetime.fromisoformat('${CUTOFF}'.replace('Z', '+00:00'))
try:
    data = json.load(sys.stdin)
    result = data.get('result', {})
    # Handle different response formats
    content = result.get('content', [])
    if isinstance(content, list):
        for item in content:
            text = item.get('text', '') if isinstance(item, dict) else str(item)
            try:
                episodes = json.loads(text) if isinstance(text, str) else text
                if isinstance(episodes, list):
                    for ep in episodes:
                        created = ep.get('created_at', '')
                        if created:
                            ep_time = datetime.fromisoformat(created.replace('Z', '+00:00'))
                            if ep_time < cutoff:
                                print(ep.get('uuid', ''))
            except (json.JSONDecodeError, ValueError):
                pass
except Exception as e:
    print(f'# Error: {e}', file=sys.stderr)
" 2>/dev/null)

for UUID in $OLD_EPISODES; do
    if [ -n "$UUID" ]; then
        curl -sf "${GRAPHITI_URL}/mcp" \
            -H "Content-Type: application/json" \
            -d "{
                \"jsonrpc\": \"2.0\",
                \"id\": 1,
                \"method\": \"tools/call\",
                \"params\": {
                    \"name\": \"delete_episode\",
                    \"arguments\": {
                        \"episode_uuid\": \"${UUID}\"
                    }
                }
            }" >/dev/null 2>&1
        DELETED=$((DELETED + 1))
    fi
done

echo "  Deleted ${DELETED} episodes older than ${RETENTION_DAYS} days"
echo "  Entities and facts from multiple episodes are preserved (crystallized)"

# Neo4j stats
NEO4J_PASSWORD="${NEO4J_PASSWORD:-tracegraph2026}"
NODE_COUNT=$(docker exec contextgraph-neo4j cypher-shell -u neo4j -p "${NEO4J_PASSWORD}" "MATCH (n) RETURN count(n) AS c" 2>/dev/null | tail -1 || echo "?")
REL_COUNT=$(docker exec contextgraph-neo4j cypher-shell -u neo4j -p "${NEO4J_PASSWORD}" "MATCH ()-[r]->() RETURN count(r) AS c" 2>/dev/null | tail -1 || echo "?")
echo "  Neo4j: ${NODE_COUNT} nodes, ${REL_COUNT} relationships"

echo "$(date -Iseconds) Purge complete"
