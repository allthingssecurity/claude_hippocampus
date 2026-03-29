"""Spreading activation engine.

Given a cue (text + workspace), seeds from Entity nodes matching keywords,
then spreads activation through COACTIVATED edges and returns ranked results.

Filters out noise: file paths, URLs, UUIDs, duplicates.
"""

import os
import re
import time
from dataclasses import dataclass, field
from .neo4j_client import Neo4jClient
from .scorer import rank_activation
from .config import (
    MAX_SEEDS,
    MAX_SPREAD_HOPS,
    SPREAD_DECAY,
    ACTIVATION_THRESHOLD,
    MIN_COACTIVATION_WEIGHT,
    MAX_NEIGHBORS_PER_HOP,
    MAX_ACTIVATED,
    STOPWORDS,
    GROUP_ID,
    ENTITY_NAME_MAX_LEN,
    ENTITY_NAME_SKIP_PREFIXES,
)


@dataclass
class ActivatedNode:
    uuid: str
    name: str
    summary: str
    activation: float
    source: str  # "seed", "spread-1", "spread-2"
    node_type: str = "entity"


@dataclass
class ActivationResult:
    nodes: list[ActivatedNode] = field(default_factory=list)
    edges_traversed: int = 0
    seed_query: str = ""
    elapsed_ms: float = 0.0
    debug_trace: list[str] = field(default_factory=list)


def _is_noise_entity(name: str) -> bool:
    """Filter out entities that are file paths, URLs, UUIDs, or too long."""
    if not name or len(name) > ENTITY_NAME_MAX_LEN:
        return True
    for prefix in ENTITY_NAME_SKIP_PREFIXES:
        if name.startswith(prefix):
            return True
    # Skip UUIDs (8-4-4-4-12 hex pattern)
    if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-", name):
        return True
    # Skip pure file extensions like *.Dockerfile*
    if name.startswith("*") and name.endswith("*"):
        return True
    return False


def extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from a cue string.

    Requires length > 3 for specificity. Sorts longer (more specific) first.
    Also extracts multi-word bigrams for compound concept matching.
    """
    tokens = re.findall(r"[a-zA-Z0-9_\-]+", text.lower())
    # Single keywords: length > 3
    singles = [t for t in tokens if t not in STOPWORDS and len(t) > 3]

    # Bigrams: adjacent meaningful tokens joined by space
    meaningful = [t for t in tokens if t not in STOPWORDS and len(t) > 2]
    bigrams = [f"{meaningful[i]} {meaningful[i+1]}" for i in range(len(meaningful) - 1)]

    # Ensure singles always get slots (they match entity names better).
    # Take top 7 singles + top 5 bigrams, deduplicate.
    seen = set()
    result = []
    top_singles = sorted(singles, key=len, reverse=True)[:7]
    top_bigrams = bigrams[:5]
    for k in top_singles + top_bigrams:
        if k not in seen:
            seen.add(k)
            result.append(k)
    return result[:12]


def activate(
    cue: str,
    workspace: str = "",
    max_seeds: int = MAX_SEEDS,
    max_hops: int = MAX_SPREAD_HOPS,
    activation_threshold: float = ACTIVATION_THRESHOLD,
    max_activated: int = MAX_ACTIVATED,
    timeout_ms: int = 3000,
) -> ActivationResult:
    """Run spreading activation from a cue string.

    Seed → Spread (multi-hop) → Rank → Deduplicate → Return.
    Filters out file paths, URLs, and duplicate entity names.
    """
    start = time.monotonic()
    result = ActivationResult(seed_query=cue)
    db = Neo4jClient()

    try:
        # === SEED PHASE ===
        keywords = extract_keywords(cue)
        if not keywords:
            result.debug_trace.append("No keywords extracted from cue")
            return result

        result.debug_trace.append(f"Keywords: {keywords}")

        # Separate bigrams and singles for different matching strategies
        bigram_kw = [k for k in keywords if " " in k]
        single_kw = [k for k in keywords if " " not in k]

        # Seed from Entity nodes using CONTAINS on filtered names.
        # Noise is controlled by: filtering paths/URLs/long names, preferring
        # entities with COACTIVATED edges, and deduplicating by normalized name.
        all_kw = single_kw + bigram_kw
        seed_rows = db.query(
            """
            MATCH (e:Entity)
            WHERE e.group_id = $group_id
              AND size(e.name) <= $max_name_len
              AND NOT (e.name STARTS WITH '/Users/' OR e.name STARTS WITH '/tmp/'
                    OR e.name STARTS WITH '/private/' OR e.name STARTS WITH '/var/'
                    OR e.name STARTS WITH 'http://' OR e.name STARTS WITH 'https://'
                    OR e.name STARTS WITH '/workspace/' OR e.name STARTS WITH '*')
              AND ANY(kw IN $keywords WHERE toLower(e.name) CONTAINS kw)
            OPTIONAL MATCH (e)-[c:COACTIVATED]-()
            WITH e, count(c) AS edge_count
            RETURN e.uuid AS uuid, e.name AS name,
                   COALESCE(e.summary, '') AS summary,
                   COALESCE(e.entity_type, 'entity') AS entity_type,
                   edge_count
            ORDER BY edge_count DESC, size(e.name) ASC
            LIMIT $max_seeds
            """,
            {
                "group_id": GROUP_ID,
                "keywords": all_kw,
                "max_name_len": ENTITY_NAME_MAX_LEN,
                "max_seeds": max_seeds * 3,  # Fetch extra, deduplicate in Python
            },
        )

        if not seed_rows:
            result.debug_trace.append("No seed entities found")
            result.elapsed_ms = (time.monotonic() - start) * 1000
            return result

        # Deduplicate seeds by normalized name (keep highest edge_count)
        activation_map: dict[str, float] = {}
        node_info: dict[str, dict] = {}
        node_source: dict[str, str] = {}
        seen_names: dict[str, str] = {}  # normalized_name → uuid

        for row in seed_rows:
            if _is_noise_entity(row["name"]):
                continue
            uid = row["uuid"]
            norm = row["name"].lower().strip()
            if norm in seen_names:
                continue
            seen_names[norm] = uid
            activation_map[uid] = 1.0
            node_info[uid] = row
            node_source[uid] = "seed"
            if len(activation_map) >= max_seeds:
                break

        if not activation_map:
            result.debug_trace.append("All seed candidates filtered as noise")
            result.elapsed_ms = (time.monotonic() - start) * 1000
            return result

        result.debug_trace.append(
            f"Seeds ({len(activation_map)}): {[node_info[uid]['name'] for uid in activation_map]}"
        )

        # === SPREAD PHASE (multi-hop) ===
        visited = set(activation_map.keys())
        project = os.path.basename(workspace) if workspace else ""

        for hop in range(1, max_hops + 1):
            elapsed = (time.monotonic() - start) * 1000
            if elapsed > timeout_ms * 0.6:
                result.debug_trace.append(f"Timeout at hop {hop}, {elapsed:.0f}ms")
                break

            frontier = [
                uid for uid, score in activation_map.items()
                if score >= activation_threshold
            ]
            if not frontier:
                break

            neighbors = db.query(
                """
                UNWIND $frontier AS fid
                MATCH (src:Entity {uuid: fid})-[c:COACTIVATED]-(neighbor:Entity)
                WHERE NOT neighbor.uuid IN $visited
                  AND c.weight > $min_weight
                  AND size(neighbor.name) <= $max_name_len
                  AND NOT (neighbor.name STARTS WITH '/Users/'
                        OR neighbor.name STARTS WITH '/tmp/'
                        OR neighbor.name STARTS WITH '/private/'
                        OR neighbor.name STARTS WITH 'http://'
                        OR neighbor.name STARTS WITH 'https://'
                        OR neighbor.name STARTS WITH '/workspace/')
                WITH neighbor, src, c,
                     CASE WHEN $project <> '' AND ANY(ctx IN c.contexts WHERE ctx = $project)
                          THEN 1.5 ELSE 1.0 END AS ctx_boost
                RETURN neighbor.uuid AS uuid, neighbor.name AS name,
                       COALESCE(neighbor.summary, '') AS summary,
                       COALESCE(neighbor.entity_type, 'entity') AS entity_type,
                       src.uuid AS from_uuid,
                       c.weight * ctx_boost AS effective_weight,
                       c.count AS cooccurrence_count,
                       c.last_ts AS last_ts,
                       c.contexts AS contexts,
                       CASE WHEN neighbor.entity_type IN ['skill', 'auto-skill']
                            THEN 1 ELSE 0 END AS is_skill
                ORDER BY is_skill DESC, effective_weight DESC
                LIMIT $max_neighbors
                """,
                {
                    "frontier": frontier,
                    "visited": list(visited),
                    "min_weight": MIN_COACTIVATION_WEIGHT,
                    "project": project,
                    "max_neighbors": MAX_NEIGHBORS_PER_HOP,
                    "max_name_len": ENTITY_NAME_MAX_LEN,
                },
            )

            result.edges_traversed += len(neighbors)
            max_weight = max((n["effective_weight"] for n in neighbors), default=1.0)

            for n in neighbors:
                uid = n["uuid"]
                norm = n["name"].lower().strip()

                # Skip noise and duplicates
                if _is_noise_entity(n["name"]):
                    continue
                if norm in seen_names and seen_names[norm] != uid:
                    continue
                seen_names[norm] = uid

                parent_activation = activation_map.get(n["from_uuid"], 0)
                norm_weight = n["effective_weight"] / max_weight if max_weight > 0 else 0.5
                spread_activation = parent_activation * SPREAD_DECAY * norm_weight

                ranked = rank_activation(
                    base_activation=spread_activation,
                    entity_name=n["name"],
                    workspace=workspace,
                    coactivation_contexts=n.get("contexts"),
                    last_ts_str=n.get("last_ts"),
                    cooccurrence_count=n.get("cooccurrence_count", 1),
                )

                if uid in activation_map:
                    activation_map[uid] = max(activation_map[uid], ranked)
                else:
                    activation_map[uid] = ranked
                    node_info[uid] = {
                        "uuid": uid, "name": n["name"], "summary": n["summary"],
                        "entity_type": n.get("entity_type", "entity"),
                    }
                    node_source[uid] = f"spread-{hop}"
                visited.add(uid)

            result.debug_trace.append(f"Hop {hop}: {len(neighbors)} neighbors reached")

        # === SKILL RETRIEVAL (dedicated pass) ===
        # Directly find any skill/auto-skill linked to activated entities.
        # Do NOT exclude skills already in activation_map (they may have
        # been found during spread with wrong entity_type).
        non_skill_uuids = [
            uid for uid in activation_map
            if node_info.get(uid, {}).get("entity_type") not in ("skill", "auto-skill")
        ]
        if non_skill_uuids:
            skill_rows = db.query(
                """
                UNWIND $uuids AS uid
                MATCH (src:Entity {uuid: uid})-[c:COACTIVATED]-(skill:Entity)
                WHERE skill.entity_type IN ['skill', 'auto-skill']
                  AND c.weight >= 1.0
                RETURN DISTINCT skill.uuid AS uuid, skill.name AS name,
                       COALESCE(skill.summary, '') AS summary,
                       skill.entity_type AS entity_type,
                       max(c.weight) AS weight
                ORDER BY weight DESC
                LIMIT 5
                """,
                {"uuids": non_skill_uuids},
            )
            for s in skill_rows:
                uid = s["uuid"]
                activation_map[uid] = max(activation_map.get(uid, 0), 0.8)
                if uid not in node_info:
                    node_info[uid] = s
                    node_source[uid] = "skill-retrieval"
                    seen_names[s["name"].lower().strip()] = uid
                else:
                    # Ensure entity_type is set correctly
                    node_info[uid]["entity_type"] = s["entity_type"]
            if skill_rows:
                result.debug_trace.append(
                    f"Skill retrieval: {[s['name'] for s in skill_rows]}"
                )

        # === COLLECT & RANK PHASE ===
        for uid in list(activation_map.keys()):
            if node_source.get(uid) == "seed":
                activation_map[uid] = rank_activation(
                    base_activation=activation_map[uid],
                    entity_name=node_info[uid]["name"],
                    workspace=workspace,
                )

        # Build deduplicated final list
        for uid, score in activation_map.items():
            if score >= activation_threshold and uid in node_info:
                info = node_info[uid]
                result.nodes.append(
                    ActivatedNode(
                        uuid=uid,
                        name=info["name"],
                        summary=info.get("summary", ""),
                        activation=round(score, 2),
                        source=node_source.get(uid, "unknown"),
                        node_type=info.get("entity_type", "entity"),
                    )
                )

        result.nodes.sort(key=lambda n: n.activation, reverse=True)
        result.nodes = result.nodes[:max_activated]
        result.elapsed_ms = (time.monotonic() - start) * 1000
        result.debug_trace.append(
            f"Final: {len(result.nodes)} nodes, {result.elapsed_ms:.0f}ms"
        )

    except Exception as e:
        result.debug_trace.append(f"Error: {e}")
    finally:
        db.close()

    return result
