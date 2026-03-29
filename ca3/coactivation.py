"""Co-activation edge builder.

Processes sessions to find Entity pairs that co-occur and creates/strengthens
COACTIVATED edges between them in Neo4j.

Also indexes Claude Code skills as Entity nodes.
"""

import math
from datetime import datetime, timezone
from .neo4j_client import Neo4jClient
from .config import RECENCY_LAMBDA, GROUP_ID, ENTITY_NAME_MAX_LEN, ENTITY_NAME_SKIP_PREFIXES


# Skills available in Claude Code — indexed as Entity nodes
SKILLS = [
    {"name": "/commit", "summary": "Create a git commit with staged changes. Analyzes diff, drafts message, stages and commits."},
    {"name": "/simplify", "summary": "Review changed code for reuse, quality, and efficiency, then fix issues found."},
    {"name": "/loop", "summary": "Run a prompt or slash command on a recurring interval (e.g. /loop 5m /foo)."},
    {"name": "/paper-teach", "summary": "Transform research papers into interactive 3D teaching pages with Three.js, KaTeX math, and difficulty levels."},
    {"name": "/codebase-to-course", "summary": "Turn any codebase into a beautiful interactive single-page HTML course for non-technical people."},
    {"name": "/claude-api", "summary": "Build apps with the Claude API or Anthropic SDK. Triggers on anthropic imports."},
    {"name": "/review-pr", "summary": "Review a pull request, analyze changes, provide feedback on code quality and correctness."},
]

# Concepts that skills are associated with — used to create COACTIVATED edges
SKILL_ASSOCIATIONS = {
    "/commit": ["git", "version control", "staging", "diff", "branch"],
    "/simplify": ["refactoring", "code quality", "code review", "DRY principle"],
    "/paper-teach": ["research paper", "visualization", "Three.js", "interactive teaching", "KaTeX"],
    "/codebase-to-course": ["documentation", "tutorial", "course", "teaching", "interactive"],
    "/claude-api": ["anthropic", "Claude API", "SDK", "tool use", "streaming"],
    "/review-pr": ["pull request", "code review", "GitHub", "diff review"],
    "/loop": ["cron", "recurring", "polling", "monitoring", "interval"],
}


def _is_noise_entity(name: str) -> bool:
    """Filter out entities that are file paths, URLs, or too long."""
    if not name or len(name) > ENTITY_NAME_MAX_LEN:
        return True
    for prefix in ENTITY_NAME_SKIP_PREFIXES:
        if name.startswith(prefix):
            return True
    return False


def _compute_weight(count: int, last_ts_str: str | None) -> float:
    """Weight = count * recency_decay."""
    if not last_ts_str:
        return float(count)
    try:
        last = datetime.fromisoformat(last_ts_str.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - last).total_seconds() / 86400
        recency = math.exp(-RECENCY_LAMBDA * days)
    except (ValueError, TypeError):
        recency = 0.5
    return count * recency


def index_skills(db: Neo4jClient) -> int:
    """Create/update Entity nodes for Claude Code skills and their associations."""
    indexed = 0
    for skill in SKILLS:
        db.query(
            """
            MERGE (e:Entity {group_id: $group_id, name: $name})
            ON CREATE SET
              e.uuid = randomUUID(),
              e.summary = $summary,
              e.entity_type = 'skill',
              e.created_at = toString(datetime())
            ON MATCH SET
              e.summary = $summary,
              e.entity_type = 'skill'
            RETURN e.uuid AS uuid
            """,
            {"group_id": GROUP_ID, "name": skill["name"], "summary": skill["summary"]},
        )
        indexed += 1

    # Create COACTIVATED edges between skills and associated concept entities
    for skill_name, concepts in SKILL_ASSOCIATIONS.items():
        for concept in concepts:
            # Find existing entities matching the concept
            db.query(
                """
                MATCH (skill:Entity {group_id: $group_id, name: $skill_name})
                MATCH (concept:Entity)
                WHERE concept.group_id = $group_id
                  AND toLower(concept.name) = toLower($concept)
                  AND concept.uuid <> skill.uuid
                MERGE (skill)-[c:COACTIVATED]-(concept)
                ON CREATE SET
                  c.count = 3,
                  c.last_session = 'skill-index',
                  c.last_ts = toString(datetime()),
                  c.contexts = ['skills'],
                  c.weight = 3.0
                RETURN count(*) AS n
                """,
                {"group_id": GROUP_ID, "skill_name": skill_name, "concept": concept},
            )

    return indexed


def extract_concepts_from_traces(session_id: str, db: Neo4jClient) -> int:
    """Extract meaningful concepts from trace input/output summaries.

    Creates Entity nodes for concepts found in tool call traces — no LLM needed.
    Uses keyword extraction to find technical terms, project names, and patterns.
    This replaces Graphiti's OpenAI-dependent entity extraction.
    """
    import re
    from .config import STOPWORDS

    # Get all trace summaries for this session
    traces = db.query(
        """
        MATCH (t:Trace)-[:BELONGS_TO]->(s:Session {session_id: $sid})
        WHERE t.input_summary IS NOT NULL OR t.output_summary IS NOT NULL
        RETURN COALESCE(t.input_summary, '') AS input,
               COALESCE(t.output_summary, '') AS output,
               t.tool_name AS tool,
               COALESCE(t.error_signal, '') AS error
        """,
        {"sid": session_id},
    )

    if not traces:
        return 0

    # Combine all text for concept extraction
    all_text = " ".join(
        f"{t['input']} {t['output']} {t['error']}" for t in traces
    )

    # Extract technical terms using patterns
    concepts = set()

    # Multi-word technical terms (capitalized phrases, hyphenated terms)
    for match in re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", all_text):
        if 3 < len(match) <= 60:
            concepts.add(match)

    # Hyphenated technical terms (wasm-pack, wasm-bindgen, etc.)
    for match in re.findall(r"[a-zA-Z]+-[a-zA-Z]+(?:-[a-zA-Z]+)*", all_text):
        if 4 < len(match) <= 40 and match.lower() not in STOPWORDS:
            concepts.add(match.lower())

    # CamelCase identifiers
    for match in re.findall(r"[A-Z][a-z]+[A-Z][a-zA-Z]+", all_text):
        if 4 < len(match) <= 40:
            concepts.add(match)

    # Known technical patterns
    tech_patterns = [
        r"\b(?:Rust|Python|JavaScript|TypeScript|Go|C\+\+|Java|Ruby|Swift)\b",
        r"\b(?:WASM|WebAssembly|Docker|Kubernetes|Redis|Neo4j|PostgreSQL|SQLite)\b",
        r"\b(?:React|Vue|Angular|FastAPI|Flask|Django|Express|Next\.js)\b",
        r"\b(?:SVG|Canvas|WebGL|Three\.js|D3\.js)\b",
        r"\b(?:API|REST|GraphQL|gRPC|WebSocket|HTTP|HTTPS)\b",
        r"\b(?:JWT|OAuth|CORS|SSL|TLS)\b",
        r"\b(?:npm|pip|cargo|yarn|pnpm|brew)\b",
        r"\b(?:git|GitHub|GitLab|CI|CD)\b",
    ]
    for pattern in tech_patterns:
        for match in re.findall(pattern, all_text):
            concepts.add(match)

    # Error-specific concepts
    for match in re.findall(r"(\w+Error|\w+Exception)", all_text):
        concepts.add(match)

    # Filter noise
    filtered = set()
    for c in concepts:
        if len(c) <= 3:
            continue
        if c.lower() in STOPWORDS:
            continue
        if any(c.startswith(p) for p in ENTITY_NAME_SKIP_PREFIXES):
            continue
        filtered.add(c)

    # Create Entity nodes
    created = 0
    for concept in filtered:
        result = db.query(
            """
            MERGE (e:Entity {group_id: $gid, name: $name})
            ON CREATE SET
              e.uuid = randomUUID(),
              e.summary = $summary,
              e.entity_type = 'concept',
              e.created_at = toString(datetime())
            RETURN e.uuid AS uuid
            """,
            {
                "gid": GROUP_ID,
                "name": concept,
                "summary": f"Concept extracted from session {session_id[:12]}... traces.",
            },
        )
        if result:
            created += 1

    return created


def build_coactivations_for_session(session_id: str, db: Neo4jClient) -> int:
    """Build COACTIVATED edges for entities co-occurring in a single session.

    Only connects "clean" entities (not file paths, URLs, UUIDs).
    Uses both Episodic→MENTIONS and Trace.tool_name matching.
    """
    # Step 1: Get entities mentioned in this session's episodes (non-noise only)
    entities_from_episodes = db.query(
        """
        MATCH (ep:Episodic)-[:MENTIONS]->(e:Entity)
        WHERE ep.group_id = $group_id
          AND ep.content CONTAINS $sid
          AND size(e.name) <= $max_name_len
          AND NOT (e.name STARTS WITH '/Users/' OR e.name STARTS WITH '/tmp/'
                OR e.name STARTS WITH '/private/' OR e.name STARTS WITH '/var/'
                OR e.name STARTS WITH 'http://' OR e.name STARTS WITH 'https://'
                OR e.name STARTS WITH '/workspace/')
        RETURN DISTINCT e.uuid AS uuid, e.name AS name
        """,
        {"group_id": GROUP_ID, "sid": session_id, "max_name_len": ENTITY_NAME_MAX_LEN},
    )

    # Step 2: Get entities matching tool names (exact match, not CONTAINS)
    tool_entities = db.query(
        """
        MATCH (t:Trace)-[:BELONGS_TO]->(s:Session {session_id: $sid})
        WHERE t.tool_name <> ''
        WITH DISTINCT t.tool_name AS tool_name
        MATCH (e:Entity)
        WHERE e.group_id = $group_id
          AND (toLower(e.name) = toLower(tool_name)
               OR toLower(e.name) = toLower(tool_name) + ' tool')
          AND size(e.name) <= $max_name_len
        RETURN DISTINCT e.uuid AS uuid, e.name AS name
        """,
        {"sid": session_id, "group_id": GROUP_ID, "max_name_len": ENTITY_NAME_MAX_LEN},
    )

    # Step 2b: Get concepts extracted from this session's traces
    # (created by extract_concepts_from_traces, tagged with session_id in summary)
    extracted_concepts = db.query(
        """
        MATCH (e:Entity)
        WHERE e.group_id = $group_id
          AND e.entity_type = 'concept'
          AND e.summary CONTAINS $sid_prefix
          AND size(e.name) <= $max_name_len
          AND NOT (e.name STARTS WITH '/Users/' OR e.name STARTS WITH '/tmp/'
                OR e.name STARTS WITH 'http://')
        RETURN DISTINCT e.uuid AS uuid, e.name AS name
        """,
        {
            "group_id": GROUP_ID,
            "sid_prefix": session_id[:12],
            "max_name_len": ENTITY_NAME_MAX_LEN,
        },
    )

    # Merge and deduplicate by normalized name
    seen_names: dict[str, str] = {}
    entity_uuids = []
    for e in entities_from_episodes + tool_entities + extracted_concepts:
        norm = e["name"].lower().strip()
        if norm not in seen_names:
            seen_names[norm] = e["uuid"]
            entity_uuids.append(e["uuid"])

    if len(entity_uuids) < 2:
        return 0

    # Step 3: Get session project
    sessions = db.query(
        "MATCH (s:Session {session_id: $sid}) RETURN s.project AS project",
        {"sid": session_id},
    )
    project = sessions[0]["project"] if sessions else "unknown"

    # Step 4: Cap entity set and MERGE COACTIVATED edges
    entity_uuids = entity_uuids[:25]

    edges_updated = db.query(
        """
        UNWIND $uuids AS uid1
        UNWIND $uuids AS uid2
        WITH uid1, uid2 WHERE uid1 < uid2
        MATCH (a:Entity {uuid: uid1}), (b:Entity {uuid: uid2})
        MERGE (a)-[c:COACTIVATED]-(b)
        ON CREATE SET
          c.count = 1,
          c.last_session = $sid,
          c.last_ts = toString(datetime()),
          c.contexts = [$project],
          c.weight = 1.0
        ON MATCH SET
          c.count = c.count + 1,
          c.last_session = $sid,
          c.last_ts = toString(datetime()),
          c.contexts = (CASE WHEN NOT $project IN c.contexts
                        THEN (c.contexts + $project)[-5..]
                        ELSE c.contexts END)
        RETURN count(*) AS updated
        """,
        {"uuids": entity_uuids, "sid": session_id, "project": project},
    )

    n_updated = edges_updated[0]["updated"] if edges_updated else 0

    # Step 5: Recompute weights
    if n_updated > 0:
        edges = db.query(
            """
            MATCH (a:Entity)-[c:COACTIVATED]-(b:Entity)
            WHERE c.last_session = $sid
            RETURN id(c) AS rel_id, c.count AS count, c.last_ts AS last_ts
            """,
            {"sid": session_id},
        )
        for edge in edges:
            weight = _compute_weight(edge["count"], edge.get("last_ts"))
            db.execute(
                "MATCH ()-[c:COACTIVATED]-() WHERE id(c) = $rel_id SET c.weight = $weight",
                {"rel_id": edge["rel_id"], "weight": weight},
            )

    return n_updated


def build_all_coactivations(since: str | None = None, extract_concepts: bool = True) -> dict:
    """Build COACTIVATED edges for all sessions. Also indexes skills and extracts concepts."""
    db = Neo4jClient()
    try:
        # Index skills first
        skills_indexed = index_skills(db)

        # Normalize and deduplicate entities
        from .entity_normalizer import merge_duplicate_entities
        entities_merged = merge_duplicate_entities(db)

        # Extract concepts from traces (replaces Graphiti's OpenAI extraction)
        concepts_extracted = 0
        if extract_concepts:
            all_sessions = db.query(
                "MATCH (s:Session) RETURN s.session_id AS sid ORDER BY s.started_at"
            )
            for s in all_sessions:
                concepts_extracted += extract_concepts_from_traces(s["sid"], db)

        if since:
            sessions = db.query(
                "MATCH (s:Session) WHERE s.started_at >= $since RETURN s.session_id AS sid ORDER BY s.started_at",
                {"since": since},
            )
        else:
            sessions = db.query(
                "MATCH (s:Session) RETURN s.session_id AS sid ORDER BY s.started_at"
            )

        total_edges = 0
        for s in sessions:
            n = build_coactivations_for_session(s["sid"], db)
            total_edges += n

        # Auto-detect skills from recurring patterns
        from .skill_detector import crystallize_skills
        skills_detected = crystallize_skills(db)

        totals = db.query("MATCH ()-[c:COACTIVATED]-() RETURN count(c) AS total")
        total_in_db = totals[0]["total"] if totals else 0

        return {
            "sessions": len(sessions),
            "edges": total_edges,
            "total": total_in_db,
            "skills_indexed": skills_indexed,
            "concepts_extracted": concepts_extracted,
            "skills_auto_detected": skills_detected,
            "entities_merged": entities_merged,
        }
    finally:
        db.close()
