"""ID utilities."""

from __future__ import annotations

import itertools


def evidence_id_generator(prefix: str = "id_") -> itertools.count:
    """Return a counter for evidence ids.

    Args:
        prefix: ID prefix.

    Returns:
        A counter that yields consecutive numbers starting from 1.
    """

    return itertools.count(1)


def format_evidence_id(n: int, prefix: str = "ev_") -> str:
    """Format a numeric counter to evidence id.
    
    Uses ev_ prefix with zero-padded numbers (e.g., ev_0001) to match
    the format expected in prompts and citations.
    """

    return f"{prefix}{n:04d}"
