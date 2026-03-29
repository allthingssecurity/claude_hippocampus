# Context Graph

Lightweight agent decision trace system using a temporal knowledge graph. Records what Claude Code knew, considered, and decided. Old traces auto-purge; crystallized knowledge persists forever.

## Architecture

```
Claude Code
  └── Graphiti MCP (HTTP, port 8100)
        └── Neo4j 5.26 (isolated instance, ports 7475/7688)

Episodes (raw traces)  ──purge after 30 days──>  gone
Entities & Facts       ──crystallized──────────>  permanent
```

**Two containers. No Python services, no SQLite, no Go binaries.**

## Prerequisites

- Docker & Docker Compose
- OpenAI API key (for Graphiti's entity extraction)

## Quick Start

```bash
cd contextgraph

# Configure
cp .env.example .env
# Edit .env — set your OPENAI_API_KEY

# Start
docker compose up -d

# Verify
curl http://localhost:8100/health

# Browse the graph
open http://localhost:7475    # Neo4j Browser (neo4j / tracegraph2026)
```

## Connect to Claude Code

Copy `.mcp.json` to any project:
```bash
cp .mcp.json /path/to/your/project/.mcp.json
```

Or register globally:
```bash
claude mcp add graphiti --transport http http://localhost:8100/mcp
```

## What Gets Captured

| What | How | Retention |
|------|-----|-----------|
| Decisions (why X over Y) | `add_episode` | 30 days (raw), facts permanent |
| Bug fixes (root cause + fix) | `add_episode` | 30 days (raw), facts permanent |
| Codebase patterns | `add_episode` | 30 days (raw), facts permanent |
| Session summaries | `add_episode` | 30 days (raw), facts permanent |
| Entities (files, services, concepts) | Auto-extracted | Permanent |
| Facts (relationships between entities) | Auto-extracted | Permanent |

## How Crystallization Works

Graphiti automatically extracts entities and facts from every episode:

```
Episode: "Chose SQLite WAL for session store — single-file, no server, handles 10k sessions"
  ↓ auto-extraction
Entity: SessionStore (component)
Entity: SQLite WAL (technology)
Fact: "SessionStore uses SQLite WAL mode" (valid_from: 2026-03-24)
Fact: "SQLite WAL handles ~10k concurrent sessions" (permanent)
```

When old episodes are purged after 30 days:
- **Entities** referenced by other episodes survive
- **Facts** referenced by other episodes survive
- Only entities/facts exclusively tied to deleted episodes are removed

Recurring knowledge compounds. One-off noise disappears.

## Auto-Purge

Set up the cron (daily at 3am):
```bash
chmod +x scripts/purge-old-traces.sh

# Add to crontab
(crontab -l 2>/dev/null; echo "0 3 * * * $(pwd)/scripts/purge-old-traces.sh 30 >> /tmp/contextgraph-purge.log 2>&1") | crontab -
```

Or run manually:
```bash
./scripts/purge-old-traces.sh 30    # purge episodes older than 30 days
```

## Useful Cypher Queries

Open Neo4j Browser at http://localhost:7475 and run:

```cypher
// All entities
MATCH (n:Entity) RETURN n LIMIT 50

// All facts between entities
MATCH (a:Entity)-[r]->(b:Entity) RETURN a, r, b LIMIT 100

// Decisions about a specific file/module
MATCH (e:Episode) WHERE e.body CONTAINS 'auth' RETURN e ORDER BY e.created_at DESC

// Knowledge graph for a concept
MATCH (n:Entity {name: 'SessionStore'})-[r]-(m) RETURN n, r, m

// Timeline of all episodes
MATCH (e:Episode) RETURN e.name, e.created_at ORDER BY e.created_at DESC LIMIT 20
```

## File Structure

```
contextgraph/
  docker-compose.yml          # Neo4j (isolated) + Graphiti MCP
  .env.example                # Config template
  .mcp.json                   # MCP registration (copy to projects)
  CLAUDE.md                   # Agent behavior instructions
  scripts/
    purge-old-traces.sh       # Cron retention script
  README.md
```

## Ports

| Service | Port | Purpose |
|---------|------|---------|
| Neo4j Browser | 7475 | Graph visualization (isolated from your existing Neo4j at 7474) |
| Neo4j Bolt | 7688 | Cypher queries (isolated from existing 7687) |
| Graphiti MCP | 8100 | MCP endpoint for Claude Code |

## Stopping

```bash
docker compose down           # Stop containers (data preserved in volumes)
docker compose down -v        # Stop + delete all trace data
```
