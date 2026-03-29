#!/usr/bin/env python3
"""
Thin MCP server that bridges Claude Code <-> Graphiti REST API.

Runs via stdio (Claude Code spawns it). Proxies tool calls to
the Graphiti REST API at GRAPHITI_URL (default http://localhost:8100).

Install deps:  pip install mcp httpx
Run:            python mcp_bridge.py
"""

import json
import os
from datetime import datetime, timezone

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

GRAPHITI_URL = os.environ.get("GRAPHITI_URL", "http://localhost:8100")
GROUP_ID = os.environ.get("GRAPHITI_GROUP_ID", "claude-traces")

server = Server("graphiti-bridge")
client = httpx.Client(base_url=GRAPHITI_URL, timeout=60.0)


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="add_episode",
            description="Record a decision, discovery, bugfix, or session summary to the knowledge graph. Graphiti auto-extracts entities and facts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short title (e.g. 'Chose SQLite for sessions', 'Fixed JWT race condition')",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full description: what happened, why, what was learned",
                    },
                    "source_description": {
                        "type": "string",
                        "description": "Category: decision, bugfix, discovery, pattern, session-summary",
                        "default": "decision",
                    },
                },
                "required": ["name", "content"],
            },
        ),
        Tool(
            name="search_facts",
            description="Search for relevant facts and learnings from past sessions. Returns entity relationships extracted by Graphiti.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for (e.g. 'authentication approach', 'database choices')",
                    },
                    "max_facts": {
                        "type": "integer",
                        "description": "Max results to return",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="recall_memory",
            description="Retrieve relevant memory (facts + context) for a given question or topic. Uses Graphiti's semantic retrieval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Question or topic to recall (e.g. 'What do we know about the auth module?')",
                    },
                    "max_facts": {
                        "type": "integer",
                        "description": "Max facts to retrieve",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_episodes",
            description="Get recent episodes (raw decision traces) from the knowledge graph.",
            inputSchema={
                "type": "object",
                "properties": {
                    "last_n": {
                        "type": "integer",
                        "description": "Number of recent episodes to fetch",
                        "default": 20,
                    },
                },
            },
        ),
        Tool(
            name="get_status",
            description="Check the health of the Graphiti server and Neo4j connection.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    try:
        if name == "add_episode":
            now = datetime.now(timezone.utc).isoformat()
            source_desc = arguments.get("source_description", "decision")
            resp = client.post(
                "/messages",
                json={
                    "group_id": GROUP_ID,
                    "messages": [
                        {
                            "content": f"[{source_desc}] {arguments['name']}: {arguments['content']}",
                            "role_type": "user",
                            "role": "claude-code",
                            "name": arguments["name"],
                            "source_description": source_desc,
                            "timestamp": now,
                        }
                    ],
                },
            )
            resp.raise_for_status()
            return [TextContent(type="text", text=f"Episode recorded: {arguments['name']}")]

        elif name == "search_facts":
            resp = client.post(
                "/search",
                json={
                    "group_ids": [GROUP_ID],
                    "query": arguments["query"],
                    "max_facts": arguments.get("max_facts", 10),
                },
            )
            resp.raise_for_status()
            results = resp.json()
            if not results:
                return [TextContent(type="text", text="No facts found.")]
            formatted = json.dumps(results, indent=2, default=str)
            return [TextContent(type="text", text=formatted)]

        elif name == "recall_memory":
            now = datetime.now(timezone.utc).isoformat()
            resp = client.post(
                "/get-memory",
                json={
                    "group_id": GROUP_ID,
                    "center_node_uuid": None,
                    "max_facts": arguments.get("max_facts", 10),
                    "messages": [
                        {
                            "content": arguments["query"],
                            "role_type": "user",
                            "role": "claude-code",
                            "timestamp": now,
                        }
                    ],
                },
            )
            resp.raise_for_status()
            results = resp.json()
            if not results:
                return [TextContent(type="text", text="No memory found.")]
            formatted = json.dumps(results, indent=2, default=str)
            return [TextContent(type="text", text=formatted)]

        elif name == "get_episodes":
            last_n = arguments.get("last_n", 20)
            resp = client.get(f"/episodes/{GROUP_ID}", params={"last_n": last_n})
            resp.raise_for_status()
            results = resp.json()
            if not results:
                return [TextContent(type="text", text="No episodes found.")]
            formatted = json.dumps(results, indent=2, default=str)
            return [TextContent(type="text", text=formatted)]

        elif name == "get_status":
            resp = client.get("/healthcheck")
            resp.raise_for_status()
            return [TextContent(type="text", text=json.dumps(resp.json()))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except httpx.HTTPStatusError as e:
        return [TextContent(type="text", text=f"API error {e.response.status_code}: {e.response.text}")]
    except httpx.ConnectError:
        return [TextContent(type="text", text=f"Cannot connect to Graphiti at {GRAPHITI_URL}. Is docker compose up?")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
