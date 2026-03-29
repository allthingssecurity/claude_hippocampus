// Agentic Execution Trace Schema
// Run once: curl against Neo4j HTTP API or paste into Neo4j Browser
//
// Coexists with Graphiti's Entity/Episodic nodes — we own Trace/Session entirely.

// Constraints
CREATE CONSTRAINT trace_id IF NOT EXISTS FOR (t:Trace) REQUIRE t.trace_id IS UNIQUE;
CREATE CONSTRAINT session_node_id IF NOT EXISTS FOR (s:Session) REQUIRE s.session_id IS UNIQUE;

// Indexes for lineage queries
CREATE INDEX trace_session IF NOT EXISTS FOR (t:Trace) ON (t.session_id);
CREATE INDEX trace_seq IF NOT EXISTS FOR (t:Trace) ON (t.seq);
CREATE INDEX trace_tool IF NOT EXISTS FOR (t:Trace) ON (t.tool_name);
CREATE INDEX trace_status IF NOT EXISTS FOR (t:Trace) ON (t.status);
CREATE INDEX trace_ts IF NOT EXISTS FOR (t:Trace) ON (t.timestamp);
