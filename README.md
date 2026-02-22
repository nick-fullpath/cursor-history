# cursor-history

Browse, search, and resume your Cursor Agent CLI sessions from the terminal.

![License](https://img.shields.io/badge/license-MIT-blue.svg)

## Why?

The Cursor Agent CLI stores session transcripts in `~/.cursor/projects/`, but there's no easy way to:

- **See all your past sessions** across every project
- **Search** through session content to find that one conversation
- **Resume a session** from the right workspace directory
- **Get stats** on your Cursor usage

`cursor-history` solves all of that with a fast, interactive TUI.

## Features

- **Interactive picker** — fzf-powered session browser with live preview
- **Session summaries** — extracts the first prompt from each session
- **Full-text search** — find sessions by content (`cursor-history search "kubernetes"`)
- **Stats dashboard** — sessions per project, activity timeline, largest sessions
- **Smart resume** — `cd`s to the original workspace and resumes the session
- **Path reconstruction** — maps Cursor's encoded folder names back to real paths
- **Both formats** — supports `.jsonl` and `.txt` transcript formats
- **Fast caching** — indexes sessions once, refreshes every 5 minutes

## Quick Start

```bash
# Clone and install
git clone https://github.com/nick-fullpath/cursor-history.git
cd cursor-history
./install.sh --link

# Add shell integration to ~/.zshrc
eval "$(cursor-history init zsh)"

# Launch the interactive picker
cursor-history
```

## Usage

```
cursor-history                  Interactive session picker (default)
cursor-history list [options]   List all sessions
cursor-history search <query>   Full-text search across sessions
cursor-history resume <id>      Resume a session by ID (partial IDs work)
cursor-history show <id>        Show session details
cursor-history stats            Stats dashboard
cursor-history rebuild          Force-rebuild session index
```

### Interactive Picker

Just run `cursor-history` with no arguments:

```
╭─────────────── Cursor Agent Sessions ───────────────╮
│ Filter >                                             │
│                                                      │
│ 2026-02-19 16:13  f3d1bb9a  120 msgs  devops    ... │
│ 2026-02-19 10:37  55294735    4 msgs  ~         ... │
│ 2026-02-16 20:55  7c905c3a    8 msgs  ~         ... │
│ 2026-02-15 12:52  e420bd7f   18 msgs  devops    ... │
│ ...                                                  │
╰──────────────────────────────────────────────────────╯
```

Type to filter. Press Enter to resume. The preview pane shows full session details.

### Search

Find sessions containing specific terms:

```bash
cursor-history search "kubernetes"
cursor-history search "RDS backup"
cursor-history search "datadog"
```

Results show match counts and offer interactive selection.

### Stats Dashboard

```bash
cursor-history stats
```

```
╔══════════════════════════════════════════════════════════════╗
║              cursor-history — Stats Dashboard               ║
╚══════════════════════════════════════════════════════════════╝

  Overview
  ────────────────────────────────────────
  Total sessions:     54
  Total messages:     1,247
  Total tool calls:   892
  Transcript size:    2.1M
  Workspaces:         12
  Date range:         2025-08-27 → 2026-02-22

  Sessions by Workspace
  ────────────────────────────────────────
  devops                     24 sessions   580 msgs  2026-02-19
  ████████████████████████████████████████████████
  mcp                         4 sessions    42 msgs  2026-02-20
  ████████
  ...
```

### List

```bash
# List all sessions
cursor-history list

# Filter by workspace
cursor-history list -w devops

# JSON output (for scripting)
cursor-history list --json

# Limit results
cursor-history list -n 10
```

### Resume

```bash
# Resume by full or partial session ID
cursor-history resume f3d1bb9a

# With shell integration, this will:
# 1. cd to /Users/you/autoleadstar/devops
# 2. Run: cursor-agent --resume f3d1bb9a-7993-446c-8c9a-2658a29e07ac
```

## Shell Integration

Add to your `~/.zshrc` (or `~/.bashrc`):

```bash
eval "$(cursor-history init zsh)"
```

This wraps `cursor-history` in a shell function that can `cd` to the workspace directory before resuming a session. Without it, the tool will print the commands but can't change your shell's working directory.

## Installation

### Prerequisites

- **jq** — `brew install jq`
- **fzf** — `brew install fzf`
- **python3** — typically pre-installed on macOS

### Install

```bash
git clone https://github.com/nick-fullpath/cursor-history.git
cd cursor-history

# Option A: Symlink (for development — edits take effect immediately)
./install.sh --link

# Option B: Copy to ~/.local/bin
./install.sh
```

### Manual Install

```bash
cp cursor-history ~/.local/bin/cursor-history
chmod +x ~/.local/bin/cursor-history
```

## Configuration

Environment variables:

| Variable | Default | Description |
|---|---|---|
| `CURSOR_PROJECTS_DIR` | `~/.cursor/projects` | Where Cursor stores project data |
| `CURSOR_HISTORY_CACHE` | `~/.cursor-history` | Cache directory for the session index |

## How It Works

1. **Discovery** — Scans `~/.cursor/projects/*/agent-transcripts/` for `.jsonl` and `.txt` files
2. **Path mapping** — Reconstructs real filesystem paths from Cursor's encoded folder names (e.g., `Users-nick-kaplan-devops` → `/Users/nick.kaplan/devops`) using greedy filesystem matching
3. **Parsing** — Extracts first prompt, message count, tool call count from each transcript
4. **Caching** — Stores the index at `~/.cursor-history/sessions.json` (5-minute TTL)
5. **Display** — Renders an interactive fzf picker with live preview, or structured list output

## Contributing

Contributions welcome! Some ideas:

- [ ] Session tagging / bookmarking
- [ ] Export session to markdown
- [ ] Hooks integration for auto-logging
- [ ] Token usage tracking
- [ ] tmux/zellij integration (open in new pane)
- [ ] Support for Cursor GUI sessions (not just CLI)

## License

MIT
