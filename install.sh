#!/usr/bin/env bash
# ╔════════════════════════════════════════════════════════════════════════════╗
# ║  cursor-history — Local installer                                        ║
# ║                                                                          ║
# ║  Installs the cursor-history CLI and its Python indexer library to       ║
# ║  ~/.local/bin (or $INSTALL_DIR if overridden).                           ║
# ║                                                                          ║
# ║  Usage:                                                                  ║
# ║    ./install.sh           Copy files to ~/.local/bin                     ║
# ║    ./install.sh --link    Symlink instead (useful for development —      ║
# ║                           changes to the source are picked up instantly) ║
# ║                                                                          ║
# ║  Layout after install:                                                   ║
# ║    ~/.local/bin/cursor-history              (main CLI script)            ║
# ║    ~/.local/lib/cursor-history/*.py          (Python modules)             ║
# ╚════════════════════════════════════════════════════════════════════════════╝
set -euo pipefail

BOLD='\033[1m'
GREEN='\033[32m'
CYAN='\033[36m'
YELLOW='\033[33m'
RED='\033[31m'
RESET='\033[0m'

INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
LIB_DIR="${INSTALL_DIR}/../lib/cursor-history"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo -e "${BOLD}cursor-history installer${RESET}"
echo ""

# Verify all required dependencies are available
for cmd in jq fzf python3 bc; do
  if command -v "$cmd" &>/dev/null; then
    echo -e "  ${GREEN}✓${RESET} $cmd found"
  else
    echo -e "  ${RED}✗${RESET} $cmd not found — install with: brew install $cmd"
    exit 1
  fi
done

echo ""

mkdir -p "$INSTALL_DIR" "$LIB_DIR"

PY_MODULES=(indexer.py paths.py transcript.py models.py __init__.py)

if [[ "${1:-}" == "--link" ]]; then
  ln -sf "$SCRIPT_DIR/cursor-history" "$INSTALL_DIR/cursor-history"
  for mod in "${PY_MODULES[@]}"; do
    ln -sf "$SCRIPT_DIR/lib/$mod" "$LIB_DIR/$mod"
  done
  echo -e "${GREEN}Symlinked${RESET} cursor-history → $SCRIPT_DIR/cursor-history"
else
  cp "$SCRIPT_DIR/cursor-history" "$INSTALL_DIR/cursor-history"
  chmod +x "$INSTALL_DIR/cursor-history"
  for mod in "${PY_MODULES[@]}"; do
    cp "$SCRIPT_DIR/lib/$mod" "$LIB_DIR/$mod"
  done
  echo -e "${GREEN}Installed${RESET} cursor-history to $INSTALL_DIR/"
fi

# Warn if the install directory isn't in PATH
if ! echo "$PATH" | tr ':' '\n' | grep -q "^${INSTALL_DIR}$"; then
  echo ""
  echo -e "${YELLOW}Warning:${RESET} $INSTALL_DIR is not in your PATH."
  echo "  Add this to your ~/.zshrc:"
  echo ""
  echo "    export PATH=\"$INSTALL_DIR:\$PATH\""
fi

echo ""
echo -e "${BOLD}Shell integration (recommended):${RESET}"
echo ""
echo "  Add this to your ~/.zshrc to enable workspace-aware resume:"
echo ""
echo -e "    ${CYAN}eval \"\$(cursor-history init zsh)\"${RESET}"
echo ""
echo -e "${GREEN}Done!${RESET} Run ${BOLD}cursor-history${RESET} to get started."
echo ""
