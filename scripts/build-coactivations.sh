#!/usr/bin/env bash
# build-coactivations.sh — Build/refresh COACTIVATED edges from session data
#
# Run manually to bootstrap, or via cron:
#   0 5 * * * /Users/I074560/Downloads/experiments/claude_nous/scripts/build-coactivations.sh

set -euo pipefail

echo "$(date -Iseconds) Building co-activation edges..."

python3 -c "
import sys
sys.path.insert(0, '/Users/I074560/Downloads/experiments/claude_nous')
from ca3.coactivation import build_all_coactivations
stats = build_all_coactivations()
print(f'  Sessions processed: {stats[\"sessions\"]}')
print(f'  Edges created/updated: {stats[\"edges\"]}')
print(f'  Total COACTIVATED edges in DB: {stats[\"total\"]}')
"

echo "$(date -Iseconds) Co-activation build complete"
