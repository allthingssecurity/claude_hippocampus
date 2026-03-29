"""Compress activated subgraph into a concise context packet for LLM injection."""

from .activation import ActivationResult
from .config import CONTEXT_PACKET_MAX_TOKENS, TOKEN_ESTIMATE_DIVISOR


def _estimate_tokens(text: str) -> int:
    return len(text) // TOKEN_ESTIMATE_DIVISOR


def _truncate(text: str, max_chars: int = 120) -> str:
    if len(text) <= max_chars:
        return text
    # Try to cut at sentence boundary
    cut = text[:max_chars]
    last_period = cut.rfind(". ")
    if last_period > max_chars // 2:
        return cut[: last_period + 1]
    return cut[:max_chars - 3] + "..."


def compress_to_packet(
    result: ActivationResult,
    max_tokens: int = CONTEXT_PACKET_MAX_TOKENS,
) -> str:
    """Convert an ActivationResult into a compact context packet.

    Groups:
    - Skills (entity_type == "skill") → "Suggested skills"
    - High activation (>0.7) → "Related concepts"
    - Medium (0.3-0.7) → "Associated patterns"
    - Low (<0.3) → "Also relevant" (names only)
    """
    if not result.nodes:
        return ""

    lines = []
    lines.append(
        f"[Associative recall — {len(result.nodes)} concepts, "
        f"{result.elapsed_ms:.0f}ms]"
    )
    lines.append("")

    skills = [n for n in result.nodes if n.node_type in ("skill", "auto-skill")]
    entities = [n for n in result.nodes if n.node_type not in ("skill", "auto-skill")]
    high = [n for n in entities if n.activation > 0.7]
    medium = [n for n in entities if 0.3 < n.activation <= 0.7]
    low = [n for n in entities if n.activation <= 0.3]

    budget = max_tokens
    current = _estimate_tokens("\n".join(lines))

    # Skills first — always useful, compact
    if skills:
        lines.append("Suggested skills:")
        for node in skills[:4]:
            summary = _truncate(node.summary, 80) if node.summary else ""
            line = f"- {node.name}: {summary}" if summary else f"- {node.name}"
            cost = _estimate_tokens(line)
            if current + cost > budget:
                break
            lines.append(line)
            current += cost
        lines.append("")

    # High-confidence concepts with summaries
    if high:
        lines.append("Related concepts:")
        for node in high[:6]:
            summary = _truncate(node.summary, 100) if node.summary else ""
            if summary:
                line = f"- {node.name}: {summary}"
            else:
                line = f"- {node.name}"
            cost = _estimate_tokens(line)
            if current + cost > budget:
                break
            lines.append(line)
            current += cost
        lines.append("")

    # Medium: associated patterns
    if medium and current < budget * 0.75:
        lines.append("Associated patterns:")
        for node in medium[:5]:
            summary = _truncate(node.summary, 80) if node.summary else ""
            if summary:
                line = f"- {node.name}: {summary}"
            else:
                line = f"- {node.name}"
            cost = _estimate_tokens(line)
            if current + cost > budget:
                break
            lines.append(line)
            current += cost
        lines.append("")

    # Low: just names if space remains
    if low and current < budget * 0.9:
        names = [n.name for n in low[:8]]
        tail = f"Also relevant: {', '.join(names)}"
        cost = _estimate_tokens(tail)
        if current + cost <= budget:
            lines.append(tail)

    return "\n".join(lines).strip()
