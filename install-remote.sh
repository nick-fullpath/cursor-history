#!/usr/bin/env bash
# ╔════════════════════════════════════════════════════════════════════════════╗
# ║  cursor-history — Remote installer (curl | bash)                         ║
# ║                                                                          ║
# ║  Downloads the latest cursor-history from GitHub and installs it to      ║
# ║  ~/.local/bin. Re-run to upgrade — it overwrites the existing files.     ║
# ║                                                                          ║
# ║  Usage:                                                                  ║
# ║    curl -fsSL https://raw.githubusercontent.com/nick-fullpath/           ║
# ║      cursor-history/main/install-remote.sh | bash                       ║
# ║                                                                          ║
# ║  Layout after install:                                                   ║
# ║    ~/.local/bin/cursor-history              (main CLI script)            ║
# ║    ~/.local/lib/cursor-history/*.py          (Python modules)             ║
# ╚════════════════════════════════════════════════════════════════════════════╝
set -euo pipefail

REPO="nick-fullpath/cursor-history"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
LIB_DIR="${INSTALL_DIR}/../lib/cursor-history"

BOLD='\033[1m'
GREEN='\033[32m'
CYAN='\033[36m'
YELLOW='\033[33m'
RED='\033[31m'
RESET='\033[0m'

echo ""
echo -e "${BOLD}cursor-history${RESET} — installer"
echo ""

# Verify all required dependencies are available
missing=()
for cmd in jq fzf python3 bc; do
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
  case "$(uname)" in
    Darwin)          echo "  Install with: brew install ${missing[*]}" ;;
    Linux|GNU/Linux) echo "  Install with: sudo apt install ${missing[*]}  (or your distro's package manager)" ;;
    MINGW*|MSYS*|CYGWIN*)
                     echo "  Install with: choco install ${missing[*]}  (or winget/scoop)" ;;
    *)               echo "  Please install: ${missing[*]}" ;;
  esac
  exit 1
fi

echo ""

mkdir -p "$INSTALL_DIR" "$LIB_DIR"

echo -e "Downloading cursor-history..."
curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/cursor-history" \
  -o "${INSTALL_DIR}/cursor-history"
chmod +x "${INSTALL_DIR}/cursor-history"

for mod in indexer.py paths.py transcript.py models.py __init__.py; do
  curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/lib/${mod}" \
    -o "${LIB_DIR}/${mod}"
done

echo -e "${GREEN}Installed${RESET} to ${INSTALL_DIR}/cursor-history"

# Detect the user's shell rc file
_shell_rc() {
  if [[ -n "${ZSH_VERSION:-}" ]] || [[ "$SHELL" == */zsh ]]; then
    echo "$HOME/.zshrc"
  else
    echo "$HOME/.bashrc"
  fi
}
RC_FILE="$(_shell_rc)"

# Warn if the install directory isn't in PATH
if ! echo "$PATH" | tr ':' '\n' | grep -q "^${INSTALL_DIR}$"; then
  echo ""
  echo -e "${YELLOW}Note:${RESET} ${INSTALL_DIR} is not in your PATH."
  echo "  Add to your $RC_FILE:"
  echo ""
  echo "    export PATH=\"${INSTALL_DIR}:\$PATH\""
fi

echo ""
echo -e "${BOLD}Shell integration (recommended):${RESET}"
echo "  Add to your $RC_FILE:"
echo ""
echo -e "    ${CYAN}eval \"\$(cursor-history init zsh)\"${RESET}"
echo ""
echo -e "${GREEN}Done!${RESET} Run ${BOLD}cursor-history${RESET} to get started."
echo ""
