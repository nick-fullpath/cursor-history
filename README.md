<p align="center">
  <h1 align="center">cursor-history</h1>
  <p align="center">
    <strong>Your Cursor Agent sessions don't have to be disposable.</strong>
    <br />
    Browse, search, and resume every CLI session — right from your terminal.
  </p>
  <p align="center">
    <a href="#installation">Installation</a> &nbsp;&bull;&nbsp;
    <a href="#usage">Usage</a> &nbsp;&bull;&nbsp;
    <a href="#commands">Commands</a> &nbsp;&bull;&nbsp;
    <a href="#how-it-works">How It Works</a> &nbsp;&bull;&nbsp;
    <a href="#contributing">Contributing</a>
  </p>
</p>

<br />

## The Problem

You've been deep in a Cursor Agent CLI session — debugging infrastructure, writing automation, investigating a production issue. Thirty messages in, dozens of tool calls, real progress made. Then you close the terminal.

Now what?

The session data is still there, buried inside `~/.cursor/projects/` in encoded folder names that are nearly impossible to decipher. Good luck finding the right one. Good luck remembering which folder you were in. Good luck resuming it without manually piecing together the session ID and workspace path.

The built-in `cursor-agent resume` only works for the current directory. If you've moved on, switched projects, or just opened a new terminal — your session history is effectively gone.

**cursor-history** fixes this. It treats your agent sessions as a first-class history — searchable, browsable, and instantly resumable from anywhere.

## What It Does

- **One command to see everything.** Every Cursor Agent session you've ever run, across all projects, sorted by recency, with the first prompt shown so you actually know what each session was about.

- **Instant resume from anywhere.** Select a session and `cursor-history` will `cd` to the original workspace directory and resume the session. No manual path hunting.

- **Full-text search.** Can't remember which session had that database migration discussion? `cursor-history search "migration"` finds it in seconds, ranked by relevance.

- **Usage stats at a glance.** See which projects you use Cursor Agent in the most, your activity over time, and your longest sessions — all in a terminal dashboard.

- **Smart path reconstruction.** Cursor encodes workspace paths by replacing `/` and `.` with `-`. This tool uses a DFS algorithm that tries all possible separator combinations against your actual filesystem to reconstruct the real path. It handles edge cases like dots in usernames and dashes in folder names correctly.

- **Read-only and local.** Nothing leaves your machine. No network calls, no telemetry, no accounts. It reads Cursor's existing transcript files and caches an index locally.

## Installation

### Prerequisites

| Tool | Install |
|------|---------|
| **jq** | `brew install jq` |
| **fzf** | `brew install fzf` |
| **python3** | Pre-installed on macOS |

### Quick Install

```bash
git clone https://github.com/nick-fullpath/cursor-history.git
cd cursor-history
./install.sh --link
```

Then add shell integration to your `~/.zshrc` (or `~/.bashrc`):

```bash
eval "$(cursor-history init zsh)"
```

> **Why shell integration?** A child process can't change your shell's working directory. The shell function wraps `cursor-history` so that `resume` can `cd` to the workspace before launching `cursor-agent`. Without it, the tool prints the commands but you'd need to copy-paste them.

### Manual Install

```bash
cp cursor-history ~/.local/bin/
chmod +x ~/.local/bin/cursor-history
```

## Usage

Run `cursor-history` with no arguments to open the interactive picker:

```
╭──────────────────────── Cursor Agent Sessions ────────────────────────╮
│ Filter >                                                              │
│                                                                       │
│ 2025-03-15 14:22  a1b2c3d4   45 msgs  my-api         debug auth ..   │
│ 2025-03-15 09:10  e5f6a7b8   12 msgs  infra          terraform p..   │
│ 2025-03-14 16:33  c9d0e1f2  120 msgs  frontend       refactor da..   │
│ 2025-03-13 11:05  a3b4c5d6    8 msgs  scripts        write deplo..   │
│ ...                                                                   │
│                                                                       │
│ ┊  Session: a1b2c3d4-5678-9abc-def0-123456789abc                     │
│ ┊  Date:       2025-03-15 14:22                                       │
│ ┊  Workspace:  /home/user/projects/my-api                             │
│ ┊  Messages:   45                                                     │
│ ┊  Tool calls: 38                                                     │
│ ┊  First prompt:                                                      │
│ ┊  debug the authentication middleware, users are getting 401s...      │
╰───────────────────────────────────────────────────────────────────────╯
```

Type to filter. Arrow keys to navigate. **Enter** to resume the selected session.

## Commands

```
cursor-history                  Interactive session picker (default)
cursor-history list [options]   List all sessions
cursor-history search <query>   Full-text search across transcripts
cursor-history resume <id>      Resume a session (partial IDs work)
cursor-history show <id>        Show detailed session info
cursor-history stats            Usage stats dashboard
cursor-history rebuild          Force-rebuild the session index
```

### `cursor-history search <query>`

Search across all session transcripts for a keyword or phrase:

```bash
cursor-history search "database migration"
```

```
Searching for: database migration

5 sessions contain matches:

  2025-03-14 16:33  c9d0e1f2   87 hits  frontend    refactor dashboard components...
  2025-03-10 09:15  f1e2d3c4   23 hits  my-api      add user roles migration...
  2025-03-08 11:42  b5a6c7d8    5 hits  infra       set up staging environment...
  ...
```

Results are ranked by match count. When running interactively, you can select a result to resume it.

### `cursor-history stats`

```
╔══════════════════════════════════════════════════════════════╗
║              cursor-history — Stats Dashboard               ║
╚══════════════════════════════════════════════════════════════╝

  Overview
  ────────────────────────────────────────
  Total sessions:     42
  Total messages:     2,847
  Total tool calls:   1,923
  Transcript size:    3.1M
  Workspaces:         8
  Date range:         2025-01-15 → 2025-03-15

  Sessions by Workspace
  ────────────────────────────────────────
  infra                      18 sessions   980 msgs
  ████████████████████████████████████████
  my-api                     10 sessions   412 msgs
  ██████████████████████
  frontend                    6 sessions   305 msgs
  █████████████
  ...

  Weekly Activity
  ────────────────────────────────────────
  2025-01    8 sessions   ████████
  2025-02   14 sessions   ██████████████
  2025-03   20 sessions   ████████████████████

  Largest Sessions (by messages)
  ────────────────────────────────────────
   320 msgs   580 tools  infra       investigate production outage...
   245 msgs   312 tools  my-api      implement OAuth2 flow...
   120 msgs   156 tools  frontend    refactor dashboard components...
```

### `cursor-history list`

```bash
cursor-history list                  # All sessions (default limit: 50)
cursor-history list -w my-api        # Filter by workspace path
cursor-history list -n 10            # Limit to 10 results
cursor-history list --json           # JSON output for scripting
cursor-history list --json | jq '.[] | select(.messages > 100)'
```

### `cursor-history resume <id>`

Partial session IDs work — you only need enough characters to be unique:

```bash
cursor-history resume a1b2

# Output:
# Resuming session:
#   ID:        a1b2c3d4-5678-9abc-def0-123456789abc
#   Workspace: /home/user/projects/my-api
#   Summary:   debug the authentication middleware...
#
# → cd /home/user/projects/my-api && cursor-agent --resume a1b2c3d4-...
```

With shell integration enabled, this happens automatically — you land in the right directory with the session resumed.

## How It Works

```
~/.cursor/projects/
├── Users-jane-doe-projects-my-api/
│   └── agent-transcripts/
│       ├── a1b2c3d4-5678-9abc-def0-123456789abc.jsonl
│       └── e5f6a7b8-1234-5678-9abc-def012345678.txt
├── Users-jane-doe-projects-infra/
│   └── agent-transcripts/
│       └── ...
└── ...
```

1. **Discovery** — Scans all `agent-transcripts/` directories under `~/.cursor/projects/`.

2. **Path reconstruction** — Cursor encodes `/Users/jane.doe/projects/my-api` as `Users-jane-doe-projects-my-api`, replacing both `/` and `.` with `-`. Since `-` can also be a literal character in folder names, simple string replacement doesn't work. Instead, `cursor-history` uses a DFS algorithm that tries all three possible separators (`/`, `.`, `-`) at each dash boundary and validates against the real filesystem to find the correct path.

3. **Parsing** — Reads both `.jsonl` (structured JSON, newer format) and `.txt` (plain text, older format) transcripts. Extracts the first user prompt as a summary, counts messages and tool calls.

4. **Caching** — Builds a session index at `~/.cursor-history/sessions.json` with a 5-minute TTL. The cache file is created with `0600` permissions since it contains workspace paths and session summaries.

5. **Display** — Pipes the index through `fzf` for interactive selection, or formats it as a table/JSON for non-interactive use.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CURSOR_PROJECTS_DIR` | `~/.cursor/projects` | Where Cursor stores project data |
| `CURSOR_HISTORY_CACHE` | `~/.cursor-history` | Cache directory for the session index |

## Security

- **Read-only** — Never modifies Cursor's transcript files. Only reads them.
- **Local-only** — No network calls. No telemetry. No external services.
- **Restricted cache** — The session index is created with `0600` permissions (owner-only).
- **No eval** — The shell integration validates the resume command against an allowlist pattern before execution.
- **Input validation** — Session IDs are validated as hex/UUID format. Numeric parameters are checked before interpolation into queries.

## Contributing

Contributions welcome! Some ideas for future work:

- [ ] Session tagging and bookmarking
- [ ] Export session to markdown
- [ ] Cursor hooks integration for richer metadata capture
- [ ] Token usage tracking
- [ ] tmux / zellij integration (open session in a new pane)
- [ ] Support for Cursor GUI sessions (not just CLI)
- [ ] Linux support and testing

## License

[MIT](LICENSE)
