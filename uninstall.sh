#!/usr/bin/env bash

set -e

INSTALL_DIR="$HOME/.mach"
BIN_DIR="$HOME/.local/bin"
EXE_NAME="mach"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Uninstalling Mach...${NC}"

# Remove executable
if [ -f "$BIN_DIR/$EXE_NAME" ]; then
    rm "$BIN_DIR/$EXE_NAME"
fi

# We purposefully do NOT delete ~/.mach entirely because it contains user's logs
# We only delete the source code if they installed via the install script
if [ -d "$INSTALL_DIR/.git" ]; then
    rm -rf "$INSTALL_DIR/.git"
    rm -rf "$INSTALL_DIR/src"
    rm -f "$INSTALL_DIR/pyproject.toml"
    rm -f "$INSTALL_DIR/README.md"
    rm -f "$INSTALL_DIR/install.sh"
    rm -f "$INSTALL_DIR/uninstall.sh"
fi

echo -e "\n${GREEN}Mach has been uninstalled.${NC}"
echo -e "Note: Your local database and logs in .mach directories were safely preserved."
