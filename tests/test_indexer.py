"""
Unit tests for the cursor-history Python modules.

Covers:
    - Path reconstruction (paths.folder_to_path / DFS algorithm)
    - JSONL transcript parsing (single-pass)
    - TXT transcript parsing (single-pass)
    - Token estimation
    - Transcript preview rendering
    - Model map loading (with mock SQLite DB)
    - Full build_index pipeline
    - Edge cases: empty files, malformed JSON, missing fields, binary content
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

_IS_WINDOWS = sys.platform == "win32"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import indexer
import models
import paths
import transcript


# ── Helpers ──────────────────────────────────────────────────────────────────


def _write_jsonl(lines):
    """Write a list of dicts as a JSONL temp file, return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for line in lines:
        f.write(json.dumps(line) + "\n")
    f.close()
    return f.name


def _write_txt(content):
    """Write dedented text to a temp .txt file, return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    f.write(textwrap.dedent(content))
    f.close()
    return f.name


def _write_empty(suffix):
    """Write an empty temp file with the given suffix, return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
    f.close()
    return f.name


# ── File extension ───────────────────────────────────────────────────────────


class TestGetExt(unittest.TestCase):
    def test_jsonl(self):
        self.assertEqual(transcript.get_ext("/path/to/file.jsonl"), "jsonl")

    def test_txt(self):
        self.assertEqual(transcript.get_ext("/path/to/file.txt"), "txt")

    def test_no_extension(self):
        self.assertEqual(transcript.get_ext("/path/to/file"), "")

    def test_double_extension(self):
        self.assertEqual(transcript.get_ext("archive.tar.gz"), "gz")


# ── Path reconstruction ──────────────────────────────────────────────────────


class TestFolderToPath(unittest.TestCase):
    """Test the DFS-based folder name -> filesystem path reconstruction."""

    def test_single_segment(self):
        self.assertEqual(paths.folder_to_path("tmp"), "/tmp")

    def test_var_prefix_shortcut(self):
        self.assertEqual(paths.folder_to_path("var-log-syslog"), "/var/log/syslog")

    @unittest.skipIf(_IS_WINDOWS, "POSIX path resolution test")
    def test_real_path_resolution(self):
        """When real directories exist, the DFS should find them."""
        base = tempfile.mkdtemp(dir="/tmp", prefix="ch_test_")
        try:
            target = os.path.join(base, "projects", "my-api")
            os.makedirs(target)
            folder = base.lstrip("/").replace("/", "-") + "-projects-my-api"
            paths._path_exists.cache_clear()
            self.assertEqual(paths.folder_to_path(folder), target)
        finally:
            shutil.rmtree(base)

    @unittest.skipIf(_IS_WINDOWS, "POSIX path resolution test")
    def test_dot_in_path(self):
        """Folders with dots (e.g., jane.doe) should be reconstructed."""
        base = tempfile.mkdtemp(dir="/tmp", prefix="ch_test_")
        try:
            dotdir = os.path.join(base, "jane.doe")
            os.makedirs(dotdir)
            folder = base.lstrip("/").replace("/", "-").replace(".", "-") + "-jane-doe"
            paths._path_exists.cache_clear()
            self.assertEqual(paths.folder_to_path(folder), dotdir)
        finally:
            shutil.rmtree(base)

    def test_fallback_when_no_path_exists(self):
        """When nothing exists on disk, should still return a best-effort path."""
        paths._path_exists.cache_clear()
        result = paths.folder_to_path("nonexistent-aaa-bbb-ccc")
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("/"))


# ── JSONL parsing ────────────────────────────────────────────────────────────


class TestParseJsonl(unittest.TestCase):
    """Test the single-pass JSONL transcript parser."""

    def test_basic_conversation(self):
        path = _write_jsonl([
            {"role": "user", "message": {"content": [{"type": "text", "text": "hello world"}]}},
            {"role": "assistant", "message": {"content": [{"type": "text", "text": "hi there, how can I help?"}]}},
        ])
        try:
            result = transcript.parse(path)
            self.assertEqual(result["messages"], 2)
            self.assertEqual(result["summary"], "hello world")
            self.assertEqual(result["tool_calls"], 0)
            self.assertEqual(result["input_tokens"], len("hello world") // 4)
            self.assertEqual(result["output_tokens"], len("hi there, how can I help?") // 4)
        finally:
            os.unlink(path)

    def test_tool_calls_counted(self):
        path = _write_jsonl([
            {"role": "user", "message": {"content": [{"type": "text", "text": "fix the bug"}]}},
            {"role": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "read_file"},
                {"type": "text", "text": "Let me read the file"},
            ]}},
            {"role": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "write_file"},
                {"type": "tool_use", "name": "run_command"},
            ]}},
        ])
        try:
            result = transcript.parse(path)
            self.assertEqual(result["messages"], 3)
            self.assertEqual(result["tool_calls"], 3)
        finally:
            os.unlink(path)

    def test_summary_strips_html_tags(self):
        path = _write_jsonl([
            {"role": "user", "message": {"content": [
                {"type": "text", "text": "<user_query>build a REST API</user_query>"}
            ]}},
        ])
        try:
            self.assertEqual(transcript.parse(path)["summary"], "build a REST API")
        finally:
            os.unlink(path)

    def test_summary_truncated_at_200_chars(self):
        path = _write_jsonl([
            {"role": "user", "message": {"content": [{"type": "text", "text": "a" * 300}]}},
        ])
        try:
            self.assertEqual(len(transcript.parse(path)["summary"]), 200)
        finally:
            os.unlink(path)

    def test_empty_file(self):
        path = _write_empty(".jsonl")
        try:
            result = transcript.parse(path)
            self.assertEqual(result["messages"], 0)
            self.assertEqual(result["summary"], "")
        finally:
            os.unlink(path)

    def test_malformed_json_lines_skipped(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.write('{"role":"user","message":{"content":[{"type":"text","text":"valid"}]}}\n')
        f.write("this is not json\n")
        f.write('{"role":"assistant","message":{"content":[{"type":"text","text":"reply"}]}}\n')
        f.close()
        try:
            result = transcript.parse(f.name)
            self.assertEqual(result["messages"], 3)
            self.assertEqual(result["summary"], "valid")
            self.assertGreater(result["output_tokens"], 0)
        finally:
            os.unlink(f.name)

    def test_missing_content_field(self):
        path = _write_jsonl([
            {"role": "user", "message": {}},
            {"role": "assistant"},
        ])
        try:
            result = transcript.parse(path)
            self.assertEqual(result["messages"], 2)
            self.assertEqual(result["summary"], "")
        finally:
            os.unlink(path)

    def test_multiple_content_blocks(self):
        path = _write_jsonl([
            {"role": "user", "message": {"content": [
                {"type": "text", "text": "first part"},
                {"type": "text", "text": " second part"},
            ]}},
        ])
        try:
            result = transcript.parse(path)
            self.assertEqual(result["summary"], "first part second part")
            self.assertEqual(result["input_tokens"], len("first part second part") // 4)
        finally:
            os.unlink(path)


# ── TXT parsing ──────────────────────────────────────────────────────────────


class TestParseTxt(unittest.TestCase):
    """Test the single-pass plain-text transcript parser."""

    def test_basic_conversation(self):
        path = _write_txt("""\
            user:
            <user_query>
            help me debug this
            </user_query>
            assistant:
            Sure, let me look at the code.
        """)
        try:
            result = transcript.parse(path)
            self.assertEqual(result["messages"], 2)
            self.assertEqual(result["summary"], "help me debug this")
            self.assertGreater(result["input_tokens"], 0)
            self.assertGreater(result["output_tokens"], 0)
        finally:
            os.unlink(path)

    def test_tool_calls_counted(self):
        path = _write_txt("""\
            user:
            fix the tests
            assistant:
            [Tool call] read_file tests/test_main.py
            [Tool result] read_file
            content here
            [Tool call] write_file tests/test_main.py
        """)
        try:
            self.assertEqual(transcript.parse(path)["tool_calls"], 2)
        finally:
            os.unlink(path)

    def test_summary_from_user_query_tags(self):
        path = _write_txt("""\
            user:
            <user_query>
            implement the login flow
            </user_query>
            assistant:
            I'll implement the login flow.
        """)
        try:
            self.assertEqual(transcript.parse(path)["summary"], "implement the login flow")
        finally:
            os.unlink(path)

    def test_summary_fallback_without_tags(self):
        path = _write_txt("""\
            user:
            deploy to production
            assistant:
            Starting deployment.
        """)
        try:
            self.assertEqual(transcript.parse(path)["summary"], "deploy to production")
        finally:
            os.unlink(path)

    def test_empty_file(self):
        path = _write_empty(".txt")
        try:
            result = transcript.parse(path)
            self.assertEqual(result["messages"], 0)
            self.assertEqual(result["summary"], "")
        finally:
            os.unlink(path)

    def test_unknown_extension_returns_defaults(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        f.write("some,csv,data\n")
        f.close()
        try:
            result = transcript.parse(f.name)
            self.assertEqual(result["messages"], 0)
            self.assertEqual(result["summary"], "")
        finally:
            os.unlink(f.name)


# ── Token estimation ─────────────────────────────────────────────────────────


class TestTokenEstimation(unittest.TestCase):
    def test_chars_per_token_ratio(self):
        path = _write_jsonl([
            {"role": "user", "message": {"content": [{"type": "text", "text": "a" * 400}]}},
        ])
        try:
            result = transcript.parse(path)
            self.assertEqual(result["input_tokens"], 100)
            self.assertEqual(result["output_tokens"], 0)
        finally:
            os.unlink(path)

    def test_input_output_separation(self):
        path = _write_jsonl([
            {"role": "user", "message": {"content": [{"type": "text", "text": "a" * 80}]}},
            {"role": "assistant", "message": {"content": [{"type": "text", "text": "b" * 200}]}},
        ])
        try:
            result = transcript.parse(path)
            self.assertEqual(result["input_tokens"], 20)
            self.assertEqual(result["output_tokens"], 50)
        finally:
            os.unlink(path)


# ── Preview ──────────────────────────────────────────────────────────────────


class TestPreviewTranscript(unittest.TestCase):
    def _capture_preview(self, filepath, limit=20):
        """Run preview and capture stdout."""
        from io import StringIO
        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            transcript.preview(filepath, limit)
        finally:
            sys.stdout = old_stdout
        return captured.getvalue()

    def test_jsonl_preview(self):
        path = _write_jsonl([
            {"role": "user" if i % 2 == 0 else "assistant",
             "message": {"content": [{"type": "text", "text": f"message {i}"}]}}
            for i in range(5)
        ])
        try:
            output = self._capture_preview(path, limit=3)
            lines = [l for l in output.strip().split("\n") if l.strip()]
            self.assertEqual(len(lines), 4)  # 3 messages + truncated
            self.assertIn("message 0", lines[0])
            self.assertIn("truncated", lines[-1])
        finally:
            os.unlink(path)

    def test_txt_preview(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        f.write("user:\nhello\nassistant:\nworld\n")
        f.close()
        try:
            output = self._capture_preview(f.name)
            self.assertIn("hello", output)
            self.assertIn("world", output)
        finally:
            os.unlink(f.name)

    def test_preview_limit_respected(self):
        path = _write_jsonl([
            {"role": "user", "message": {"content": [{"type": "text", "text": f"msg {i}"}]}}
            for i in range(50)
        ])
        try:
            output = self._capture_preview(path, limit=5)
            lines = [l for l in output.strip().split("\n") if l.strip()]
            self.assertEqual(len(lines), 6)  # 5 messages + truncated
        finally:
            os.unlink(path)

    def test_preview_nonexistent_file(self):
        output = self._capture_preview("/nonexistent/path.jsonl")
        self.assertEqual(output, "")


# ── Model map ────────────────────────────────────────────────────────────────


class TestLoadModelMap(unittest.TestCase):
    def _create_mock_db(self, rows):
        """Create a temp SQLite DB with ai_code_hashes table and given rows."""
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = f.name
        f.close()
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE ai_code_hashes (
                conversationId TEXT, model TEXT, hash TEXT
            )
        """)
        for row in rows:
            conn.execute("INSERT INTO ai_code_hashes VALUES (?, ?, ?)", row)
        conn.commit()
        conn.close()
        return db_path

    def _cleanup_db(self, db_path):
        try:
            os.unlink(db_path)
        except PermissionError:
            pass  # Windows may hold the file lock briefly

    def test_with_mock_db(self):
        db_path = self._create_mock_db([
            ("sess-1", "gpt-4o", "h1"),
            ("sess-1", "gpt-4o", "h2"),
            ("sess-2", "claude-4", "h3"),
        ])
        try:
            result = models.load_model_map(db_path)
            self.assertEqual(result["sess-1"], {"model": "gpt-4o", "edits": 2})
            self.assertEqual(result["sess-2"], {"model": "claude-4", "edits": 1})
        finally:
            self._cleanup_db(db_path)

    def test_missing_db_returns_empty(self):
        self.assertEqual(models.load_model_map("/nonexistent/db.sqlite"), {})

    def test_multiple_models_per_session(self):
        db_path = self._create_mock_db([
            ("sess-1", "gpt-4o", "h1"),
            ("sess-1", "gpt-4o", "h2"),
            ("sess-1", "gpt-4o", "h3"),
            ("sess-1", "claude-4", "h4"),
        ])
        try:
            result = models.load_model_map(db_path)
            self.assertEqual(result["sess-1"]["model"], "gpt-4o")
            self.assertEqual(result["sess-1"]["edits"], 4)
        finally:
            self._cleanup_db(db_path)


# ── Build index (integration) ────────────────────────────────────────────────


class TestBuildIndex(unittest.TestCase):
    def _setup_project(self, tmpdir, project_name, sessions):
        """Create a mock project directory with transcript files.

        Args:
            sessions: list of (session_id, jsonl_lines) tuples
        """
        transcripts = os.path.join(tmpdir, "projects", project_name, "agent-transcripts")
        os.makedirs(transcripts)
        for sid, lines in sessions:
            path = os.path.join(transcripts, f"{sid}.jsonl")
            with open(path, "w") as f:
                for line in lines:
                    f.write(json.dumps(line) + "\n")
        return os.path.join(tmpdir, "projects")

    def test_full_pipeline(self):
        """End-to-end: create a mock project dir, index it, verify the output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            projects_dir = self._setup_project(tmpdir, "tmp-testproject", [(
                session_id, [
                    {"role": "user", "message": {"content": [{"type": "text", "text": "hello from test"}]}},
                    {"role": "assistant", "message": {"content": [
                        {"type": "text", "text": "response"},
                        {"type": "tool_use", "name": "read"},
                    ]}},
                ]
            )])
            cache_file = os.path.join(tmpdir, "cache", "sessions.json")

            with patch.object(indexer, "load_model_map", return_value={}):
                indexer.build_index(projects_dir, cache_file)

            with open(cache_file) as f:
                sessions = json.load(f)

            self.assertEqual(len(sessions), 1)
            s = sessions[0]
            self.assertEqual(s["id"], session_id)
            self.assertEqual(s["messages"], 2)
            self.assertEqual(s["tool_calls"], 1)
            self.assertEqual(s["summary"], "hello from test")
            self.assertEqual(s["format"], "jsonl")
            self.assertGreater(s["input_tokens"], 0)
            self.assertGreater(s["output_tokens"], 0)
            self.assertEqual(s["total_tokens"], s["input_tokens"] + s["output_tokens"])

    def test_multiple_sessions_sorted_newest_first(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            user_msg = lambda t: {"role": "user", "message": {"content": [{"type": "text", "text": t}]}}
            projects_dir = self._setup_project(tmpdir, "tmp-proj", [
                (sid, [user_msg(f"session {sid}")]) for sid in ["aaa", "bbb", "ccc"]
            ])

            transcripts = os.path.join(projects_dir, "tmp-proj", "agent-transcripts")
            for i, sid in enumerate(["aaa", "bbb", "ccc"]):
                os.utime(os.path.join(transcripts, f"{sid}.jsonl"),
                         (1000000 + i * 100, 1000000 + i * 100))

            cache_file = os.path.join(tmpdir, "sessions.json")
            with patch.object(indexer, "load_model_map", return_value={}):
                indexer.build_index(projects_dir, cache_file)

            with open(cache_file) as f:
                sessions = json.load(f)

            ids = [s["id"] for s in sessions]
            self.assertEqual(ids, ["ccc", "bbb", "aaa"])

    def test_skips_non_transcript_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = self._setup_project(tmpdir, "tmp-proj", [
                ("valid", [{"role": "user", "message": {"content": [{"type": "text", "text": "hi"}]}}])
            ])
            transcripts = os.path.join(projects_dir, "tmp-proj", "agent-transcripts")
            for name in ("ignored.csv", "also-ignored.log"):
                with open(os.path.join(transcripts, name), "w") as f:
                    f.write("junk\n")

            cache_file = os.path.join(tmpdir, "sessions.json")
            with patch.object(indexer, "load_model_map", return_value={}):
                indexer.build_index(projects_dir, cache_file)

            with open(cache_file) as f:
                sessions = json.load(f)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["id"], "valid")

    @unittest.skipIf(_IS_WINDOWS, "umask has no effect on Windows")
    def test_cache_file_permissions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = self._setup_project(tmpdir, "tmp-proj", [
                ("sess", [{"role": "user", "message": {"content": [{"type": "text", "text": "hi"}]}}])
            ])
            cache_file = os.path.join(tmpdir, "cache", "sessions.json")
            with patch.object(indexer, "load_model_map", return_value={}):
                indexer.build_index(projects_dir, cache_file)

            mode = oct(os.stat(cache_file).st_mode)[-3:]
            self.assertEqual(mode, "600")

    def test_empty_projects_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = os.path.join(tmpdir, "projects")
            os.makedirs(projects_dir)
            cache_file = os.path.join(tmpdir, "sessions.json")

            with patch.object(indexer, "load_model_map", return_value={}):
                indexer.build_index(projects_dir, cache_file)

            with open(cache_file) as f:
                self.assertEqual(json.load(f), [])

    def test_model_attribution_merged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sid = "abc-123"
            projects_dir = self._setup_project(tmpdir, "tmp-proj", [
                (sid, [{"role": "user", "message": {"content": [{"type": "text", "text": "test"}]}}])
            ])
            cache_file = os.path.join(tmpdir, "sessions.json")
            mock_models = {sid: {"model": "claude-4-sonnet", "edits": 42}}
            with patch.object(indexer, "load_model_map", return_value=mock_models):
                indexer.build_index(projects_dir, cache_file)

            with open(cache_file) as f:
                sessions = json.load(f)
            self.assertEqual(sessions[0]["model"], "claude-4-sonnet")
            self.assertEqual(sessions[0]["code_edits"], 42)


if __name__ == "__main__":
    unittest.main()
