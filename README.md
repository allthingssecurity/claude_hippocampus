# Claude Hippocampus

A neuroscience-inspired associative memory system for Claude Code. Gives Claude Code a hippocampus (CA3 pattern completion), neocortex (knowledge graph), and basal ganglia (auto-discovered skills).

## What it does

- **Before each prompt**: Spreads activation through a co-occurrence graph to inject relevant context from prior sessions (12-150ms)
- **After each session**: Extracts concepts, builds co-activation edges, detects recurring skills automatically
- **Always**: Remembers your project patterns, error workarounds, toolchain decisions across all sessions

## Architecture

```
User prompt
    |
    v
Cue construction         <-- Entorhinal cortex
    |
    v
Seed phase               <-- Dentate gyrus
    |
    v
Spreading activation     <-- CA3: pattern completion
    |
    v
Ranking + compression    <-- CA1: output selection
    |
    v
Context packet           <-- Hippocampal output
    |
    v
Claude Code (LLM)        <-- Prefrontal cortex
    |
    v
Tool calls + traces      <-- Motor output
    |
    v
Session-end hook         <-- Sleep consolidation
    |
    +--> Extract concepts
    +--> Build co-activations (Hebbian learning)
    +--> Detect skills (basal ganglia)
```

## Results

Controlled experiments showed:

- **29% faster** completion (Python WASM compiler task)
- **13% fewer tokens** consumed
- **36% fewer tool calls** (collaborative whiteboard task)
- **Preemptive bug prevention**: Agent fixed a Redis startup race condition it had never seen in the current session, because the memory graph recalled that error from a prior session

## Setup

### Prerequisites

- Docker and Docker Compose
- Python 3.12+
- Claude Code CLI

### 1. Start Neo4j + Graphiti

```bash
cd contextgraph
cp .env.example .env
# Edit .env with your OpenAI API key (optional, for Graphiti entity extraction)
docker compose up -d
```

### 2. Initialize the schema

```bash
# Run CA3 schema additions
curl -s -u neo4j:tracegraph2026 -H "Content-Type: application/json" \
  -d @schema/ca3-schema.cypher http://localhost:7475/db/neo4j/tx/commit
```

### 3. Install Python dependencies

```bash
pip install httpx
```

### 4. Register hooks in Claude Code

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/claude_hippocampus/hooks/ca3-activation-hook.sh",
            "timeout": 5
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/claude_hippocampus/hooks/ca3-session-end-hook.sh",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

### 5. Bootstrap co-activation edges (if you have existing sessions)

```bash
bash scripts/build-coactivations.sh
```

### 6. Run tests

```bash
python3 tests/test_activation.py
```

## Project Structure

```
ca3/                     # Core associative memory engine
  activation.py          # Spreading activation (CA3 model)
  coactivation.py        # Co-occurrence edge builder (Hebbian learning)
  config.py              # Constants and thresholds
  context_packet.py      # LLM context compression
  entity_normalizer.py   # Deduplication of equivalent entities
  neo4j_client.py        # Thin Neo4j HTTP client
  scorer.py              # Multi-signal ranking (recency, workspace, activation)
  skill_detector.py      # Auto-skill detection (basal ganglia model)

hooks/                   # Claude Code hook integrations
  ca3-activation-hook.*  # UserPromptSubmit: associative recall
  ca3-session-end-hook.* # Stop: concept extraction + skill detection

contextgraph/            # Neo4j + Graphiti infrastructure
  docker-compose.yml     # Neo4j 5.26 + Graphiti containers
  hooks/                 # Trace capture hooks
  schema/                # Cypher schema definitions
  scripts/               # Maintenance (purge, crystallize)

schema/                  # CA3 schema additions
tests/                   # Integration tests (14 tests)
```

## How the brain mapping works

| Brain region | System component | Function |
|-------------|-----------------|----------|
| Neocortex | Neo4j Entity nodes | Long-term concept storage |
| Hippocampus CA3 | COACTIVATED edges + spreading activation | Associative pattern completion |
| Dentate gyrus | Keyword extraction + entity seeding | Pattern separation |
| CA1 | Ranking + compression | Output selection |
| Basal ganglia | Skill detector | Procedural skill crystallization |
| Hebbian learning | Co-activation edge building | "Fire together, wire together" |
| Sleep consolidation | Session-end hook | Memory encoding + skill detection |
| Memory decay | Exponential weight decay (23-day half-life) | Temporal relevance |

## Blog post

Full writeup: [I Gave My AI Agent a Hippocampus](https://medium.com/p/162d4ec25feb)

## License

MIT
