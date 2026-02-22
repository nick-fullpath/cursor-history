#!/usr/bin/env bash
# Remote installer for cursor-history
# Usage: curl -fsSL https://raw.githubusercontent.com/nick-fullpath/cursor-history/main/install-remote.sh | bash
set -euo pipefail

REPO="nick-fullpath/cursor-history"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"

BOLD='\033[1m'
GREEN='\033[32m'
CYAN='\033[36m'
YELLOW='\033[33m'
RED='\033[31m'
RESET='\033[0m'

echo ""
echo -e "${BOLD}cursor-history${RESET} — installer"
echo ""

# Check dependencies
missing=()
for cmd in jq fzf python3; do
  if command -v "$cmd" &>/dev/null; then
    echo -e "  ${GREEN}✓${RESET} $cmd"
  else
    echo -e "  ${RED}✗${RESET} $cmd"
    missing+=("$cmd")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo ""
  echo -e "${RED}Missing dependencies:${RESET} ${missing[*]}"
  echo "  Install with: brew install ${missing[*]}"
  exit 1
fi

echo ""

mkdir -p "$INSTALL_DIR"

echo -e "Downloading cursor-history..."
curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/cursor-history" -o "${INSTALL_DIR}/cursor-history"
chmod +x "${INSTALL_DIR}/cursor-history"

echo -e "${GREEN}Installed${RESET} to ${INSTALL_DIR}/cursor-history"

if ! echo "$PATH" | tr ':' '\n' | grep -q "^${INSTALL_DIR}$"; then
  echo ""
  echo -e "${YELLOW}Note:${RESET} ${INSTALL_DIR} is not in your PATH."
  echo "  Add to your ~/.zshrc:"
  echo ""
  echo "    export PATH=\"${INSTALL_DIR}:\$PATH\""
fi

echo ""
echo -e "${BOLD}Shell integration (recommended):${RESET}"
echo "  Add to your ~/.zshrc:"
echo ""
echo -e "    ${CYAN}eval \"\$(cursor-history init zsh)\"${RESET}"
echo ""
echo -e "${GREEN}Done!${RESET} Run ${BOLD}cursor-history${RESET} to get started."
echo ""
