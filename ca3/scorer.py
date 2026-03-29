"""Multi-signal ranking for activated nodes."""

import math
import os
from datetime import datetime, timezone
from .config import RECENCY_LAMBDA


def rank_activation(
    base_activation: float,
    entity_name: str,
    workspace: str,
    coactivation_contexts: list[str] | None = None,
    last_ts_str: str | None = None,
    cooccurrence_count: int = 1,
) -> float:
    """Compute final activation score blending multiple signals.

    final = base_activation * recency_factor * workspace_factor

    recency_factor: exp(-lambda * days_since_last_coactivation)
    workspace_factor:
      - 2.0 if entity name matches current project
      - 1.5 if project appears in coactivation contexts
      - 1.0 otherwise
    """
    # Recency
    recency = 1.0
    if last_ts_str:
        try:
            last = datetime.fromisoformat(last_ts_str.replace("Z", "+00:00"))
            days = (datetime.now(timezone.utc) - last).total_seconds() / 86400
            recency = math.exp(-RECENCY_LAMBDA * max(0, days))
        except (ValueError, TypeError):
            recency = 0.5

    # Workspace match
    workspace_factor = 1.0
    project = os.path.basename(workspace) if workspace else ""
    if project and entity_name:
        if project.lower() in entity_name.lower() or entity_name.lower() in project.lower():
            workspace_factor = 2.0
        elif coactivation_contexts and any(
            project.lower() == ctx.lower() for ctx in coactivation_contexts
        ):
            workspace_factor = 1.5

    return base_activation * recency * workspace_factor
