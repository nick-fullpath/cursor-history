#!/usr/bin/env python3
"""
cursor-history session indexer.

Scans all Cursor Agent CLI transcript directories under the projects folder,
parses each session's metadata (prompts, message counts, token estimates,
model info), and writes a JSON index to the cache file.

Called from the cursor-history shell script:

    python3 lib/indexer.py <projects_dir> <cache_file>

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

# Rough heuristic for token estimation: 1 token ≈ 4 characters.
# This is a widely-used approximation for English text with LLMs.
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
    # Special case: /var paths are always slash-separated
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
        # Option 1: Keep the dash as a literal '-' (e.g., "my-api")
        r_dash = solve(idx + 1, segment + "-" + part, prefix)
        # Option 2: Replace the dash with '.' (e.g., "jane.doe")
        r_dot = solve(idx + 1, segment + "." + part, prefix)
        # Option 3: Replace the dash with '/' (path separator)
        candidate = prefix + "/" + segment if prefix else "/" + segment
        r_slash = None
        if os.path.exists(candidate):
            r_slash = solve(idx + 1, part, candidate)
        # Prefer paths that actually exist on the filesystem
        for r in [r_slash, r_dot, r_dash]:
            if r and os.path.exists(r):
                return r
        return r_slash or r_dot or r_dash

    return solve(1, parts[0], "")


# ── Transcript parsing ───────────────────────────────────────────────────────
#
# Cursor stores transcripts in two formats:
#   - .jsonl: One JSON object per line, each with {role, message: {content: [...]}}
#   - .txt:   Plain text with "user:" / "assistant:" role markers and <user_query> tags
#
# Each parsing function handles both formats.

def extract_first_prompt(filepath):
    """Extract the first user prompt from a transcript file.

    For JSONL: reads the first line and extracts the text content.
    For TXT: looks for <user_query>...</user_query> tags, or falls back
    to the first non-empty, non-marker line.

    Returns:
        The first user prompt (up to 200 chars), or "" if not found.
    """
    ext = filepath.rsplit(".", 1)[-1]
    try:
        with open(filepath, "r", errors="replace") as f:
            if ext == "jsonl":
                line = f.readline()
                if not line.strip():
                    return ""
                d = json.loads(line)
                for c in d.get("message", {}).get("content", []):
                    if c.get("type") == "text":
                        # Strip XML/HTML tags that Cursor sometimes wraps around prompts
                        text = re.sub(r"<[^>]+>", "", c["text"]).strip()
                        return " ".join(text.split())[:200]
            elif ext == "txt":
                text = f.read(2000)
                m = re.search(
                    r"<user_query>\s*(.*?)\s*</user_query>", text, re.DOTALL
                )
                if m:
                    return " ".join(m.group(1).split())[:200]
                for line in text.split("\n"):
                    line = line.strip()
                    if line and line != "user:" and not line.startswith("<"):
                        return line[:200]
    except Exception:
        pass
    return ""


def count_messages(filepath):
    """Count the total number of user + assistant messages in a transcript.

    For JSONL: counts non-empty lines (each line is one message).
    For TXT: counts lines matching "user:" or "assistant:" role markers.
    """
    ext = filepath.rsplit(".", 1)[-1]
    try:
        if ext == "jsonl":
            with open(filepath, "r", errors="replace") as f:
                return sum(1 for line in f if line.strip())
        elif ext == "txt":
            with open(filepath, "r", errors="replace") as f:
                text = f.read()
            return len(re.findall(r"^(user|assistant):", text, re.MULTILINE))
    except Exception:
        pass
    return 0


def count_tool_calls(filepath):
    """Count tool invocations in a transcript.

    For JSONL: counts content blocks with type "tool_use".
    For TXT: counts lines starting with "[Tool call]".
    """
    ext = filepath.rsplit(".", 1)[-1]
    try:
        if ext == "jsonl":
            count = 0
            with open(filepath, "r", errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                        for c in d.get("message", {}).get("content", []):
                            if c.get("type") == "tool_use":
                                count += 1
                    except Exception:
                        pass
            return count
        elif ext == "txt":
            with open(filepath, "r", errors="replace") as f:
                text = f.read()
            return len(re.findall(r"^\[Tool call\]", text, re.MULTILINE))
    except Exception:
        pass
    return 0


def estimate_tokens(filepath):
    """Estimate input and output token counts from transcript content.

    Uses the heuristic: tokens ≈ characters / 4. Separates input (user messages)
    from output (assistant messages) to give a rough breakdown.

    For JSONL: sums text content length per role.
    For TXT: tracks the current role marker and accumulates line lengths.

    Returns:
        Tuple of (input_tokens, output_tokens).
    """
    ext = filepath.rsplit(".", 1)[-1]
    input_chars = 0
    output_chars = 0
    try:
        if ext == "jsonl":
            with open(filepath, "r", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        role = d.get("role", "")
                        text_len = sum(
                            len(c.get("text", ""))
                            for c in d.get("message", {}).get("content", [])
                            if c.get("type") == "text"
                        )
                        if role == "user":
                            input_chars += text_len
                        else:
                            output_chars += text_len
                    except Exception:
                        pass
        elif ext == "txt":
            with open(filepath, "r", errors="replace") as f:
                text = f.read()
            current_role = None
            for line in text.split("\n"):
                stripped = line.strip()
                if stripped == "user:":
                    current_role = "user"
                elif stripped == "assistant:":
                    current_role = "assistant"
                elif current_role == "user":
                    input_chars += len(line)
                elif current_role == "assistant":
                    output_chars += len(line)
    except Exception:
        pass
    return input_chars // CHARS_PER_TOKEN, output_chars // CHARS_PER_TOKEN


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
        Dict mapping session_id → {"model": str, "edits": int}.
        Returns an empty dict if the DB doesn't exist or can't be read.
    """
    db_path = os.path.expanduser("~/.cursor/ai-tracking/ai-code-tracking.db")
    result = {}
    if not os.path.exists(db_path):
        return result
    try:
        # timeout=2 prevents hanging if the DB is locked by Cursor
        conn = sqlite3.connect(db_path, timeout=2)
        c = conn.cursor()
        c.execute("""
            SELECT conversationId, model, COUNT(*) as edits
            FROM ai_code_hashes
            WHERE conversationId IS NOT NULL
            GROUP BY conversationId, model
            ORDER BY edits DESC
        """)
        for cid, model, edits in c.fetchall():
            if cid not in result:
                # First row for this conversation has the most edits (ORDER BY)
                result[cid] = {"model": model, "edits": edits}
            else:
                # Additional models for the same conversation — sum the edits
                result[cid]["edits"] += edits
        conn.close()
    except Exception:
        pass
    return result


# ── Main indexing logic ──────────────────────────────────────────────────────

def build_index(projects_dir, cache_file):
    """Scan all project transcript directories and write the session index.

    Walks every subdirectory of projects_dir looking for agent-transcripts/
    folders. For each transcript file found, it:
      1. Reconstructs the original workspace path from the folder name
      2. Extracts the first user prompt as a summary
      3. Counts messages and tool calls
      4. Estimates token usage
      5. Looks up model attribution from Cursor's tracking DB

    The resulting JSON array is sorted newest-first and written to cache_file
    with restrictive permissions (umask 077 → only owner can read/write).

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

        # Reconstruct the real workspace path from the encoded folder name
        workspace_path = folder_to_path(project_entry)

        for fname in os.listdir(transcripts_dir):
            if not (fname.endswith(".jsonl") or fname.endswith(".txt")):
                continue
            filepath = os.path.join(transcripts_dir, fname)
            if not os.path.isfile(filepath):
                continue

            # Session ID is the filename without extension (a UUID)
            session_id = re.sub(r"\.(jsonl|txt)$", "", fname)
            ext = fname.rsplit(".", 1)[-1]
            stat = os.stat(filepath)
            modified = int(stat.st_mtime)
            size = stat.st_size
            date_str = datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M")

            input_tokens, output_tokens = estimate_tokens(filepath)
            model_info = model_map.get(session_id, {})

            sessions.append({
                "id": session_id,
                "workspace": workspace_path,
                "folder": project_entry,
                "format": ext,
                "modified": modified,
                "date": date_str,
                "size": size,
                "messages": count_messages(filepath),
                "tool_calls": count_tool_calls(filepath),
                "summary": extract_first_prompt(filepath),
                "transcript_path": filepath,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "model": model_info.get("model", ""),
                "code_edits": model_info.get("edits", 0),
            })

    # Sort newest first for display
    sessions.sort(key=lambda s: s["modified"], reverse=True)

    # Write with restrictive permissions (0600) since transcripts may contain
    # sensitive content (API keys, internal code, etc.)
    old_umask = os.umask(0o077)
    try:
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(sessions, f, indent=2)
    finally:
        os.umask(old_umask)

    print(f"Indexed {len(sessions)} sessions.", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <projects_dir> <cache_file>", file=sys.stderr)
        sys.exit(1)
    build_index(sys.argv[1], sys.argv[2])
