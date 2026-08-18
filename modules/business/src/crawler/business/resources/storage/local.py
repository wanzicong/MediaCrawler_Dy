"""通用的本地文件系统存储原语。"""

import os
from pathlib import Path


def atomic_replace(source: Path, destination: Path) -> None:
    """在同一文件系统内将 ``source`` 原子地移动到 ``destination``。

    参数：
        source: 源文件路径。
        destination: 目标文件路径，已存在时会被覆盖。
    """

    os.replace(source, destination)


def resolve_within_root(candidate: Path, root: Path) -> Path | None:
    """仅当路径解析后仍位于已解析的根目录内时才返回该路径，否则返回 None。

    用于防止路径穿越（path traversal）逃逸出允许的根目录。

    参数：
        candidate: 待校验的候选路径。
        root: 已调用 resolve() 解析过的根目录。

    返回：
        解析后的安全路径；越出根目录时返回 None。
    """

    resolved = candidate.resolve()
    return resolved if resolved.is_relative_to(root) else None


__all__ = ["atomic_replace", "resolve_within_root"]
