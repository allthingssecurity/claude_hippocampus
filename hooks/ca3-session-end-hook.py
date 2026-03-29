#!/usr/bin/env python3
"""CA3 session-end hook — fires on Stop event.

After a session ends:
1. Extract concepts from traces (no LLM needed)
2. Build co-activation edges for this session
3. Detect and crystallize new skills from recurring patterns

Runs in background — returns immediately, does work async.
"""

import sys
import json
import os
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    try:
        d = json.load(sys.stdin)
    except Exception:
        print(json.dumps({"continue": True}))
        return

    if d.get("hook_event_name") != "Stop":
        print(json.dumps({"continue": True}))
        return

    session_id = d.get("session_id", "")

    # Return immediately, do work in background
    print(json.dumps({"continue": True}))
    sys.stdout.flush()

    if not session_id:
        return

    try:
        from ca3.neo4j_client import Neo4jClient
        from ca3.coactivation import (
            extract_concepts_from_traces,
            build_coactivations_for_session,
        )
        from ca3.skill_detector import crystallize_skills

        db = Neo4jClient()
        try:
            # 1. Extract concepts from this session's traces
            concepts = extract_concepts_from_traces(session_id, db)

            # 2. Build co-activation edges for this session
            edges = build_coactivations_for_session(session_id, db)

            # 3. Detect new skills from accumulated patterns
            skills = crystallize_skills(db)

            # Log to temp file for debugging
            log_path = f"/tmp/ca3-session-end-{session_id[:8]}.log"
            with open(log_path, "w") as f:
                f.write(f"session: {session_id}\n")
                f.write(f"concepts_extracted: {concepts}\n")
                f.write(f"edges_created: {edges}\n")
                f.write(f"skills_detected: {skills}\n")
        finally:
            db.close()
    except Exception as e:
        # Never crash — just log
        try:
            with open(f"/tmp/ca3-error-{session_id[:8]}.log", "w") as f:
                f.write(f"Error: {e}\n")
        except Exception:
            pass


if __name__ == "__main__":
    main()
