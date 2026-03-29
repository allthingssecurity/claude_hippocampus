#!/usr/bin/env python3
"""CA3 activation hook — fires on UserPromptSubmit.

Reads hook JSON from stdin, runs spreading activation on the user's prompt,
returns a context packet as a suppressed userMessage.

Must complete within 5s (hook timeout). Reserves 1.5s for overhead.
"""

import sys
import json
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    try:
        d = json.load(sys.stdin)
    except Exception:
        print(json.dumps({"continue": True}))
        return

    if d.get("hook_event_name") != "UserPromptSubmit":
        print(json.dumps({"continue": True}))
        return

    user_prompt = (d.get("user_prompt") or "")[:500]
    cwd = d.get("cwd") or ""

    # Skip very short prompts or slash commands
    if not user_prompt or len(user_prompt.strip()) < 5 or user_prompt.strip().startswith("/"):
        print(json.dumps({"continue": True}))
        return

    try:
        from ca3.activation import activate
        from ca3.context_packet import compress_to_packet

        result = activate(user_prompt, workspace=cwd, timeout_ms=3000)
        if result.nodes:
            packet = compress_to_packet(result, max_tokens=1500)
            if packet and len(packet) > 20:
                print(json.dumps({
                    "continue": True,
                    "suppressOutput": True,
                    "userMessage": packet,
                }))
                return
    except Exception:
        # Fail silently — never block the user's prompt
        pass

    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
