"""
Unit tests for lib/indexer.py — the cursor-history session indexer.

Covers:
    - Path reconstruction (folder_to_path / DFS algorithm)
    - JSONL transcript parsing (single-pass)
    - TXT transcript parsing (single-pass)
    - Token estimation
    - Transcript preview rendering
    - Model map loading (with mock SQLite DB)
    - Full build_index pipeline
    - Edge cases: empty files, malformed JSON, missing fields, binary content
"""

import io
import json
import os
import sqlite3
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import indexer


class TestGetExt(unittest.TestCase):
    def test_jsonl(self):
        self.assertEqual(indexer._get_ext("/path/to/file.jsonl"), "jsonl")

    def test_txt(self):
        self.assertEqual(indexer._get_ext("/path/to/file.txt"), "txt")

    def test_no_extension(self):
        self.assertEqual(indexer._get_ext("/path/to/file"), "")

    def test_double_extension(self):
        self.assertEqual(indexer._get_ext("archive.tar.gz"), "gz")


# ── Path reconstruction ──────────────────────────────────────────────────────

class TestFolderToPath(unittest.TestCase):
    """Test the DFS-based folder name → filesystem path reconstruction."""

    def test_single_segment(self):
        self.assertEqual(indexer.folder_to_path("tmp"), "/tmp")

    def test_var_prefix_shortcut(self):
        result = indexer.folder_to_path("var-log-syslog")
        self.assertEqual(result, "/var/log/syslog")

    def test_real_path_resolution(self):
        """When real directories exist, the DFS should find them.

        Uses /tmp as a stable base to avoid temp-dir path ambiguity.
        """
        base = tempfile.mkdtemp(dir="/tmp", prefix="ch_test_")
        try:
            target = os.path.join(base, "projects", "my-api")
            os.makedirs(target)
            folder = base.lstrip("/").replace("/", "-") + "-projects-my-api"
            indexer._path_exists.cache_clear()
            result = indexer.folder_to_path(folder)
            self.assertEqual(result, target)
        finally:
            import shutil
            shutil.rmtree(base)

    def test_dot_in_path(self):
        """Folders with dots (e.g., jane.doe) should be reconstructed."""
        base = tempfile.mkdtemp(dir="/tmp", prefix="ch_test_")
        try:
            dotdir = os.path.join(base, "jane.doe")
            os.makedirs(dotdir)
            folder = base.lstrip("/").replace("/", "-").replace(".", "-") + "-jane-doe"
            indexer._path_exists.cache_clear()
            result = indexer.folder_to_path(folder)
            self.assertEqual(result, dotdir)
        finally:
            import shutil
            shutil.rmtree(base)

    def test_fallback_when_no_path_exists(self):
        """When nothing exists on disk, should still return a best-effort path."""
        indexer._path_exists.cache_clear()
        result = indexer.folder_to_path("nonexistent-aaa-bbb-ccc")
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("/"))


# ── JSONL parsing ─────────────────────────────────────────────────────────────

class TestParseJsonl(unittest.TestCase):
    """Test the single-pass JSONL transcript parser."""

    def _write_jsonl(self, lines):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for line in lines:
            f.write(json.dumps(line) + "\n")
        f.close()
        return f.name

    def test_basic_conversation(self):
        path = self._write_jsonl([
            {"role": "user", "message": {"content": [{"type": "text", "text": "hello world"}]}},
            {"role": "assistant", "message": {"content": [{"type": "text", "text": "hi there, how can I help?"}]}},
        ])
        try:
            result = indexer.parse_transcript(path)
            self.assertEqual(result["messages"], 2)
            self.assertEqual(result["summary"], "hello world")
            self.assertEqual(result["tool_calls"], 0)
            self.assertEqual(result["input_tokens"], len("hello world") // 4)
            self.assertEqual(result["output_tokens"], len("hi there, how can I help?") // 4)
        finally:
            os.unlink(path)

    def test_tool_calls_counted(self):
        path = self._write_jsonl([
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
            result = indexer.parse_transcript(path)
            self.assertEqual(result["messages"], 3)
            self.assertEqual(result["tool_calls"], 3)
        finally:
            os.unlink(path)

    def test_summary_strips_html_tags(self):
        path = self._write_jsonl([
            {"role": "user", "message": {"content": [
                {"type": "text", "text": "<user_query>build a REST API</user_query>"}
            ]}},
        ])
        try:
            result = indexer.parse_transcript(path)
            self.assertEqual(result["summary"], "build a REST API")
        finally:
            os.unlink(path)

    def test_summary_truncated_at_200_chars(self):
        long_text = "a" * 300
        path = self._write_jsonl([
            {"role": "user", "message": {"content": [{"type": "text", "text": long_text}]}},
        ])
        try:
            result = indexer.parse_transcript(path)
            self.assertEqual(len(result["summary"]), 200)
        finally:
            os.unlink(path)

    def test_empty_file(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.close()
        try:
            result = indexer.parse_transcript(f.name)
            self.assertEqual(result["messages"], 0)
            self.assertEqual(result["summary"], "")
        finally:
            os.unlink(f.name)

    def test_malformed_json_lines_skipped(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.write('{"role":"user","message":{"content":[{"type":"text","text":"valid"}]}}\n')
        f.write("this is not json\n")
        f.write('{"role":"assistant","message":{"content":[{"type":"text","text":"reply"}]}}\n')
        f.close()
        try:
            result = indexer.parse_transcript(f.name)
            self.assertEqual(result["messages"], 3)
            self.assertEqual(result["summary"], "valid")
            self.assertGreater(result["output_tokens"], 0)
        finally:
            os.unlink(f.name)

    def test_missing_content_field(self):
        path = self._write_jsonl([
            {"role": "user", "message": {}},
            {"role": "assistant"},
        ])
        try:
            result = indexer.parse_transcript(path)
            self.assertEqual(result["messages"], 2)
            self.assertEqual(result["summary"], "")
        finally:
            os.unlink(path)

    def test_multiple_content_blocks(self):
        path = self._write_jsonl([
            {"role": "user", "message": {"content": [
                {"type": "text", "text": "first part"},
                {"type": "text", "text": " second part"},
            ]}},
        ])
        try:
            result = indexer.parse_transcript(path)
            self.assertEqual(result["summary"], "first part")
            self.assertEqual(result["input_tokens"], len("first part second part") // 4)
        finally:
            os.unlink(path)


# ── TXT parsing ───────────────────────────────────────────────────────────────

class TestParseTxt(unittest.TestCase):
    """Test the single-pass plain-text transcript parser."""

    def _write_txt(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        f.write(textwrap.dedent(content))
        f.close()
        return f.name

    def test_basic_conversation(self):
        path = self._write_txt("""\
            user:
            <user_query>
            help me debug this
            </user_query>
            assistant:
            Sure, let me look at the code.
        """)
        try:
            result = indexer.parse_transcript(path)
            self.assertEqual(result["messages"], 2)
            self.assertEqual(result["summary"], "help me debug this")
            self.assertGreater(result["input_tokens"], 0)
            self.assertGreater(result["output_tokens"], 0)
        finally:
            os.unlink(path)

    def test_tool_calls_counted(self):
        path = self._write_txt("""\
            user:
            fix the tests
            assistant:
            [Tool call] read_file tests/test_main.py
            [Tool result] read_file
            content here
            [Tool call] write_file tests/test_main.py
        """)
        try:
            result = indexer.parse_transcript(path)
            self.assertEqual(result["tool_calls"], 2)
        finally:
            os.unlink(path)

    def test_summary_from_user_query_tags(self):
        path = self._write_txt("""\
            user:
            <user_query>
            implement the login flow
            </user_query>
            assistant:
            I'll implement the login flow.
        """)
        try:
            result = indexer.parse_transcript(path)
            self.assertEqual(result["summary"], "implement the login flow")
        finally:
            os.unlink(path)

    def test_summary_fallback_without_tags(self):
        path = self._write_txt("""\
            user:
            deploy to production
            assistant:
            Starting deployment.
        """)
        try:
            result = indexer.parse_transcript(path)
            self.assertEqual(result["summary"], "deploy to production")
        finally:
            os.unlink(path)

    def test_empty_file(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        f.close()
        try:
            result = indexer.parse_transcript(f.name)
            self.assertEqual(result["messages"], 0)
            self.assertEqual(result["summary"], "")
        finally:
            os.unlink(f.name)

    def test_unknown_extension_returns_defaults(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        f.write("some,csv,data\n")
        f.close()
        try:
            result = indexer.parse_transcript(f.name)
            self.assertEqual(result["messages"], 0)
            self.assertEqual(result["summary"], "")
        finally:
            os.unlink(f.name)


# ── Token estimation ──────────────────────────────────────────────────────────

class TestTokenEstimation(unittest.TestCase):
    def test_chars_per_token_ratio(self):
        text_400_chars = "a" * 400
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.write(json.dumps({
            "role": "user",
            "message": {"content": [{"type": "text", "text": text_400_chars}]}
        }) + "\n")
        f.close()
        try:
            result = indexer.parse_transcript(f.name)
            self.assertEqual(result["input_tokens"], 100)
            self.assertEqual(result["output_tokens"], 0)
        finally:
            os.unlink(f.name)

    def test_input_output_separation(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.write(json.dumps({
            "role": "user",
            "message": {"content": [{"type": "text", "text": "a" * 80}]}
        }) + "\n")
        f.write(json.dumps({
            "role": "assistant",
            "message": {"content": [{"type": "text", "text": "b" * 200}]}
        }) + "\n")
        f.close()
        try:
            result = indexer.parse_transcript(f.name)
            self.assertEqual(result["input_tokens"], 20)
            self.assertEqual(result["output_tokens"], 50)
        finally:
            os.unlink(f.name)


# ── Preview ───────────────────────────────────────────────────────────────────

class TestPreviewTranscript(unittest.TestCase):
    def test_jsonl_preview(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for i in range(5):
            role = "user" if i % 2 == 0 else "assistant"
            f.write(json.dumps({
                "role": role,
                "message": {"content": [{"type": "text", "text": f"message {i}"}]}
            }) + "\n")
        f.close()
        try:
            from io import StringIO
            captured = StringIO()
            sys.stdout = captured
            indexer.preview_transcript(f.name, limit=3)
            sys.stdout = sys.__stdout__
            output = captured.getvalue()
            lines = [l for l in output.strip().split("\n") if l.strip()]
            self.assertEqual(len(lines), 4)  # 3 messages + truncated
            self.assertIn("message 0", lines[0])
            self.assertIn("truncated", lines[-1])
        finally:
            sys.stdout = sys.__stdout__
            os.unlink(f.name)

    def test_txt_preview(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        f.write("user:\nhello\nassistant:\nworld\n")
        f.close()
        try:
            from io import StringIO
            captured = StringIO()
            sys.stdout = captured
            indexer.preview_transcript(f.name, limit=20)
            sys.stdout = sys.__stdout__
            output = captured.getvalue()
            self.assertIn("hello", output)
            self.assertIn("world", output)
        finally:
            sys.stdout = sys.__stdout__
            os.unlink(f.name)

    def test_preview_limit_respected(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for i in range(50):
            f.write(json.dumps({
                "role": "user",
                "message": {"content": [{"type": "text", "text": f"msg {i}"}]}
            }) + "\n")
        f.close()
        try:
            from io import StringIO
            captured = StringIO()
            sys.stdout = captured
            indexer.preview_transcript(f.name, limit=5)
            sys.stdout = sys.__stdout__
            output = captured.getvalue()
            lines = [l for l in output.strip().split("\n") if l.strip()]
            self.assertEqual(len(lines), 6)  # 5 messages + truncated
        finally:
            sys.stdout = sys.__stdout__
            os.unlink(f.name)

    def test_preview_nonexistent_file(self):
        from io import StringIO
        captured = StringIO()
        sys.stdout = captured
        indexer.preview_transcript("/nonexistent/path.jsonl")
        sys.stdout = sys.__stdout__
        self.assertEqual(captured.getvalue(), "")


# ── Model map ─────────────────────────────────────────────────────────────────

class TestLoadModelMap(unittest.TestCase):
    def test_with_mock_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE ai_code_hashes (
                    conversationId TEXT,
                    model TEXT,
                    hash TEXT
                )
            """)
            conn.execute("INSERT INTO ai_code_hashes VALUES ('sess-1', 'gpt-4o', 'h1')")
            conn.execute("INSERT INTO ai_code_hashes VALUES ('sess-1', 'gpt-4o', 'h2')")
            conn.execute("INSERT INTO ai_code_hashes VALUES ('sess-2', 'claude-4', 'h3')")
            conn.commit()
            conn.close()

            with patch.object(indexer.os.path, "expanduser", return_value=db_path):
                result = indexer.load_model_map()

            self.assertIn("sess-1", result)
            self.assertEqual(result["sess-1"]["model"], "gpt-4o")
            self.assertEqual(result["sess-1"]["edits"], 2)
            self.assertIn("sess-2", result)
            self.assertEqual(result["sess-2"]["model"], "claude-4")
            self.assertEqual(result["sess-2"]["edits"], 1)
        finally:
            os.unlink(db_path)

    def test_missing_db_returns_empty(self):
        with patch.object(indexer.os.path, "expanduser", return_value="/nonexistent/db.sqlite"):
            result = indexer.load_model_map()
        self.assertEqual(result, {})

    def test_multiple_models_per_session(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE ai_code_hashes (
                    conversationId TEXT,
                    model TEXT,
                    hash TEXT
                )
            """)
            conn.execute("INSERT INTO ai_code_hashes VALUES ('sess-1', 'gpt-4o', 'h1')")
            conn.execute("INSERT INTO ai_code_hashes VALUES ('sess-1', 'gpt-4o', 'h2')")
            conn.execute("INSERT INTO ai_code_hashes VALUES ('sess-1', 'gpt-4o', 'h3')")
            conn.execute("INSERT INTO ai_code_hashes VALUES ('sess-1', 'claude-4', 'h4')")
            conn.commit()
            conn.close()

            with patch.object(indexer.os.path, "expanduser", return_value=db_path):
                result = indexer.load_model_map()

            self.assertEqual(result["sess-1"]["model"], "gpt-4o")
            self.assertEqual(result["sess-1"]["edits"], 4)
        finally:
            os.unlink(db_path)


# ── Build index (integration) ────────────────────────────────────────────────

class TestBuildIndex(unittest.TestCase):
    def test_full_pipeline(self):
        """End-to-end: create a mock project dir, index it, verify the output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = os.path.join(tmpdir, "projects")
            project = os.path.join(projects_dir, "tmp-testproject")
            transcripts = os.path.join(project, "agent-transcripts")
            os.makedirs(transcripts)

            # Write a JSONL transcript
            session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            filepath = os.path.join(transcripts, f"{session_id}.jsonl")
            with open(filepath, "w") as f:
                f.write(json.dumps({
                    "role": "user",
                    "message": {"content": [{"type": "text", "text": "hello from test"}]}
                }) + "\n")
                f.write(json.dumps({
                    "role": "assistant",
                    "message": {"content": [
                        {"type": "text", "text": "response"},
                        {"type": "tool_use", "name": "read"},
                    ]}
                }) + "\n")

            cache_file = os.path.join(tmpdir, "cache", "sessions.json")

            with patch.object(indexer, "load_model_map", return_value={}):
                indexer.build_index(projects_dir, cache_file)

            self.assertTrue(os.path.exists(cache_file))

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
            projects_dir = os.path.join(tmpdir, "projects")
            transcripts = os.path.join(projects_dir, "tmp-proj", "agent-transcripts")
            os.makedirs(transcripts)

            for i, sid in enumerate(["aaa", "bbb", "ccc"]):
                path = os.path.join(transcripts, f"{sid}.jsonl")
                with open(path, "w") as f:
                    f.write(json.dumps({
                        "role": "user",
                        "message": {"content": [{"type": "text", "text": f"session {sid}"}]}
                    }) + "\n")
                # Set different mtimes
                os.utime(path, (1000000 + i * 100, 1000000 + i * 100))

            cache_file = os.path.join(tmpdir, "sessions.json")
            with patch.object(indexer, "load_model_map", return_value={}):
                indexer.build_index(projects_dir, cache_file)

            with open(cache_file) as f:
                sessions = json.load(f)

            self.assertEqual(len(sessions), 3)
            self.assertEqual(sessions[0]["id"], "ccc")
            self.assertEqual(sessions[1]["id"], "bbb")
            self.assertEqual(sessions[2]["id"], "aaa")

    def test_skips_non_transcript_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = os.path.join(tmpdir, "projects")
            transcripts = os.path.join(projects_dir, "tmp-proj", "agent-transcripts")
            os.makedirs(transcripts)

            with open(os.path.join(transcripts, "valid.jsonl"), "w") as f:
                f.write(json.dumps({
                    "role": "user",
                    "message": {"content": [{"type": "text", "text": "hi"}]}
                }) + "\n")
            with open(os.path.join(transcripts, "ignored.csv"), "w") as f:
                f.write("not,a,transcript\n")
            with open(os.path.join(transcripts, "also-ignored.log"), "w") as f:
                f.write("log data\n")

            cache_file = os.path.join(tmpdir, "sessions.json")
            with patch.object(indexer, "load_model_map", return_value={}):
                indexer.build_index(projects_dir, cache_file)

            with open(cache_file) as f:
                sessions = json.load(f)

            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["id"], "valid")

    def test_cache_file_permissions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = os.path.join(tmpdir, "projects")
            transcripts = os.path.join(projects_dir, "tmp-proj", "agent-transcripts")
            os.makedirs(transcripts)

            with open(os.path.join(transcripts, "sess.jsonl"), "w") as f:
                f.write(json.dumps({
                    "role": "user",
                    "message": {"content": [{"type": "text", "text": "hi"}]}
                }) + "\n")

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
                sessions = json.load(f)
            self.assertEqual(sessions, [])

    def test_model_attribution_merged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = os.path.join(tmpdir, "projects")
            transcripts = os.path.join(projects_dir, "tmp-proj", "agent-transcripts")
            os.makedirs(transcripts)

            sid = "abc-123"
            with open(os.path.join(transcripts, f"{sid}.jsonl"), "w") as f:
                f.write(json.dumps({
                    "role": "user",
                    "message": {"content": [{"type": "text", "text": "test"}]}
                }) + "\n")

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
