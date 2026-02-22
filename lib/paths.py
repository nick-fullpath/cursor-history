"""
Path reconstruction for Cursor's encoded project folder names.

Cursor encodes workspace paths by replacing '/' and '.' with '-' in the
project folder name. For example:
    /Users/jane.doe/projects/my-api → Users-jane-doe-projects-my-api

The challenge: '-' can also appear as a literal character in real directory
names (e.g., "my-api"), so we can't simply replace all dashes. Instead, we
use DFS to try all three possible interpretations at each dash boundary
(literal dash, dot, or path separator) and validate against the filesystem.
"""

import os
from functools import lru_cache


@lru_cache(maxsize=256)
def _path_exists(path):
    """Cached os.path.exists to avoid redundant syscalls during DFS."""
    return os.path.exists(path)


def folder_to_path(folder_name):
    """Reconstruct a real filesystem path from Cursor's encoded folder name.

    Uses a DFS algorithm that evaluates all possible separator assignments
    (/, ., -) at each dash boundary, preferring candidates that exist on
    the filesystem.

    Args:
        folder_name: The encoded folder name (e.g., "Users-jane-doe-my-api")

    Returns:
        The reconstructed filesystem path (e.g., "/Users/jane.doe/my-api"),
        or a best-effort guess if no exact match is found.
    """
    if folder_name.startswith("var-"):
        return "/" + folder_name.replace("-", "/")

    parts = folder_name.split("-")
    n = len(parts)
    if n == 1:
        return "/" + parts[0]

    def solve(idx, segment, prefix):
        """Recursively try -, ., / as the separator at each dash position."""
        if idx == n:
            return prefix + "/" + segment if prefix else "/" + segment

        part = parts[idx]
        r_dash = solve(idx + 1, segment + "-" + part, prefix)
        r_dot = solve(idx + 1, segment + "." + part, prefix)

        candidate = prefix + "/" + segment if prefix else "/" + segment
        r_slash = None
        if _path_exists(candidate):
            r_slash = solve(idx + 1, part, candidate)

        for r in [r_slash, r_dot, r_dash]:
            if r and _path_exists(r):
                return r
        return r_slash or r_dot or r_dash

    return solve(1, parts[0], "")
