#!/bin/bash
# =============================================================================
# ORACLE SETUP FOR HERMES
# =============================================================================
# Quick setup - copy this folder to your Hermes and run.
#
# 1. Copy this folder to ~/.hermes/oracle-setup/
# 2. Run: bash oracle-setup.sh
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

echo "🔮 Oracle Setup for Hermes"
echo "==========================="
echo ""

# Check Hermes exists
if [ ! -d "$HERMES_HOME" ]; then
    echo "❌ Hermes not found at $HERMES_HOME"
    echo "   Install Hermes first: https://github.com/nousresearch/hermes"
    exit 1
fi

echo "✓ Hermes found at $HERMES_HOME"

# Copy skill
echo ""
echo "[1/4] Installing Oracle skill..."
mkdir -p "$HERMES_HOME/skills"
cp -r "$SCRIPT_DIR/skills/oracle" "$HERMES_HOME/skills/" 2>/dev/null || echo "  (skill files will be added separately)"

# Copy config
echo "[2/4] Setting up Oracle config..."
mkdir -p "$HERMES_HOME/oracle"
cp -f "$SCRIPT_DIR/config/"*.yaml "$HERMES_HOME/oracle/" 2>/dev/null || true
cp -f "$SCRIPT_DIR/config/"*.json "$HERMES_HOME/oracle/" 2>/dev/null || true

# Make scripts executable
echo "[3/4] Setting permissions..."
chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true

# Done
echo "[4/4] ✓ Complete!"

echo ""
echo "========================================"
echo "  ✧ ORACLE INSTALLED ✧"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Get free API key: https://astrovisor.io"
echo "  2. Edit: ~/.hermes/oracle/.env"
echo "  3. Update your birth info in profiles.json"
echo "  4. Run: /oracle"
echo ""
echo '"Millionaires study markets, billionaires study the stars"'
