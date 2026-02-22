#!/usr/bin/env python3
"""
cursor-history session indexer — orchestration and CLI entrypoint.

Scans all Cursor Agent CLI transcript directories under the projects folder,
delegates parsing to the transcript/paths/models modules, and writes a JSON
index to the cache file.

Called from the cursor-history shell script:

    python3 lib/indexer.py <projects_dir> <cache_file>
    python3 lib/indexer.py --preview <transcript_path> [limit]

The resulting JSON array is sorted by modification time (newest first) and
written with 0600 permissions to prevent other users from reading it.
"""

import json
import os
import sys
from datetime import datetime

from models import load_model_map
from paths import folder_to_path
from transcript import get_ext, parse, preview


def build_index(projects_dir, cache_file):
    """Scan all project transcript directories and write the session index.

    Walks every subdirectory of projects_dir looking for agent-transcripts/
    folders. For each transcript file found, it:
      1. Reconstructs the original workspace path from the folder name
      2. Parses the transcript in a single pass (summary, counts, tokens)
      3. Looks up model attribution from Cursor's tracking DB

    The resulting JSON array is sorted newest-first and written to cache_file
    with restrictive permissions (umask 077 -> only owner can read/write).
    """
    if not os.path.isdir(projects_dir):
        print(f"Projects directory not found: {projects_dir}", file=sys.stderr)
        sys.exit(1)

    model_map = load_model_map()
    sessions = []

    for project_entry in sorted(os.listdir(projects_dir)):
        transcripts_dir = os.path.join(projects_dir, project_entry, "agent-transcripts")
        if not os.path.isdir(transcripts_dir):
            continue

        workspace_path = folder_to_path(project_entry)

        for fname in os.listdir(transcripts_dir):
            ext = get_ext(fname)
            if ext not in ("jsonl", "txt"):
                continue
            filepath = os.path.join(transcripts_dir, fname)
            if not os.path.isfile(filepath):
                continue

            session = _build_session(filepath, fname, project_entry,
                                     workspace_path, ext, model_map)
            sessions.append(session)

    sessions.sort(key=lambda s: s["modified"], reverse=True)
    _write_cache(sessions, cache_file)
    print(f"Indexed {len(sessions)} sessions.", file=sys.stderr)


def _build_session(filepath, fname, folder, workspace, ext, model_map):
    """Assemble a single session dict from a transcript file."""
    session_id = os.path.splitext(fname)[0]
    stat = os.stat(filepath)
    parsed = parse(filepath)
    model_info = model_map.get(session_id, {})

    return {
        "id": session_id,
        "workspace": workspace,
        "folder": folder,
        "format": ext,
        "modified": int(stat.st_mtime),
        "date": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "size": stat.st_size,
        "messages": parsed["messages"],
        "tool_calls": parsed["tool_calls"],
        "summary": parsed["summary"],
        "transcript_path": filepath,
        "input_tokens": parsed["input_tokens"],
        "output_tokens": parsed["output_tokens"],
        "total_tokens": parsed["input_tokens"] + parsed["output_tokens"],
        "model": model_info.get("model", ""),
        "code_edits": model_info.get("edits", 0),
    }


def _write_cache(sessions, cache_file):
    """Write the session index with restrictive file permissions."""
    old_umask = os.umask(0o077)
    try:
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(sessions, f, indent=2)
    finally:
        os.umask(old_umask)


# ── CLI entrypoint ───────────────────────────────────────────────────────────


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--preview":
        filepath = sys.argv[2]
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        preview(filepath, limit)
    elif len(sys.argv) == 3:
        build_index(sys.argv[1], sys.argv[2])
    else:
        print(f"Usage: {sys.argv[0]} <projects_dir> <cache_file>", file=sys.stderr)
        print(f"       {sys.argv[0]} --preview <transcript_path> [limit]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
