#!/usr/bin/env bash

set -e

# Configuration
INSTALL_DIR="$HOME/.mach-cli"
BIN_DIR="$HOME/.local/bin"
EXE_NAME="mach"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Uninstalling Mach Execution Ledger...${NC}"

# 1. Remove the symlink
if [ -L "$BIN_DIR/$EXE_NAME" ]; then
    echo "Removing executable symlink from $BIN_DIR/$EXE_NAME..."
    rm "$BIN_DIR/$EXE_NAME"
elif [ -e "$BIN_DIR/$EXE_NAME" ]; then
    echo -e "${RED}Warning: $BIN_DIR/$EXE_NAME exists but is not a symlink. Skipping removal to be safe.${NC}"
fi

# 2. Remove the installation directory
if [ -d "$INSTALL_DIR" ]; then
    echo "Removing installation directory $INSTALL_DIR..."
    rm -rf "$INSTALL_DIR"
else
    echo "Installation directory $INSTALL_DIR not found. It may have already been removed."
fi

# Note: We intentionally do NOT remove user data in ~/.mach or inside repositories.
# This ensures that uninstalling the CLI doesn't wipe out their valuable execution logs.

echo -e "\n${GREEN}Success! Mach was uninstalled successfully.${NC}"
echo "Note: Your existing execution logs in .mach/ directories were kept intact."
