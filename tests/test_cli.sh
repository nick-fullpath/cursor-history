#!/usr/bin/env bash
# ╔════════════════════════════════════════════════════════════════════════════╗
# ║  Integration tests for the cursor-history CLI                            ║
# ║                                                                          ║
# ║  Creates a temporary mock environment (projects dir, cache, transcripts) ║
# ║  and exercises every non-interactive command. Validates output content,   ║
# ║  exit codes, and error handling.                                         ║
# ║                                                                          ║
# ║  Usage: bash tests/test_cli.sh                                           ║
# ╚════════════════════════════════════════════════════════════════════════════╝
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLI="$SCRIPT_DIR/cursor-history"

PASS=0
FAIL=0
ERRORS=()

# ─── Test helpers ─────────────────────────────────────────────────────────────

pass() { (( PASS++ )) || true; printf "  \033[32m✓\033[0m %s\n" "$1"; }
fail() { (( FAIL++ )) || true; ERRORS+=("$1"); printf "  \033[31m✗\033[0m %s\n" "$1"; }

assert_exit() {
  local expected="$1" actual="$2" name="$3"
  if [[ "$actual" == "$expected" ]]; then
    pass "$name"
  else
    fail "$name (expected exit $expected, got $actual)"
  fi
}

assert_contains() {
  local output="$1" pattern="$2" name="$3"
  if echo "$output" | grep -q "$pattern"; then
    pass "$name"
  else
    fail "$name (output missing: $pattern)"
  fi
}

assert_not_contains() {
  local output="$1" pattern="$2" name="$3"
  if ! echo "$output" | grep -q "$pattern"; then
    pass "$name"
  else
    fail "$name (output should not contain: $pattern)"
  fi
}

assert_json_length() {
  local output="$1" expected="$2" name="$3"
  local actual
  actual=$(echo "$output" | jq 'length')
  if [[ "$actual" == "$expected" ]]; then
    pass "$name"
  else
    fail "$name (expected length $expected, got $actual)"
  fi
}

# ─── Setup mock environment ──────────────────────────────────────────────────

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

MOCK_PROJECTS="$TMPDIR/projects"
MOCK_CACHE="$TMPDIR/cache"
mkdir -p "$MOCK_PROJECTS" "$MOCK_CACHE"

export CURSOR_PROJECTS_DIR="$MOCK_PROJECTS"
export CURSOR_HISTORY_CACHE="$MOCK_CACHE"

# Create mock project with transcripts
PROJECT1="$MOCK_PROJECTS/tmp-testproject"
TRANSCRIPTS1="$PROJECT1/agent-transcripts"
mkdir -p "$TRANSCRIPTS1"

cat > "$TRANSCRIPTS1/aaaa1111-2222-3333-4444-555555555555.jsonl" << 'EOF'
{"role":"user","message":{"content":[{"type":"text","text":"implement user authentication with JWT"}]}}
{"role":"assistant","message":{"content":[{"type":"text","text":"I'll implement JWT authentication for you."}]}}
{"role":"assistant","message":{"content":[{"type":"tool_use","name":"write_file"},{"type":"text","text":"Created the auth middleware."}]}}
EOF

cat > "$TRANSCRIPTS1/bbbb2222-3333-4444-5555-666666666666.jsonl" << 'EOF'
{"role":"user","message":{"content":[{"type":"text","text":"fix the database migration script"}]}}
{"role":"assistant","message":{"content":[{"type":"text","text":"Let me look at the migration."}]}}
EOF

# Second project
PROJECT2="$MOCK_PROJECTS/tmp-otherproject"
TRANSCRIPTS2="$PROJECT2/agent-transcripts"
mkdir -p "$TRANSCRIPTS2"

cat > "$TRANSCRIPTS2/cccc3333-4444-5555-6666-777777777777.jsonl" << 'EOF'
{"role":"user","message":{"content":[{"type":"text","text":"set up CI/CD pipeline with GitHub Actions"}]}}
{"role":"assistant","message":{"content":[{"type":"text","text":"I'll create the workflow files."}]}}
{"role":"assistant","message":{"content":[{"type":"tool_use","name":"write_file"},{"type":"tool_use","name":"run_command"}]}}
{"role":"user","message":{"content":[{"type":"text","text":"add deployment stage too"}]}}
{"role":"assistant","message":{"content":[{"type":"text","text":"Adding deployment stage."}]}}
EOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  cursor-history CLI integration tests"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ─── version ──────────────────────────────────────────────────────────────────

echo "version / help:"
output=$(bash "$CLI" version 2>&1); rc=$?
assert_exit 0 "$rc" "version exits 0"
assert_contains "$output" "cursor-history v" "version shows version string"

output=$(bash "$CLI" --version 2>&1); rc=$?
assert_exit 0 "$rc" "--version exits 0"

output=$(bash "$CLI" -v 2>&1); rc=$?
assert_exit 0 "$rc" "-v exits 0"

# ─── help ─────────────────────────────────────────────────────────────────────

output=$(bash "$CLI" help 2>&1); rc=$?
assert_exit 0 "$rc" "help exits 0"
assert_contains "$output" "USAGE" "help shows USAGE section"
assert_contains "$output" "LIST OPTIONS" "help shows LIST OPTIONS"
assert_contains "$output" "SHELL INTEGRATION" "help shows SHELL INTEGRATION"

output=$(bash "$CLI" --help 2>&1); rc=$?
assert_exit 0 "$rc" "--help exits 0"

output=$(bash "$CLI" -h 2>&1); rc=$?
assert_exit 0 "$rc" "-h exits 0"

echo ""

# ─── list ─────────────────────────────────────────────────────────────────────

echo "list:"
output=$(bash "$CLI" list 2>&1); rc=$?
assert_exit 0 "$rc" "list exits 0"
assert_contains "$output" "3 sessions" "list shows correct session count"
assert_contains "$output" "aaaa1111" "list shows session ID prefix"
assert_contains "$output" "bbbb2222" "list shows second session"
assert_contains "$output" "cccc3333" "list shows third session"

echo ""

# ─── list --json ──────────────────────────────────────────────────────────────

echo "list --json:"
output=$(bash "$CLI" list --json 2>&1); rc=$?
assert_exit 0 "$rc" "list --json exits 0"
assert_json_length "$output" 3 "list --json returns 3 sessions"

echo ""

# ─── list -n (limit) ─────────────────────────────────────────────────────────

echo "list -n:"
output=$(bash "$CLI" list -n 1 --json 2>&1); rc=$?
assert_exit 0 "$rc" "list -n 1 exits 0"
assert_json_length "$output" 1 "list -n 1 returns 1 session"

output=$(bash "$CLI" list -n 0 --json 2>&1); rc=$?
assert_json_length "$output" 0 "list -n 0 returns 0 sessions"

echo ""

# ─── list -w (workspace filter) ──────────────────────────────────────────────

echo "list -w:"
output=$(bash "$CLI" list -w testproject --json 2>&1); rc=$?
assert_exit 0 "$rc" "list -w testproject exits 0"
assert_json_length "$output" 2 "list -w testproject returns 2 sessions"

output=$(bash "$CLI" list -w otherproject --json 2>&1); rc=$?
assert_json_length "$output" 1 "list -w otherproject returns 1 session"

output=$(bash "$CLI" list -w nonexistent --json 2>&1); rc=$?
assert_json_length "$output" 0 "list -w nonexistent returns 0 sessions"

echo ""

# ─── list error handling ─────────────────────────────────────────────────────

echo "list errors:"
output=$(bash "$CLI" list --badarg 2>&1); rc=$?
assert_exit 1 "$rc" "list --badarg exits 1"
assert_contains "$output" "Unknown option" "list --badarg shows error"

output=$(bash "$CLI" list -n abc 2>&1); rc=$?
assert_exit 1 "$rc" "list -n abc exits 1"
assert_contains "$output" "positive integer" "list -n abc shows validation error"

output=$(bash "$CLI" list unexpected_arg 2>&1); rc=$?
assert_exit 1 "$rc" "list with positional arg exits 1"
assert_contains "$output" "Unexpected argument" "list positional arg shows error"

echo ""

# ─── show ─────────────────────────────────────────────────────────────────────

echo "show:"
output=$(bash "$CLI" show aaaa1111 2>&1); rc=$?
assert_exit 0 "$rc" "show exits 0"
assert_contains "$output" "aaaa1111-2222-3333-4444-555555555555" "show displays full ID"
assert_contains "$output" "Messages:" "show displays message count"
assert_contains "$output" "Tool calls:" "show displays tool calls"
assert_contains "$output" "implement user authentication with JWT" "show displays summary"
assert_contains "$output" "Conversation:" "show displays conversation section"

output=$(bash "$CLI" show cccc3333 2>&1); rc=$?
assert_exit 0 "$rc" "show with different session exits 0"
assert_contains "$output" "CI/CD pipeline" "show displays correct summary"

echo ""

# ─── show error handling ─────────────────────────────────────────────────────

echo "show errors:"
output=$(bash "$CLI" show 2>&1); rc=$?
assert_exit 1 "$rc" "show without ID exits 1"
assert_contains "$output" "Usage" "show without ID shows usage"

output=$(bash "$CLI" show deadbeef 2>&1); rc=$?
assert_exit 0 "$rc" "show with nonexistent ID exits 0"
assert_contains "$output" "Session not found" "show nonexistent ID shows error"

echo ""

# ─── resume ───────────────────────────────────────────────────────────────────

echo "resume:"
output=$(bash "$CLI" resume aaaa1111 2>&1); rc=$?
assert_exit 0 "$rc" "resume exits 0"
assert_contains "$output" "Resuming session" "resume shows header"
assert_contains "$output" "aaaa1111-2222-3333-4444-555555555555" "resume shows full ID"
assert_contains "$output" "__CURSOR_HISTORY_CD__" "resume emits directive"
assert_contains "$output" "cursor-agent --resume" "resume directive contains resume command"

echo ""

# ─── resume error handling ────────────────────────────────────────────────────

echo "resume errors:"
output=$(bash "$CLI" resume 2>&1); rc=$?
assert_exit 1 "$rc" "resume without ID exits 1"

output=$(bash "$CLI" resume 'bad;id' 2>&1); rc=$?
assert_exit 1 "$rc" "resume with invalid ID exits 1"
assert_contains "$output" "Invalid session ID" "resume invalid ID shows error"

output=$(bash "$CLI" resume 'AABB' 2>&1); rc=$?
assert_exit 1 "$rc" "resume with uppercase hex exits 1"

output=$(bash "$CLI" resume deadbeef 2>&1); rc=$?
assert_exit 1 "$rc" "resume with nonexistent ID exits 1"
assert_contains "$output" "not found" "resume nonexistent shows error"

echo ""

# ─── search ───────────────────────────────────────────────────────────────────

echo "search:"
output=$(bash "$CLI" search "JWT" 2>&1); rc=$?
assert_exit 0 "$rc" "search exits 0"
assert_contains "$output" "1 sessions" "search finds 1 match for JWT"
assert_contains "$output" "aaaa1111" "search result contains correct session"

output=$(bash "$CLI" search "migration" 2>&1); rc=$?
assert_exit 0 "$rc" "search for migration exits 0"
assert_contains "$output" "1 sessions" "search finds 1 match for migration"

output=$(bash "$CLI" search "nonexistent_query_xyz" 2>&1); rc=$?
assert_exit 0 "$rc" "search with no results exits 0"
assert_contains "$output" "No sessions match" "search no results shows message"

echo ""

# ─── search error handling ────────────────────────────────────────────────────

echo "search errors:"
output=$(bash "$CLI" search 2>&1); rc=$?
assert_exit 1 "$rc" "search without query exits 1"
assert_contains "$output" "Usage" "search without query shows usage"

echo ""

# ─── stats ────────────────────────────────────────────────────────────────────

echo "stats:"
output=$(bash "$CLI" stats 2>&1); rc=$?
assert_exit 0 "$rc" "stats exits 0"
assert_contains "$output" "Stats Dashboard" "stats shows dashboard header"
assert_contains "$output" "Total sessions:" "stats shows total sessions"
assert_contains "$output" "Total messages:" "stats shows total messages"
assert_contains "$output" "Total tool calls:" "stats shows tool calls"
assert_contains "$output" "Workspaces:" "stats shows workspace count"
assert_contains "$output" "Sessions by Workspace" "stats shows workspace breakdown"
assert_contains "$output" "Largest Sessions" "stats shows largest sessions"

echo ""

# ─── rebuild ──────────────────────────────────────────────────────────────────

echo "rebuild:"
output=$(bash "$CLI" rebuild 2>&1); rc=$?
assert_exit 0 "$rc" "rebuild exits 0"
assert_contains "$output" "Indexed 3 sessions" "rebuild shows correct count"
assert_contains "$output" "Done" "rebuild shows completion"

echo ""

# ─── unknown command ──────────────────────────────────────────────────────────

echo "unknown command:"
output=$(bash "$CLI" foobar 2>&1); rc=$?
assert_exit 1 "$rc" "unknown command exits 1"
assert_contains "$output" "Unknown command" "unknown command shows error"

echo ""

# ─── init ─────────────────────────────────────────────────────────────────────

echo "init:"
output=$(bash "$CLI" init zsh 2>&1); rc=$?
assert_exit 0 "$rc" "init zsh exits 0"
assert_contains "$output" "cursor-history()" "init outputs shell function"
assert_contains "$output" "_cursor_history_open_tab" "init outputs tab helper"
assert_contains "$output" "__CURSOR_HISTORY_CD__" "init references directive"

output=$(bash "$CLI" init bash 2>&1); rc=$?
assert_exit 0 "$rc" "init bash exits 0"

output=$(bash "$CLI" init fish 2>&1); rc=$?
assert_exit 1 "$rc" "init fish exits 1"
assert_contains "$output" "Unsupported shell" "init fish shows error"

echo ""

# ─── cache freshness ─────────────────────────────────────────────────────────

echo "cache freshness:"
# First call should build the cache
rm -f "$MOCK_CACHE/sessions.json"
output=$(bash "$CLI" list --json 2>&1); rc=$?
assert_exit 0 "$rc" "list builds cache when missing"
assert_contains "$output" "aaaa1111" "fresh cache has correct data"

# Second call should use cache (no "Scanning" message)
output=$(bash "$CLI" list 2>&1); rc=$?
assert_not_contains "$output" "Scanning" "second list uses cache"

# Touch a transcript dir to invalidate
sleep 1
touch "$TRANSCRIPTS1"
output=$(bash "$CLI" list 2>&1); rc=$?
assert_contains "$output" "Scanning" "list rebuilds after transcript dir change"

echo ""

# ─── Summary ──────────────────────────────────────────────────────────────────

TOTAL=$((PASS + FAIL))
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if (( FAIL == 0 )); then
  printf "  \033[32m%d/%d tests passed\033[0m\n" "$PASS" "$TOTAL"
else
  printf "  \033[31m%d/%d tests passed (%d failed)\033[0m\n" "$PASS" "$TOTAL" "$FAIL"
  echo ""
  echo "  Failed tests:"
  for err in "${ERRORS[@]}"; do
    echo "    - $err"
  done
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

exit $FAIL
