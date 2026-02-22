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
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

CHARS_PER_TOKEN = 4
MAX_SUMMARY_LEN = 200
_TAG_RE = re.compile(r"<[^>]+>")


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


def _clean_text(text):
    """Strip XML/HTML tags and normalize whitespace."""
    return " ".join(_TAG_RE.sub("", text).split())


@dataclass
class TranscriptStats:
    """Accumulates metrics while parsing a transcript in a single pass.

    Both JSONL and TXT parsers feed data into the same structure via
    add_message / add_tool_call, keeping the parsing logic focused on
    format-specific concerns only.
    """
    summary: str = ""
    messages: int = 0
    tool_calls: int = 0
    _input_chars: int = field(default=0, repr=False)
    _output_chars: int = field(default=0, repr=False)

    def add_message(self, role, text=""):
        self.messages += 1
        if role == "user":
            self._input_chars += len(text)
            if not self.summary and text:
                self.summary = _clean_text(text)[:MAX_SUMMARY_LEN]
        else:
            self._output_chars += len(text)

    def add_tool_call(self):
        self.tool_calls += 1

    def to_dict(self):
        return {
            "summary": self.summary,
            "messages": self.messages,
            "tool_calls": self.tool_calls,
            "input_tokens": self._input_chars // CHARS_PER_TOKEN,
            "output_tokens": self._output_chars // CHARS_PER_TOKEN,
        }


def parse_transcript(filepath):
    """Parse a transcript file in a single pass, extracting all metrics.

    Returns a dict with keys: summary, messages, tool_calls,
    input_tokens, output_tokens.
    """
    ext = _get_ext(filepath)
    stats = TranscriptStats()

    try:
        with open(filepath, "r", errors="replace") as f:
            if ext == "jsonl":
                _parse_jsonl(f, stats)
            elif ext == "txt":
                _parse_txt(f.read(), stats)
    except Exception:
        pass

    return stats.to_dict()


def _parse_jsonl(f, stats):
    """Feed JSONL transcript lines into stats."""
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            stats.messages += 1
            continue

        role = d.get("role", "")
        text_parts = []
        for block in d.get("message", {}).get("content", []):
            if block.get("type") == "tool_use":
                stats.add_tool_call()
            elif block.get("type") == "text":
                text_parts.append(block.get("text", ""))

        stats.add_message(role, "".join(text_parts))


def _parse_txt(text, stats):
    """Feed plain-text transcript lines into stats."""
    m = re.search(r"<user_query>\s*(.*?)\s*</user_query>", text, re.DOTALL)
    if m:
        stats.summary = _clean_text(m.group(1))[:MAX_SUMMARY_LEN]

    current_role = None
    for line in text.split("\n"):
        stripped = line.strip()

        if stripped in ("user:", "assistant:"):
            current_role = stripped.rstrip(":")
            stats.messages += 1
            continue

        if stripped.startswith("[Tool call]"):
            stats.add_tool_call()

        if current_role == "user":
            stats._input_chars += len(line)
            if not stats.summary and stripped and not stripped.startswith("<"):
                stats.summary = stripped[:MAX_SUMMARY_LEN]
        elif current_role == "assistant":
            stats._output_chars += len(line)


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
