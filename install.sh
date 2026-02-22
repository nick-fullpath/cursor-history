#!/usr/bin/env bash
# cursor-history installer
set -euo pipefail

BOLD='\033[1m'
GREEN='\033[32m'
CYAN='\033[36m'
YELLOW='\033[33m'
RED='\033[31m'
RESET='\033[0m'

INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo -e "${BOLD}cursor-history installer${RESET}"
echo ""

# Check dependencies
for cmd in jq fzf python3; do
  if command -v "$cmd" &>/dev/null; then
    echo -e "  ${GREEN}✓${RESET} $cmd found"
  else
    echo -e "  ${RED}✗${RESET} $cmd not found — install with: brew install $cmd"
    exit 1
  fi
done

echo ""

# Create install dir
mkdir -p "$INSTALL_DIR"

# Copy or symlink
if [[ "${1:-}" == "--link" ]]; then
  ln -sf "$SCRIPT_DIR/cursor-history" "$INSTALL_DIR/cursor-history"
  echo -e "${GREEN}Symlinked${RESET} $INSTALL_DIR/cursor-history → $SCRIPT_DIR/cursor-history"
else
  cp "$SCRIPT_DIR/cursor-history" "$INSTALL_DIR/cursor-history"
  chmod +x "$INSTALL_DIR/cursor-history"
  echo -e "${GREEN}Installed${RESET} cursor-history to $INSTALL_DIR/cursor-history"
fi

# Check PATH
if ! echo "$PATH" | tr ':' '\n' | grep -q "^${INSTALL_DIR}$"; then
  echo ""
  echo -e "${YELLOW}Warning:${RESET} $INSTALL_DIR is not in your PATH."
  echo "  Add this to your ~/.zshrc:"
  echo ""
  echo "    export PATH=\"$INSTALL_DIR:\$PATH\""
fi

# Shell integration
echo ""
echo -e "${BOLD}Shell integration (recommended):${RESET}"
echo ""
echo "  Add this to your ~/.zshrc to enable 'cd to workspace' on resume:"
echo ""
echo -e "    ${CYAN}eval \"\$(cursor-history init zsh)\"${RESET}"
echo ""
echo -e "${GREEN}Done!${RESET} Run ${BOLD}cursor-history${RESET} to get started."
echo ""
