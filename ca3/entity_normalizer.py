"""Entity name normalization and deduplication.

Ensures conceptually identical entities (e.g., "mario-game", "mario game",
"Mario Game") are merged into a single canonical node. Runs as part of
the co-activation build pipeline.
"""

import re
from .neo4j_client import Neo4jClient
from .config import GROUP_ID, ENTITY_NAME_MAX_LEN


def _normalize(name: str) -> str:
    """Normalize entity name: lowercase, collapse hyphens/underscores to spaces, strip."""
    n = name.lower().strip()
    n = re.sub(r"[-_]+", " ", n)
    n = re.sub(r"\s+", " ", n)
    return n


def merge_duplicate_entities(db: Neo4jClient) -> int:
    """Find entities with equivalent normalized names and merge them.

    Keeps the entity with the longest/richest summary. Transfers all
    COACTIVATED and MENTIONS edges to the kept entity. Deletes the duplicate.

    Returns number of duplicates merged.
    """
    # Find all entities grouped by normalized name
    entities = db.query(
        """
        MATCH (e:Entity)
        WHERE e.group_id = $gid
          AND size(e.name) <= $max_len
        RETURN e.uuid AS uuid, e.name AS name,
               COALESCE(e.summary, '') AS summary,
               COALESCE(e.entity_type, '') AS etype
        ORDER BY e.name
        """,
        {"gid": GROUP_ID, "max_len": ENTITY_NAME_MAX_LEN},
    )

    # Group by normalized name
    groups: dict[str, list[dict]] = {}
    for e in entities:
        norm = _normalize(e["name"])
        if norm not in groups:
            groups[norm] = []
        groups[norm].append(e)

    merged = 0
    for norm_name, group in groups.items():
        if len(group) < 2:
            continue

        # Pick the "best" entity to keep:
        # Prefer: skill/auto-skill > entity with summary > first created
        def score(e):
            s = 0
            if e["etype"] in ("skill", "auto-skill"):
                s += 1000
            s += len(e["summary"])
            return s

        group.sort(key=score, reverse=True)
        keep = group[0]
        duplicates = group[1:]

        for dup in duplicates:
            # Transfer COACTIVATED edges from duplicate to kept entity
            db.execute(
                """
                MATCH (dup:Entity {uuid: $dup_uuid})-[c:COACTIVATED]-(other:Entity)
                WHERE other.uuid <> $keep_uuid
                WITH dup, c, other
                MERGE (keep:Entity {uuid: $keep_uuid})-[new_c:COACTIVATED]-(other)
                ON CREATE SET
                  new_c.count = c.count,
                  new_c.weight = c.weight,
                  new_c.last_ts = c.last_ts,
                  new_c.last_session = c.last_session,
                  new_c.contexts = c.contexts
                ON MATCH SET
                  new_c.count = new_c.count + c.count,
                  new_c.weight = CASE WHEN c.weight > new_c.weight THEN c.weight ELSE new_c.weight END
                DELETE c
                """,
                {"dup_uuid": dup["uuid"], "keep_uuid": keep["uuid"]},
            )

            # Transfer MENTIONS edges
            db.execute(
                """
                MATCH (ep:Episodic)-[m:MENTIONS]->(dup:Entity {uuid: $dup_uuid})
                MERGE (ep)-[:MENTIONS]->(keep:Entity {uuid: $keep_uuid})
                DELETE m
                """,
                {"dup_uuid": dup["uuid"], "keep_uuid": keep["uuid"]},
            )

            # Delete the duplicate
            db.execute(
                "MATCH (e:Entity {uuid: $uuid}) DETACH DELETE e",
                {"uuid": dup["uuid"]},
            )
            merged += 1

    return merged
