#!/usr/bin/env python3
"""
cursor-history session indexer.

Scans Cursor Agent CLI transcript directories, parses session metadata,
and writes a JSON index to the cache file. Designed to be called from
the cursor-history shell script:

    python3 lib/indexer.py <projects_dir> <cache_file>
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime

CHARS_PER_TOKEN = 4


# ── Path reconstruction ─────────────────────────────────────────────────────

def folder_to_path(folder_name):
    """Reconstruct a real filesystem path from Cursor's encoded folder name.

    Cursor replaces '/' and '.' with '-' in folder names. We use DFS to try
    all three possible separators at each dash boundary, preferring paths
    that actually exist on the filesystem.
    """
    if folder_name.startswith("var-"):
        return "/" + folder_name.replace("-", "/")

    parts = folder_name.split("-")
    n = len(parts)
    if n == 1:
        return "/" + parts[0]

    def solve(idx, segment, prefix):
        if idx == n:
            return prefix + "/" + segment if prefix else "/" + segment
        part = parts[idx]
        # Try keeping the dash as a literal dash
        r_dash = solve(idx + 1, segment + "-" + part, prefix)
        # Try replacing the dash with a dot
        r_dot = solve(idx + 1, segment + "." + part, prefix)
        # Try replacing the dash with a path separator
        candidate = prefix + "/" + segment if prefix else "/" + segment
        r_slash = None
        if os.path.exists(candidate):
            r_slash = solve(idx + 1, part, candidate)
        # Prefer paths that exist on the filesystem
        for r in [r_slash, r_dot, r_dash]:
            if r and os.path.exists(r):
                return r
        return r_slash or r_dot or r_dash

    return solve(1, parts[0], "")


# ── Transcript parsing ───────────────────────────────────────────────────────

def extract_first_prompt(filepath):
    """Extract the first user prompt from a transcript file."""
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
    """Count user + assistant messages in a transcript."""
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
    """Count tool invocations in a transcript."""
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
    """Estimate input/output tokens from transcript content (chars / 4)."""
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

def load_model_map():
    """Load model name and code-edit count per session from Cursor's sqlite DB."""
    db_path = os.path.expanduser("~/.cursor/ai-tracking/ai-code-tracking.db")
    result = {}
    if not os.path.exists(db_path):
        return result
    try:
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
                result[cid] = {"model": model, "edits": edits}
            else:
                result[cid]["edits"] += edits
        conn.close()
    except Exception:
        pass
    return result


# ── Main indexing logic ──────────────────────────────────────────────────────

def build_index(projects_dir, cache_file):
    """Scan all project transcript directories and write the session index."""
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
            if not (fname.endswith(".jsonl") or fname.endswith(".txt")):
                continue
            filepath = os.path.join(transcripts_dir, fname)
            if not os.path.isfile(filepath):
                continue

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

    sessions.sort(key=lambda s: s["modified"], reverse=True)

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
