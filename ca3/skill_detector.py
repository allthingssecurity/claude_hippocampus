"""Automatic skill detection from session patterns.

Finds recurring project workflows and crystallizes them into
auto-skill Entity nodes. Runs as part of the co-activation build pipeline.

Detection logic:
1. Group sessions by project
2. For projects with 2+ sessions, extract the dominant tool + concept patterns
3. Match against known tech archetypes (WASM app, Docker setup, etc.)
4. Also detect novel patterns from concept co-occurrence within a project
5. Store as Entity nodes with entity_type='auto-skill'
"""

from .neo4j_client import Neo4jClient
from .config import GROUP_ID, ENTITY_NAME_MAX_LEN


# Generic names to exclude from skill trigger concepts
GENERIC_NAMES = frozenset({
    "Bash", "Read", "Write", "Grep", "Glob", "Edit", "Agent",
    "TaskCreate", "TaskUpdate", "TaskList", "TaskOutput", "TaskStop",
    "WebFetch", "WebSearch", "EnterPlanMode", "ExitPlanMode",
    "AskUserQuestion", "agent", "claude-hook(user)", "Session",
    "Trace", "this project", "README", "Build Lead",
})

# Tech archetype matchers: keyword → (skill_name, description_template)
ARCHETYPES = {
    "wasm": ("/wasm-app", "Scaffold and build a Rust→WASM→Browser application using wasm-pack"),
    "webassembly": ("/wasm-app", "Scaffold and build a Rust→WASM→Browser application using wasm-pack"),
    "wasm-pack": ("/wasm-app", "Scaffold and build a Rust→WASM→Browser application using wasm-pack"),
    "docker": ("/docker-setup", "Set up Docker/docker-compose for a project"),
    "docker-compose": ("/docker-setup", "Set up Docker/docker-compose for a project"),
    "quantum": ("/quantum-sim", "Build quantum circuit simulations and visualizations"),
    "qubit": ("/quantum-sim", "Build quantum circuit simulations and visualizations"),
    "neo4j": ("/graph-db", "Set up and query Neo4j graph databases"),
    "cypher": ("/graph-db", "Set up and query Neo4j graph databases"),
    "fastapi": ("/fastapi-app", "Scaffold a FastAPI application"),
    "flask": ("/flask-app", "Scaffold a Flask application"),
    "react": ("/react-app", "Scaffold a React application"),
    "three.js": ("/3d-viz", "Build 3D visualizations with Three.js"),
    "webgl": ("/3d-viz", "Build 3D visualizations"),
    "pipecat": ("/voice-agent", "Build voice agent pipelines with Pipecat"),
    "websocket": ("/websocket-app", "Build WebSocket-based real-time applications"),
    "svg": ("/svg-viz", "Build SVG-based data visualizations"),
    "canvas": ("/canvas-app", "Build canvas-based interactive applications"),
    "mario": ("/browser-game", "Build browser-based games"),
    "game": ("/browser-game", "Build browser-based games"),
    "course": ("/course-builder", "Build interactive educational courses"),
    "tutorial": ("/course-builder", "Build interactive educational content"),
    "reinforcement": ("/rl-training", "Set up reinforcement learning training pipelines"),
    "grpo": ("/rl-training", "Set up RL training with GRPO"),
    "training": ("/ml-training", "Set up machine learning training pipelines"),
}


def detect_skills(db: Neo4jClient) -> list[dict]:
    """Detect recurring patterns and return skill candidates."""
    detected = []
    seen_skill_names = set()

    # Get all projects with 2+ sessions
    projects = db.query(
        """
        MATCH (s:Session)
        WHERE s.project <> 'unknown' AND s.project <> ''
        WITH s.project AS project, count(s) AS session_count,
             collect(s.session_id) AS session_ids
        WHERE session_count >= 2
        RETURN project, session_count, session_ids
        ORDER BY session_count DESC
        LIMIT 30
        """,
    )

    for proj in projects:
        project = proj["project"]
        session_ids = proj["session_ids"]

        # Get domain concepts for this project (from extracted concepts)
        concepts = db.query(
            """
            MATCH (e:Entity)
            WHERE e.group_id = $gid
              AND e.entity_type = 'concept'
              AND size(e.name) <= $max_len
              AND NOT e.name STARTS WITH '/'
              AND NOT e.name STARTS WITH 'http'
              AND ANY(sid IN $sids WHERE e.summary CONTAINS substring(sid, 0, 12))
            RETURN DISTINCT e.name AS name
            LIMIT 30
            """,
            {"gid": GROUP_ID, "max_len": ENTITY_NAME_MAX_LEN, "sids": session_ids[:5]},
        )

        # Also get Graphiti entities mentioned in this project's episodes
        graphiti_entities = db.query(
            """
            MATCH (t:Trace)-[:BELONGS_TO]->(s:Session)
            WHERE s.project = $project
            WITH collect(DISTINCT s.session_id) AS sids
            UNWIND sids AS sid
            MATCH (ep:Episodic)-[:MENTIONS]->(e:Entity)
            WHERE ep.group_id = $gid
              AND ep.content CONTAINS sid
              AND size(e.name) <= $max_len
              AND NOT e.name STARTS WITH '/'
              AND NOT e.name STARTS WITH 'http'
            RETURN DISTINCT e.name AS name
            LIMIT 30
            """,
            {"gid": GROUP_ID, "project": project, "max_len": ENTITY_NAME_MAX_LEN},
        )

        all_concept_names = set()
        for c in concepts + graphiti_entities:
            name = c["name"]
            if name not in GENERIC_NAMES and len(name) > 3:
                all_concept_names.add(name)

        if not all_concept_names:
            continue

        # Match against archetypes
        for concept in all_concept_names:
            concept_lower = concept.lower()
            for keyword, (skill_name, desc_template) in ARCHETYPES.items():
                if keyword in concept_lower and skill_name not in seen_skill_names:
                    # Found a match — build the skill
                    triggers = [c for c in all_concept_names
                                if c not in GENERIC_NAMES][:10]
                    tools = _get_project_tools(db, project)

                    detected.append({
                        "name": skill_name,
                        "summary": (
                            f"{desc_template}. "
                            f"Based on {proj['session_count']} sessions in '{project}'. "
                            f"Key concepts: {', '.join(triggers[:5])}."
                        ),
                        "project": project,
                        "trigger_concepts": triggers,
                        "tool_pattern": tools,
                        "session_count": proj["session_count"],
                    })
                    seen_skill_names.add(skill_name)
                    break  # One skill per archetype per project

    # === PASS 2: Cross-project skill detection ===
    # Find concepts that appear in traces across 2+ different projects
    cross_project = db.query(
        """
        MATCH (t:Trace)-[:BELONGS_TO]->(s:Session)
        WHERE t.input_summary IS NOT NULL AND t.input_summary <> ''
          AND s.project <> 'unknown' AND s.project <> ''
        WITH s.project AS project, collect(t.input_summary) AS inputs
        WITH project, reduce(all_text = '', inp IN inputs | all_text + ' ' + inp) AS combined
        RETURN project, combined
        """,
    )

    # Extract tech keywords from each project's traces and find cross-project patterns
    from .config import STOPWORDS
    import re
    project_keywords: dict[str, set[str]] = {}
    for row in cross_project:
        proj_name = row["project"]
        text = row["combined"].lower()
        # Match against archetypes
        found = set()
        for keyword in ARCHETYPES:
            if keyword in text:
                found.add(keyword)
        if found:
            project_keywords[proj_name] = found

    # Find keywords appearing in 2+ projects
    keyword_projects: dict[str, list[str]] = {}
    for proj_name, keywords in project_keywords.items():
        for kw in keywords:
            if kw not in keyword_projects:
                keyword_projects[kw] = []
            keyword_projects[kw].append(proj_name)

    for keyword, projects_list in keyword_projects.items():
        if len(projects_list) < 2:
            continue
        skill_name, desc_template = ARCHETYPES[keyword]
        if skill_name in seen_skill_names:
            continue

        # Collect trigger concepts from all involved projects
        all_triggers = set()
        for proj_name in projects_list:
            concepts = db.query(
                """
                MATCH (e:Entity {entity_type: 'concept', group_id: $gid})
                WHERE size(e.name) <= $max_len
                  AND NOT e.name STARTS WITH '/'
                  AND NOT e.name STARTS WITH 'http'
                RETURN e.name AS name
                LIMIT 20
                """,
                {"gid": GROUP_ID, "max_len": ENTITY_NAME_MAX_LEN},
            )
            for c in concepts:
                if c["name"] not in GENERIC_NAMES and len(c["name"]) > 3:
                    all_triggers.add(c["name"])

        triggers = list(all_triggers)[:10]
        detected.append({
            "name": skill_name,
            "summary": (
                f"{desc_template}. "
                f"Detected across {len(projects_list)} projects: {', '.join(projects_list[:5])}. "
                f"Key concepts: {', '.join(triggers[:5])}."
            ),
            "project": projects_list[0],
            "trigger_concepts": triggers,
            "tool_pattern": [],
            "session_count": len(projects_list),
        })
        seen_skill_names.add(skill_name)

    return detected


def _get_project_tools(db: Neo4jClient, project: str) -> list[str]:
    """Get the specific (non-generic) tools used in a project."""
    rows = db.query(
        """
        MATCH (t:Trace)-[:BELONGS_TO]->(s:Session {project: $project})
        WHERE t.tool_name <> ''
        RETURN t.tool_name AS tool, count(*) AS uses
        ORDER BY uses DESC
        LIMIT 10
        """,
        {"project": project},
    )
    generic = {"Bash", "Read", "Write", "Grep", "Glob", "Edit", "Agent",
               "TaskCreate", "TaskUpdate", "TaskList"}
    return [r["tool"] for r in rows if r["tool"] not in generic][:5]


def crystallize_skills(db: Neo4jClient) -> int:
    """Detect skills and write them to the graph."""
    candidates = detect_skills(db)
    created = 0

    for skill in candidates:
        # Upsert auto-skill entity
        db.query(
            """
            MERGE (e:Entity {group_id: $gid, name: $name})
            ON CREATE SET
              e.uuid = randomUUID(),
              e.summary = $summary,
              e.entity_type = 'auto-skill',
              e.trigger_concepts = $triggers,
              e.tool_pattern = $tools,
              e.source_project = $project,
              e.session_count = $session_count,
              e.created_at = toString(datetime())
            ON MATCH SET
              e.summary = $summary,
              e.entity_type = 'auto-skill',
              e.trigger_concepts = $triggers,
              e.tool_pattern = $tools,
              e.session_count = $session_count,
              e.updated_at = toString(datetime())
            RETURN e.uuid AS uuid
            """,
            {
                "gid": GROUP_ID,
                "name": skill["name"],
                "summary": skill["summary"],
                "triggers": skill["trigger_concepts"],
                "tools": skill["tool_pattern"],
                "project": skill["project"],
                "session_count": skill["session_count"],
            },
        )

        # Link skill to its trigger concepts
        for concept in skill["trigger_concepts"]:
            db.query(
                """
                MATCH (skill:Entity {group_id: $gid, name: $skill_name})
                MATCH (concept:Entity {group_id: $gid, name: $concept_name})
                WHERE concept.uuid <> skill.uuid
                MERGE (skill)-[c:COACTIVATED]-(concept)
                ON CREATE SET c.count = 3, c.weight = 3.0,
                              c.last_ts = toString(datetime()),
                              c.last_session = 'skill-detector',
                              c.contexts = [$project]
                RETURN count(*) AS n
                """,
                {
                    "gid": GROUP_ID,
                    "skill_name": skill["name"],
                    "concept_name": concept,
                    "project": skill["project"],
                },
            )

        created += 1

    return created
