"""
Path reconstruction for Cursor's encoded project folder names.

Cursor encodes workspace paths by replacing '/' (or '\\' on Windows) and '.'
with '-' in the project folder name. For example:
    /Users/jane.doe/projects/my-api  → Users-jane-doe-projects-my-api
    C:\\Users\\jane\\projects\\my-api  → c-Users-jane-projects-my-api

The challenge: '-' can also appear as a literal character in real directory
names (e.g., "my-api"), so we can't simply replace all dashes. Instead, we
use DFS to try all three possible interpretations at each dash boundary
(literal dash, dot, or path separator) and validate against the filesystem.

On Windows (Git Bash / MSYS2), folder names start with a lowercase drive
letter (e.g., "c-Users-..."). We detect this and prepend the drive prefix.
"""

import os
import sys
from functools import lru_cache

_IS_WINDOWS = sys.platform == "win32" or os.name == "nt"
_SEP = os.sep


@lru_cache(maxsize=256)
def _path_exists(path):
    """Cached os.path.exists to avoid redundant syscalls during DFS."""
    return os.path.exists(path)


def _detect_drive_prefix(parts):
    """Check if the first part is a single-letter Windows drive (e.g., 'c').

    Returns (drive_prefix, start_index) — e.g., ("C:/", 1) or ("", 0).
    """
    if len(parts) >= 2 and len(parts[0]) == 1 and parts[0].isalpha():
        drive = parts[0].upper() + ":/"
        if _IS_WINDOWS or _path_exists(drive) or _path_exists("/" + parts[0]):
            return drive, 1
    return "", 0


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

    drive_prefix, start_idx = _detect_drive_prefix(parts)

    if drive_prefix:
        if start_idx >= n:
            return drive_prefix

        def solve(idx, segment, prefix):
            if idx == n:
                return prefix + segment
            part = parts[idx]
            r_dash = solve(idx + 1, segment + "-" + part, prefix)
            r_dot = solve(idx + 1, segment + "." + part, prefix)
            candidate = prefix + segment
            r_slash = None
            if _path_exists(candidate):
                r_slash = solve(idx + 1, part, candidate + "/")
            for r in [r_slash, r_dot, r_dash]:
                if r and _path_exists(r):
                    return r
            return r_slash or r_dot or r_dash

        return solve(start_idx + 1, parts[start_idx], drive_prefix)

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
