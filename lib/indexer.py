#!/usr/bin/env python3
"""
cursor-history session indexer.

Scans all Cursor Agent CLI transcript directories under the projects folder,
parses each session's metadata (prompts, message counts, token estimates,
model info), and writes a JSON index to the cache file.

Called from the cursor-history shell script:

    python3 lib/indexer.py <projects_dir> <cache_file>
    python3 lib/indexer.py --preview <transcript_path> [limit]

The resulting JSON array is sorted by modification time (newest first) and
written with 0600 permissions to prevent other users from reading it.

Data sources:
    - Transcript files (.jsonl / .txt) in ~/.cursor/projects/*/agent-transcripts/
    - Model attribution from ~/.cursor/ai-tracking/ai-code-tracking.db (SQLite)
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from functools import lru_cache

CHARS_PER_TOKEN = 4


# ── Path reconstruction ─────────────────────────────────────────────────────
#
# Cursor encodes workspace paths by replacing '/' and '.' with '-' in the
# project folder name. For example:
#   /Users/jane.doe/projects/my-api → Users-jane-doe-projects-my-api
#
# The challenge: '-' can also appear as a literal character in real directory
# names (e.g., "my-api"), so we can't simply replace all dashes. Instead, we
# use DFS to try all three possible interpretations at each dash boundary
# (literal dash, dot, or path separator) and validate against the filesystem.


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
        """Recursively try all separator options at position idx.

        Args:
            idx:     Current index into the parts array
            segment: The path segment being built (accumulated between slashes)
            prefix:  The resolved path prefix so far

        Returns:
            The best matching filesystem path, or None.
        """
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


# ── Transcript parsing (single-pass) ────────────────────────────────────────
#
# Cursor stores transcripts in two formats:
#   - .jsonl: One JSON object per line, each with {role, message: {content: [...]}}
#   - .txt:   Plain text with "user:" / "assistant:" role markers and <user_query> tags
#
# All metrics (summary, message count, tool calls, token estimates) are
# extracted in a single read of the file to avoid redundant I/O.


def _get_ext(filepath):
    """Return the file extension without the dot, using os.path.splitext."""
    return os.path.splitext(filepath)[1].lstrip(".")


def parse_transcript(filepath):
    """Parse a transcript file in a single pass, extracting all metrics.

    Returns a dict with keys:
        summary:       str  — first user prompt (up to 200 chars)
        messages:      int  — total user + assistant messages
        tool_calls:    int  — number of tool invocations
        input_tokens:  int  — estimated input tokens (chars / 4)
        output_tokens: int  — estimated output tokens (chars / 4)
    """
    ext = _get_ext(filepath)
    result = {
        "summary": "",
        "messages": 0,
        "tool_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }

    try:
        with open(filepath, "r", errors="replace") as f:
            if ext == "jsonl":
                result = _parse_jsonl(f)
            elif ext == "txt":
                result = _parse_txt(f.read())
    except Exception:
        pass

    return result


def _parse_jsonl(f):
    """Single-pass parser for JSONL transcripts."""
    summary = ""
    messages = 0
    tool_calls = 0
    input_chars = 0
    output_chars = 0
    first_user_seen = False

    for line in f:
        line = line.strip()
        if not line:
            continue
        messages += 1
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        role = d.get("role", "")
        for c in d.get("message", {}).get("content", []):
            ctype = c.get("type", "")
            if ctype == "tool_use":
                tool_calls += 1
            elif ctype == "text":
                text = c.get("text", "")
                if role == "user":
                    input_chars += len(text)
                    if not first_user_seen:
                        cleaned = re.sub(r"<[^>]+>", "", text).strip()
                        summary = " ".join(cleaned.split())[:200]
                        first_user_seen = True
                else:
                    output_chars += len(text)

    return {
        "summary": summary,
        "messages": messages,
        "tool_calls": tool_calls,
        "input_tokens": input_chars // CHARS_PER_TOKEN,
        "output_tokens": output_chars // CHARS_PER_TOKEN,
    }


def _parse_txt(text):
    """Single-pass parser for plain-text transcripts."""
    summary = ""
    messages = 0
    tool_calls = 0
    input_chars = 0
    output_chars = 0
    current_role = None

    # Try extracting summary from <user_query> tags first
    m = re.search(r"<user_query>\s*(.*?)\s*</user_query>", text, re.DOTALL)
    if m:
        summary = " ".join(m.group(1).split())[:200]

    for line in text.split("\n"):
        stripped = line.strip()
        if stripped == "user:":
            current_role = "user"
            messages += 1
            continue
        if stripped == "assistant:":
            current_role = "assistant"
            messages += 1
            continue
        if stripped.startswith("[Tool call]"):
            tool_calls += 1
        if current_role == "user":
            input_chars += len(line)
            if not summary and stripped and not stripped.startswith("<"):
                summary = stripped[:200]
        elif current_role == "assistant":
            output_chars += len(line)

    return {
        "summary": summary,
        "messages": messages,
        "tool_calls": tool_calls,
        "input_tokens": input_chars // CHARS_PER_TOKEN,
        "output_tokens": output_chars // CHARS_PER_TOKEN,
    }


# ── Transcript preview ──────────────────────────────────────────────────────
#
# Renders a conversation excerpt for the fzf preview pane or `show` command.
# Extracted here so the bash script doesn't need inline Python.

def preview_transcript(filepath, limit=20):
    """Print a formatted conversation excerpt from a transcript file.

    Args:
        filepath: Path to the .jsonl or .txt transcript
        limit:    Maximum number of messages to display
    """
    ext = _get_ext(filepath)
    count = 0

    try:
        if ext == "jsonl":
            with open(filepath, "r", errors="replace") as f:
                for line in f:
                    if count >= limit:
                        print("  ... (truncated)")
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    role = d.get("role", "?")
                    for c in d.get("message", {}).get("content", []):
                        if c.get("type") == "text":
                            text = re.sub(r"<[^>]+>", "", c["text"]).strip()
                            text = " ".join(text.split())[:150]
                            marker = "\u25b6" if role == "user" else "\u25c0"
                            print(f"  {marker} [{role}] {text}")
                            count += 1
                            break

        elif ext == "txt":
            with open(filepath, "r", errors="replace") as f:
                text = f.read()
            for line in text.split("\n"):
                if count >= limit:
                    print("  ... (truncated)")
                    break
                stripped = line.strip()
                if stripped in ("user:", "assistant:"):
                    continue
                if stripped.startswith("<user_query>") or stripped.startswith("</user_query>"):
                    continue
                if stripped.startswith("[Tool call]"):
                    print(f"  \U0001f527 {stripped}")
                    count += 1
                elif stripped and not stripped.startswith("[Tool result]"):
                    cleaned = re.sub(r"<[^>]+>", "", stripped).strip()
                    if cleaned:
                        print(f"  {cleaned[:150]}")
                        count += 1
    except Exception:
        pass


# ── Model data from Cursor's tracking DB ─────────────────────────────────────
#
# Cursor maintains a SQLite database at ~/.cursor/ai-tracking/ai-code-tracking.db
# that logs which model was used for each code edit. We query this to attribute
# a model name and code-edit count to each session.

def load_model_map():
    """Load model name and code-edit count per conversation from Cursor's DB.

    Queries the ai_code_hashes table, grouping by conversationId and model.
    For sessions that used multiple models, the model with the most edits wins.

    Returns:
        Dict mapping session_id -> {"model": str, "edits": int}.
        Returns an empty dict if the DB doesn't exist or can't be read.
    """
    db_path = os.path.expanduser("~/.cursor/ai-tracking/ai-code-tracking.db")
    result = {}
    if not os.path.exists(db_path):
        return result
    try:
        with sqlite3.connect(db_path, timeout=2) as conn:
            cursor = conn.execute("""
                SELECT conversationId, model, COUNT(*) as edits
                FROM ai_code_hashes
                WHERE conversationId IS NOT NULL
                GROUP BY conversationId, model
                ORDER BY edits DESC
            """)
            for cid, model, edits in cursor.fetchall():
                if cid not in result:
                    result[cid] = {"model": model, "edits": edits}
                else:
                    result[cid]["edits"] += edits
    except Exception:
        pass
    return result


# ── Main indexing logic ──────────────────────────────────────────────────────

def build_index(projects_dir, cache_file):
    """Scan all project transcript directories and write the session index.

    Walks every subdirectory of projects_dir looking for agent-transcripts/
    folders. For each transcript file found, it:
      1. Reconstructs the original workspace path from the folder name
      2. Parses the transcript in a single pass (summary, counts, tokens)
      3. Looks up model attribution from Cursor's tracking DB

    The resulting JSON array is sorted newest-first and written to cache_file
    with restrictive permissions (umask 077 -> only owner can read/write).

    Args:
        projects_dir: Path to ~/.cursor/projects (or override)
        cache_file:   Path to write the JSON index to
    """
    model_map = load_model_map()
    sessions = []

    if not os.path.isdir(projects_dir):
        print(f"Projects directory not found: {projects_dir}", file=sys.stderr)
        sys.exit(1)

    for project_entry in sorted(os.listdir(projects_dir)):
        project_path = os.path.join(projects_dir, project_entry)
        if not os.path.isdir(project_path):
            continue
        transcripts_dir = os.path.join(project_path, "agent-transcripts")
        if not os.path.isdir(transcripts_dir):
            continue

        workspace_path = folder_to_path(project_entry)

        for fname in os.listdir(transcripts_dir):
            ext = _get_ext(fname)
            if ext not in ("jsonl", "txt"):
                continue
            filepath = os.path.join(transcripts_dir, fname)
            if not os.path.isfile(filepath):
                continue

            session_id = os.path.splitext(fname)[0]
            stat = os.stat(filepath)
            modified = int(stat.st_mtime)
            size = stat.st_size
            date_str = datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M")

            parsed = parse_transcript(filepath)
            model_info = model_map.get(session_id, {})

            sessions.append({
                "id": session_id,
                "workspace": workspace_path,
                "folder": project_entry,
                "format": ext,
                "modified": modified,
                "date": date_str,
                "size": size,
                "messages": parsed["messages"],
                "tool_calls": parsed["tool_calls"],
                "summary": parsed["summary"],
                "transcript_path": filepath,
                "input_tokens": parsed["input_tokens"],
                "output_tokens": parsed["output_tokens"],
                "total_tokens": parsed["input_tokens"] + parsed["output_tokens"],
                "model": model_info.get("model", ""),
                "code_edits": model_info.get("edits", 0),
            })

    sessions.sort(key=lambda s: s["modified"], reverse=True)

    old_umask = os.umask(0o077)
    try:
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(sessions, f, indent=2)
    finally:
        os.umask(old_umask)

    print(f"Indexed {len(sessions)} sessions.", file=sys.stderr)


# ── CLI entrypoint ───────────────────────────────────────────────────────────

def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--preview":
        filepath = sys.argv[2]
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        preview_transcript(filepath, limit)
    elif len(sys.argv) == 3:
        build_index(sys.argv[1], sys.argv[2])
    else:
        print(f"Usage: {sys.argv[0]} <projects_dir> <cache_file>", file=sys.stderr)
        print(f"       {sys.argv[0]} --preview <transcript_path> [limit]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
