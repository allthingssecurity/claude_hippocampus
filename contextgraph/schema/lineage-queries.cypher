// ═══════════════════════════════════════════════════════════════
// AGENTIC LINEAGE QUERIES — Reference for Neo4j Browser
// Open http://localhost:7475 | Login: neo4j / tracegraph2026
// ═══════════════════════════════════════════════════════════════

// ── LIST ALL SESSIONS ──────────────────────────────────────────
// Overview of all agent sessions with trace counts and failure rates
MATCH (s:Session)
OPTIONAL MATCH (t:Trace)-[:BELONGS_TO]->(s)
WITH s, count(t) AS traces,
     sum(CASE WHEN t.status = 'failed' THEN 1 ELSE 0 END) AS failures
RETURN s.session_id AS session, s.started_at AS started,
       s.project AS project, traces, failures
ORDER BY s.started_at DESC LIMIT 20;


// ── FULL SESSION TIMELINE ──────────────────────────────────────
// Every agent action in order for a specific session
// Replace 'SESSION_ID_HERE' with actual session_id
MATCH (t:Trace {session_id: 'SESSION_ID_HERE'})
RETURN t.seq AS step, t.event_type AS event, t.tool_name AS tool,
       t.status AS status, t.input_summary AS input,
       left(t.output_summary, 100) AS output, t.error_signal AS error
ORDER BY t.seq;


// ── VISUAL CAUSAL CHAIN ───────────────────────────────────────
// Graph view: click this in Neo4j Browser to see the linked trace
// Replace 'SESSION_ID_HERE' with actual session_id
MATCH (t:Trace {session_id: 'SESSION_ID_HERE'})
OPTIONAL MATCH (t)-[r:FOLLOWED_BY]->(next:Trace)
RETURN t, r, next
ORDER BY t.seq;


// ── LATEST SESSION LINEAGE (auto-detect) ──────────────────────
// Automatically finds the most recent session and shows its full chain
MATCH (s:Session)
WITH s ORDER BY s.started_at DESC LIMIT 1
MATCH (t:Trace)-[:BELONGS_TO]->(s)
OPTIONAL MATCH (t)-[f:FOLLOWED_BY]->(next:Trace)
RETURN t, f, next
ORDER BY t.seq;


// ── ALL FAILURES IN A SESSION ─────────────────────────────────
// What went wrong and where
MATCH (t:Trace {session_id: 'SESSION_ID_HERE', status: 'failed'})
RETURN t.seq AS step, t.tool_name AS tool,
       t.error_signal AS error, t.input_summary AS input
ORDER BY t.seq;


// ── RETRY CHAINS (failure → recovery) ─────────────────────────
// Shows where agent failed and how it recovered
MATCH (recovery:Trace)-[:RETRIED_AFTER]->(failure:Trace)
WHERE recovery.session_id = 'SESSION_ID_HERE'
RETURN failure.seq AS failed_step, failure.tool_name AS tool,
       failure.error_signal AS error,
       recovery.seq AS retry_step, recovery.input_summary AS retry_input
ORDER BY failure.seq;


// ── WHAT LED TO A SPECIFIC STEP ───────────────────────────────
// Trace backwards from step N to see the causal chain
// Replace SESSION_ID_HERE and 10 (target step number)
MATCH path = (t:Trace)-[:FOLLOWED_BY*]->(target:Trace {session_id: 'SESSION_ID_HERE', seq: 10})
RETURN path;


// ── CROSS-SESSION ERROR PATTERNS ──────────────────────────────
// Most common errors across all sessions
MATCH (t:Trace {status: 'failed'})
RETURN t.tool_name AS tool, t.error_signal AS error, count(*) AS occurrences
ORDER BY occurrences DESC LIMIT 20;


// ── TOOL USAGE FREQUENCY ──────────────────────────────────────
// Which tools are used most and their failure rates
MATCH (t:Trace {event_type: 'tool_call'})
RETURN t.tool_name AS tool, count(*) AS calls,
       sum(CASE WHEN t.status = 'failed' THEN 1 ELSE 0 END) AS failures,
       round(100.0 * sum(CASE WHEN t.status = 'failed' THEN 1 ELSE 0 END) / count(*), 1) AS fail_pct
ORDER BY calls DESC;


// ── DECISION TRACE: user prompt → next prompt ─────────────────
// See everything the agent did between two user messages
// Shows one "turn" of agent reasoning
MATCH (start:Trace {session_id: 'SESSION_ID_HERE', event_type: 'user_prompt'})
WHERE start.seq = 0
MATCH path = (start)-[:FOLLOWED_BY*1..50]->(t:Trace)
WHERE NOT EXISTS {
  MATCH (mid:Trace {session_id: 'SESSION_ID_HERE', event_type: 'user_prompt'})
  WHERE mid.seq > start.seq AND mid.seq < t.seq
}
RETURN path;


// ── SESSION SUMMARY (compact) ─────────────────────────────────
// One-line-per-step summary of a session
MATCH (t:Trace {session_id: 'SESSION_ID_HERE'})
RETURN t.seq AS '#',
       t.event_type AS type,
       CASE WHEN t.tool_name <> '' THEN t.tool_name ELSE '-' END AS tool,
       CASE WHEN t.status = 'failed' THEN 'FAIL' ELSE 'ok' END AS status,
       left(t.input_summary, 60) AS input
ORDER BY t.seq;
