"""Generic local filesystem storage primitives."""

import os
from pathlib import Path


def atomic_replace(source: Path, destination: Path) -> None:
    """Atomically move ``source`` onto ``destination`` on one filesystem."""

    os.replace(source, destination)


def resolve_within_root(candidate: Path, root: Path) -> Path | None:
    """Resolve a path only when it remains inside an already-resolved root."""

    resolved = candidate.resolve()
    return resolved if resolved.is_relative_to(root) else None


__all__ = ["atomic_replace", "resolve_within_root"]
