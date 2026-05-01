#!/usr/bin/env bash

set -e

# Configuration
REPO_URL="https://github.com/harsh020/mach.git"
INSTALL_DIR="$HOME/.mach-cli"
BIN_DIR="$HOME/.local/bin"
EXE_NAME="mach"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Installing Mach Execution Ledger...${NC}"

# 1. Check dependencies
if ! command -v git &> /dev/null; then
    echo -e "${RED}Error: git is required but not installed.${NC}"
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 is required but not installed.${NC}"
    exit 1
fi

# 2. Clone or update repository
if [ -d "$INSTALL_DIR" ]; then
    echo "Updating existing installation in $INSTALL_DIR..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    echo "Cloning repository to $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# 3. Setup Virtual Environment
echo "Setting up Python virtual environment..."
python3 -m venv .venv

# 4. Install dependencies
echo "Installing Mach dependencies..."
./.venv/bin/pip install --upgrade pip setuptools wheel quiet
./.venv/bin/pip install -e .

# 5. Create symlink
echo "Creating symlink..."
mkdir -p "$BIN_DIR"
ln -sf "$INSTALL_DIR/.venv/bin/mach" "$BIN_DIR/$EXE_NAME"

# 6. Verify PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo -e "\n${RED}Warning: $BIN_DIR is not in your PATH.${NC}"
    echo -e "To use the 'mach' command, add this line to your ~/.bashrc, ~/.zshrc, or ~/.profile:"
    echo -e "\n    ${GREEN}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}\n"
    echo "After adding it, restart your terminal or run: source ~/.zshrc"
else
    echo -e "\n${GREEN}Success! Mach was installed successfully.${NC}"
    echo -e "You can now run '${BLUE}mach init${NC}' in any repository."
fi
