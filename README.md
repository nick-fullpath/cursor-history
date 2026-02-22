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

The session data is still there, buried inside `~/.cursor/projects/` in encoded folder names that look like `Users-nick-kaplan-autoleadstar-devops`. Good luck finding the right one. Good luck remembering which folder you were in. Good luck resuming it without manually piecing together the session ID and workspace path.

The built-in `cursor-agent resume` only works for the current directory. If you've moved on, switched projects, or just opened a new terminal — your session history is effectively gone.

**cursor-history** fixes this. It treats your agent sessions as a first-class history — searchable, browsable, and instantly resumable from anywhere.

## What It Does

- **One command to see everything.** Every Cursor Agent session you've ever run, across all projects, sorted by recency, with the first prompt shown so you actually know what each session was about.

- **Instant resume from anywhere.** Select a session and `cursor-history` will `cd` to the original workspace directory and resume the session. No manual path hunting.

- **Full-text search.** Can't remember which session had that Kubernetes debugging? `cursor-history search "kubectl"` finds it in seconds, ranked by relevance.

- **Usage stats at a glance.** See which projects you use Cursor Agent in the most, your activity over time, and your longest sessions — all in a terminal dashboard.

- **Smart path reconstruction.** Cursor encodes workspace paths by replacing `/` and `.` with `-`. This tool uses a DFS algorithm that tries all possible separator combinations against your actual filesystem to reconstruct the real path. It handles edge cases like `nick.kaplan` (dot in username) and `business-engineers` (dash in folder name) correctly.

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
│ 2026-02-22 09:34  f0f201f3   31 msgs  nick.kaplan    create a tool.. │
│ 2026-02-21 09:42  8e6f61d5   75 msgs  mcp            aws cli and ..  │
│ 2026-02-19 16:13  f3d1bb9a  120 msgs  devops          datadog cust.. │
│ 2026-02-15 14:09  49dc6373   12 msgs  autoleadstar    investigate ..  │
│ ...                                                                   │
│                                                                       │
│ ┊  Session: f3d1bb9a-7993-446c-8c9a-2658a29e07ac                     │
│ ┊  Date:       2026-02-19 16:13                                       │
│ ┊  Workspace:  /Users/nick.kaplan/autoleadstar/devops                 │
│ ┊  Messages:   120                                                    │
│ ┊  Tool calls: 0                                                      │
│ ┊  First prompt:                                                      │
│ ┊  please use my aws cli, kubectl and pup to investigate...           │
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
cursor-history search "RDS backup"
```

```
Searching for: RDS backup

8 sessions contain matches:

  2026-01-25 07:04  96307ff4  2999 hits  devops     reduce datadog cost...
  2026-02-03 12:51  d744b9f5   221 hits  devops     read this summary of the previous...
  2026-02-19 16:13  f3d1bb9a    43 hits  devops     aws cli, kubectl and pup...
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
  Total sessions:     54
  Total messages:     3,554
  Total tool calls:   3,726
  Transcript size:    3.8M
  Workspaces:         9
  Date range:         2026-01-21 → 2026-02-22

  Sessions by Workspace
  ────────────────────────────────────────
  devops                     24 sessions  1378 msgs
  ████████████████████████████████████████
  nick.kaplan                16 sessions   516 msgs
  ████████████████████████████████
  mcp                         4 sessions   138 msgs
  ████████
  ...

  Weekly Activity
  ────────────────────────────────────────
  2026-01    13 sessions  █████████████
  2026-02    41 sessions  ████████████████████████████████████████

  Largest Sessions (by messages)
  ────────────────────────────────────────
   640 msgs  1279 tools  devops     reduce datadog cost...
   405 msgs   433 tools  mcp-lambda read MCP_AGENTCORE_GATEWAY...
   355 msgs   293 tools  mcp-lambda please take it from here
```

### `cursor-history list`

```bash
cursor-history list                  # All sessions (default limit: 50)
cursor-history list -w devops        # Filter by workspace path
cursor-history list -n 10            # Limit to 10 results
cursor-history list --json           # JSON output for scripting
cursor-history list --json | jq '.[] | select(.messages > 100)'
```

### `cursor-history resume <id>`

Partial session IDs work — you only need enough characters to be unique:

```bash
cursor-history resume f3d1

# Output:
# Resuming session:
#   ID:        f3d1bb9a-7993-446c-8c9a-2658a29e07ac
#   Workspace: /Users/nick.kaplan/autoleadstar/devops
#   Summary:   please use my aws cli, kubectl and pup...
#
# → cd /Users/nick.kaplan/autoleadstar/devops && cursor-agent --resume f3d1bb9a-...
```

With shell integration enabled, this happens automatically — you land in the right directory with the session resumed.

## How It Works

```
~/.cursor/projects/
├── Users-nick-kaplan-autoleadstar-devops/
│   └── agent-transcripts/
│       ├── f3d1bb9a-7993-446c-8c9a-2658a29e07ac.jsonl
│       └── 96307ff4-4b33-4514-bcd2-7a59a3414881.txt
├── Users-nick-kaplan-autoleadstar-mcp/
│   └── agent-transcripts/
│       └── ...
└── ...
```

1. **Discovery** — Scans all `agent-transcripts/` directories under `~/.cursor/projects/`.

2. **Path reconstruction** — Cursor encodes `/Users/nick.kaplan/autoleadstar/devops` as `Users-nick-kaplan-autoleadstar-devops`, replacing both `/` and `.` with `-`. Since `-` can also be a literal character in folder names, simple string replacement doesn't work. Instead, `cursor-history` uses a DFS algorithm that tries all three possible separators (`/`, `.`, `-`) at each dash boundary and validates against the real filesystem to find the correct path.

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
