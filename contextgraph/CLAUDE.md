# Context Graph — Agent Decision Trace System

This project provides a temporal knowledge graph (Graphiti + Neo4j) that records agent decisions, learnings, and causal relationships. Old raw traces auto-purge; crystallized knowledge persists forever.

## Available MCP Tools

Via the `graphiti` MCP server:

| Tool | Purpose |
|------|---------|
| `add_episode` | Record a decision, discovery, or event |
| `search_facts` | Find relevant facts/learnings from past sessions |
| `search_nodes` | Find entities (files, services, concepts) in the graph |
| `get_episodes` | List recent episodes |
| `delete_episode` | Remove a specific episode |
| `get_status` | Check server health |

## Session Workflow

### At Session Start
1. Call `search_facts` with a query describing the current task
2. Call `search_nodes` if working on a specific file/module to see related context
3. Use retrieved knowledge to avoid repeating past mistakes

### During Work — Record Significant Decisions
Call `add_episode` for these events:

**Architectural decisions:**
```
name: "Chose connection pooling strategy"
episode_body: "Selected SQLite WAL mode over PostgreSQL for session store. Reason: single-file deployment, no server needed. Trade-off: limited to ~10k concurrent sessions. Files: src/session/store.rs"
source: text
source_description: "architectural decision"
group_id: "claude-traces"
```

**Bug fixes:**
```
name: "Fixed JWT expiration race condition"
episode_body: "Root cause: token validation checked expiry before clock sync. Fix: added 30s grace period in validate_token(). Files: src/auth/jwt.rs:142"
source: text
source_description: "bugfix"
group_id: "claude-traces"
```

**Discoveries about the codebase:**
```
name: "Config loading order matters"
episode_body: "CLAUDE.md is loaded before .env files. Environment variables in .env override CLAUDE.md settings. This caused the API key issue in session #42."
source: text
source_description: "discovery"
group_id: "claude-traces"
```

**Patterns learned:**
```
name: "Test files mirror source structure"
episode_body: "In this project, test files are at tests/<module>_test.rs mirroring src/<module>.rs. Always check for existing tests before creating new test files."
source: text
source_description: "pattern"
group_id: "claude-traces"
```

### At Session End
Always record a session summary:
```
name: "Session summary: <date> <brief goal>"
episode_body: "Goal: <objective>\nAccomplished: <what was done>\nKey decisions: <choices made and why>\nDiscoveries: <new learnings>\nFiles touched: <list>"
source: text
source_description: "session summary"
group_id: "claude-traces"
```

## How Crystallization Works

Graphiti automatically extracts **entities** and **facts** from every episode:
- Episode: "Chose SQLite WAL mode for session store because single-file deployment"
- Extracted entity: `SessionStore` (type: component)
- Extracted fact: `SessionStore uses SQLite WAL mode` (with temporal validity)
- Extracted fact: `SQLite WAL supports ~10k concurrent sessions`

When old episodes are purged, entities and facts that appear across multiple episodes **survive**. This is automatic crystallization — recurring knowledge persists, one-off noise disappears.

## Graph Structure

```
(:Entity {name, type})
  -[:RELATES_TO {fact, valid_from, valid_to}]->
(:Entity)

(:Episode {name, body, source, created_at})
  -[:MENTIONS]->
(:Entity)
```

Browse the graph: http://localhost:7475 (Neo4j Browser, login: neo4j / ${NEO4J_PASSWORD})

## Group ID Convention

Always use `group_id: "claude-traces"` for all episodes. This keeps agent traces isolated from any other data in the graph.
