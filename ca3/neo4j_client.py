"""Thin Neo4j HTTP client over the transactional Cypher endpoint."""

import httpx
from .config import NEO4J_URL, NEO4J_AUTH


class Neo4jClient:
    def __init__(self, url: str = NEO4J_URL, auth: str = NEO4J_AUTH):
        user, password = auth.split(":", 1)
        self.client = httpx.Client(
            base_url=url,
            auth=(user, password),
            timeout=5.0,
        )
        self.endpoint = "/db/neo4j/tx/commit"

    def query(self, cypher: str, params: dict | None = None) -> list[dict]:
        """Execute a Cypher query and return rows as list of dicts."""
        stmt = {"statement": cypher}
        if params:
            stmt["parameters"] = params
        resp = self.client.post(self.endpoint, json={"statements": [stmt]})
        resp.raise_for_status()
        data = resp.json()
        errors = data.get("errors", [])
        if errors:
            raise RuntimeError(f"Cypher error: {errors[0].get('message', errors)}")
        results = data.get("results", [{}])[0]
        cols = results.get("columns", [])
        rows = results.get("data", [])
        return [dict(zip(cols, row["row"])) for row in rows]

    def execute(self, cypher: str, params: dict | None = None) -> int:
        """Execute a Cypher statement, return number of rows affected."""
        stmt = {"statement": cypher}
        if params:
            stmt["parameters"] = params
        resp = self.client.post(self.endpoint, json={"statements": [stmt]})
        resp.raise_for_status()
        data = resp.json()
        errors = data.get("errors", [])
        if errors:
            raise RuntimeError(f"Cypher error: {errors[0].get('message', errors)}")
        results = data.get("results", [{}])[0]
        return len(results.get("data", []))

    def multi(self, statements: list[dict]) -> list[list[dict]]:
        """Execute multiple Cypher statements in a single transaction."""
        stmts = []
        for s in statements:
            stmt = {"statement": s["cypher"]}
            if "params" in s:
                stmt["parameters"] = s["params"]
            stmts.append(stmt)
        resp = self.client.post(self.endpoint, json={"statements": stmts})
        resp.raise_for_status()
        data = resp.json()
        errors = data.get("errors", [])
        if errors:
            raise RuntimeError(f"Cypher error: {errors[0].get('message', errors)}")
        all_results = []
        for result in data.get("results", []):
            cols = result.get("columns", [])
            rows = result.get("data", [])
            all_results.append([dict(zip(cols, row["row"])) for row in rows])
        return all_results

    def close(self):
        self.client.close()
