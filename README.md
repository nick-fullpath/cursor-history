# cursor-history

Session management for the Cursor Agent CLI. Browse, search, and resume past sessions across all workspaces from a single interface.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Overview

Cursor Agent CLI stores session transcripts under `~/.cursor/projects/`, but provides no unified way to access them. The built-in `resume` command is scoped to the current working directory, and the transcript folder names use an encoded format that obscures the original workspace path.

`cursor-history` indexes all sessions across every workspace, reconstructs the original directory paths, and provides an interactive terminal UI for browsing, searching, and resuming any past session.

### Key capabilities

- **Unified session index** across all workspaces, with automatic prompt extraction for context
- **Interactive picker** powered by `fzf` with live session preview
- **Full-text search** across transcript content, ranked by relevance
- **Workspace-aware resume** that restores both the working directory and the agent session
- **Token usage tracking** with estimated input/output token counts per session and in aggregate
- **Model attribution** pulled from Cursor's tracking database, showing which model was used per session
- **Usage analytics** with per-workspace breakdowns, model usage, and activity timelines
- **Terminal tab titles** automatically set to the session context on resume and during browsing
- **Filesystem path reconstruction** using DFS-based resolution of Cursor's encoded folder names

All operations are read-only and local. No data leaves your machine.

## Installation

### Homebrew

```bash
brew tap nick-fullpath/tap
brew install cursor-history
```

To upgrade to the latest version:

```bash
brew update
brew upgrade cursor-history
```

If `brew upgrade` shows "already installed", force a fresh pull of the tap:

```bash
brew untap nick-fullpath/tap && brew tap nick-fullpath/tap
brew upgrade cursor-history
```

### Script

```bash
curl -fsSL https://raw.githubusercontent.com/nick-fullpath/cursor-history/main/install-remote.sh | bash
```

Re-run the same command to upgrade — it overwrites the existing binary.

### Manual

```bash
git clone https://github.com/nick-fullpath/cursor-history.git
cd cursor-history
./install.sh           # install to ~/.local/bin
./install.sh --link    # symlink instead (useful for development)
```

To upgrade a manual install, `git pull` and re-run `./install.sh` (or if you used `--link`, the symlink picks up changes automatically).

### Dependencies

`jq`, `fzf`, and `python3`. The Homebrew formula handles these automatically. For other install methods:

```bash
brew install jq fzf python3
```

### Shell integration

Required for workspace-aware resume (the tool needs to `cd` in your shell before launching `cursor-agent`):

```bash
# Add to ~/.zshrc or ~/.bashrc
eval "$(cursor-history init zsh)"
```

## Usage

### Interactive mode

```bash
cursor-history
```

```
╭──────────────────────── Cursor Agent Sessions ────────────────────────╮
│ Filter >                                                              │
│                                                                       │
│ 2025-03-15 14:22  a1b2c3d4   45 msgs  my-api         debug auth ..   │
│ 2025-03-15 09:10  e5f6a7b8   12 msgs  infra          terraform p..   │
│ 2025-03-14 16:33  c9d0e1f2  120 msgs  frontend       refactor da..   │
│ 2025-03-13 11:05  a3b4c5d6    8 msgs  scripts        write deplo..   │
│                                                                       │
│ ┊  Session: a1b2c3d4-5678-9abc-def0-123456789abc                     │
│ ┊  Workspace:  /home/user/projects/my-api                             │
│ ┊  Messages:   45                                                     │
│ ┊  Tool calls: 38                                                     │
│ ┊  First prompt:                                                      │
│ ┊  debug the authentication middleware, users are getting 401s...      │
╰───────────────────────────────────────────────────────────────────────╯
```

### Commands

| Command | Description |
|---------|-------------|
| `cursor-history` | Interactive session picker |
| `cursor-history list` | List sessions (`-w <path>`, `-n <limit>`, `--json`) |
| `cursor-history search <query>` | Full-text search across all transcripts |
| `cursor-history resume <id>` | Resume a session by full or partial ID |
| `cursor-history show <id>` | Display session details |
| `cursor-history stats` | Usage statistics dashboard |
| `cursor-history rebuild` | Force-rebuild the session index |

### Search

```bash
cursor-history search "database migration"
```

```
Searching for: database migration

5 sessions contain matches:

  2025-03-14 16:33  c9d0e1f2   87 hits  frontend    refactor dashboard components...
  2025-03-10 09:15  f1e2d3c4   23 hits  my-api      add user roles migration...
  2025-03-08 11:42  b5a6c7d8    5 hits  infra       set up staging environment...
```

### Stats

```bash
cursor-history stats
```

```
╔══════════════════════════════════════════════════════════════╗
║              cursor-history — Stats Dashboard               ║
╚══════════════════════════════════════════════════════════════╝

  Overview
  ────────────────────────────────────────
  Total sessions:     42
  Total messages:     2,847
  Total tool calls:   1,923
  Tokens (est.):      ~967.0k (in: ~143.5k, out: ~823.5k)
  Code edits:         4,210
  Transcript size:    3.1M
  Workspaces:         8

  Models Used
  ────────────────────────────────────────
  claude-4.6-opus-high                       7 sessions  ~38.3k tokens
  claude-4.5-opus-high-thinking              2 sessions  ~30.2k tokens

  Sessions by Workspace
  ────────────────────────────────────────
  infra                      18 sessions   980 msgs
  ████████████████████████████████████████
  my-api                     10 sessions   412 msgs
  ██████████████████████
  frontend                    6 sessions   305 msgs
  █████████████

  Weekly Activity
  ────────────────────────────────────────
  2025-01    8 sessions   ████████
  2025-02   14 sessions   ██████████████
  2025-03   20 sessions   ████████████████████

  Largest Sessions (by messages)
  ────────────────────────────────────────
   320 msgs   580 tools  ~334.1k tok  infra       investigate production outage...
   245 msgs   312 tools   ~87.6k tok  my-api      implement OAuth2 flow...
   120 msgs   156 tools   ~13.1k tok  frontend    refactor dashboard components...
```

### Resume

Partial session IDs are supported:

```bash
cursor-history resume a1b2
```

With shell integration enabled, this changes to the original workspace directory and launches `cursor-agent --resume` automatically.

### List

```bash
cursor-history list                  # all sessions (limit: 50)
cursor-history list -w my-api        # filter by workspace
cursor-history list -n 10            # limit results
cursor-history list --json           # structured output
```

## How it works

Cursor encodes workspace paths by replacing `/` and `.` with `-` in the project folder name. For example, `/Users/jane.doe/projects/my-api` becomes `Users-jane-doe-projects-my-api`. Since `-` can also appear as a literal character in directory names, naive string replacement is insufficient.

`cursor-history` resolves this with a DFS algorithm that evaluates all possible separator assignments (`/`, `.`, `-`) at each dash boundary and validates candidates against the actual filesystem.

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

**Pipeline:**

1. **Discovery** — Scan `agent-transcripts/` directories under `~/.cursor/projects/`
2. **Path resolution** — Reconstruct workspace paths via filesystem-validated DFS
3. **Parsing** — Extract prompts, message/tool counts, and estimate token usage from `.jsonl` and `.txt` transcripts
4. **Model attribution** — Pull model name and code-edit counts from Cursor's tracking database (`ai-code-tracking.db`)
5. **Indexing** — Cache results at `~/.cursor-history/sessions.json` (`0600` permissions, invalidated when transcript directories change)
6. **Presentation** — Render via `fzf` for interactive use, or as JSON/table for scripting

**Project structure:**

```
cursor-history/
├── cursor-history       # Main CLI script (bash)
├── lib/
│   └── indexer.py       # Session indexer (Python) — parsing, path resolution, token estimation
├── install.sh           # Local installer
├── install-remote.sh    # curl | bash installer
└── README.md
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CURSOR_PROJECTS_DIR` | `~/.cursor/projects` | Cursor project data directory |
| `CURSOR_HISTORY_CACHE` | `~/.cursor-history` | Index cache directory |

## Security

- **Read-only** — transcript files are never modified
- **Local-only** — no network calls, telemetry, or external services
- **Restricted permissions** — cache files are created with `0600`
- **Command validation** — shell integration validates resume commands against an allowlist regex before execution
- **Input sanitization** — session IDs are validated as hex/UUID; numeric parameters are checked before query interpolation
- **AppleScript escaping** — session summaries and paths are sanitized before embedding in AppleScript strings to prevent injection

## Contributing

Contributions are welcome. Areas of interest:

- Session tagging and bookmarking
- Markdown export
- Cursor hooks integration for richer metadata
- Cost estimation based on model and token counts
- tmux/zellij pane integration
- Cursor GUI session support
- Linux testing

## License

[MIT](LICENSE)
