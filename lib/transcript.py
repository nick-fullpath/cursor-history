"""
Transcript parsing and preview for Cursor agent sessions.

Cursor stores transcripts in two formats:
    - .jsonl: One JSON object per line, each with {role, message: {content: [...]}}
    - .txt:   Plain text with "user:" / "assistant:" role markers and <user_query> tags

All metrics (summary, message count, tool calls, token estimates) are
extracted in a single read of the file to avoid redundant I/O.
"""

import json
import os
import re
from dataclasses import dataclass, field

CHARS_PER_TOKEN = 4
MAX_SUMMARY_LEN = 200
_TAG_RE = re.compile(r"<[^>]+>")
_USER_QUERY_RE = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.DOTALL)

PREVIEW_MARKER_USER = "\u25b6"
PREVIEW_MARKER_ASSISTANT = "\u25c0"
PREVIEW_MARKER_TOOL = "\U0001f527"
PREVIEW_MAX_LINE_LEN = 150


def get_ext(filepath):
    """Return the file extension without the dot, using os.path.splitext."""
    return os.path.splitext(filepath)[1].lstrip(".")


def _clean_text(text):
    """Strip XML/HTML tags and normalize whitespace."""
    return " ".join(_TAG_RE.sub("", text).split())


# ── Stats accumulator ────────────────────────────────────────────────────────


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


# ── Parsing ──────────────────────────────────────────────────────────────────


def parse(filepath):
    """Parse a transcript file in a single pass, extracting all metrics.

    Returns a dict with keys: summary, messages, tool_calls,
    input_tokens, output_tokens.
    """
    ext = get_ext(filepath)
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
    m = _USER_QUERY_RE.search(text)
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


# ── Preview ──────────────────────────────────────────────────────────────────


def preview(filepath, limit=20):
    """Print a formatted conversation excerpt from a transcript file.

    Args:
        filepath: Path to the .jsonl or .txt transcript
        limit:    Maximum number of messages to display
    """
    ext = get_ext(filepath)
    try:
        if ext == "jsonl":
            _preview_jsonl(filepath, limit)
        elif ext == "txt":
            _preview_txt(filepath, limit)
    except Exception:
        pass


def _preview_jsonl(filepath, limit):
    """Render a JSONL transcript as a conversation excerpt."""
    count = 0
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
            for block in d.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    text = _clean_text(block["text"])[:PREVIEW_MAX_LINE_LEN]
                    marker = PREVIEW_MARKER_USER if role == "user" else PREVIEW_MARKER_ASSISTANT
                    print(f"  {marker} [{role}] {text}")
                    count += 1
                    break


def _preview_txt(filepath, limit):
    """Render a plain-text transcript as a conversation excerpt."""
    count = 0
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
            print(f"  {PREVIEW_MARKER_TOOL} {stripped}")
            count += 1
        elif stripped and not stripped.startswith("[Tool result]"):
            cleaned = _clean_text(stripped)
            if cleaned:
                print(f"  {cleaned[:PREVIEW_MAX_LINE_LEN]}")
                count += 1
