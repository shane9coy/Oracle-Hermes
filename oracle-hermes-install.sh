#!/bin/bash
# =============================================================================
# HERMES AUTO-INSTALL: ORACLE
# =============================================================================
# This script is designed to be run BY Hermes to auto-install Oracle.
# 
# For Users:
#   1. Download the oracle-hackathon-demo folder
#   2. Copy the skill files to Hermes
#   3. Configure your profile
#
# For Hermes Auto-Install:
#   1. User runs: bash ~/Downloads/oracle-hermes-install.sh
#   2. This script copies files and sets everything up
# =============================================================================

set -e

echo "🔮 Installing Oracle into Hermes..."

# Detect HERMES_HOME
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

# Source Hermes if available (for path detection)
if [ -f "$HERMES_HOME/activate.sh" ]; then
    source "$HERMES_HOME/activate.sh" 2>/dev/null || true
fi

# Target directories
ORACLE_DIR="$HERMES_HOME/oracle"
SKILLS_DIR="$HERMES_HOME/skills/oracle"

echo "  Target: $HERMES_HOME"

# Create directories
mkdir -p "$ORACLE_DIR"/{profiles/user/{cache,reports,journal},defaults,cache}

# Copy skill files
echo "  Copying skill files..."
if [ -d "./oracle-astro/skills/oracle" ]; then
    cp -r ./oracle-astro/skills/oracle "$SKILLS_DIR"
elif [ -d "./skills/oracle" ]; then
    cp -r ./skills/oracle "$SKILLS_DIR"
else
    echo "  ⚠ Skill files not found - please copy manually"
fi

# Copy config files
echo "  Setting up config..."

# .env
if [ ! -f "$ORACLE_DIR/.env" ]; then
    cat > "$ORACLE_DIR/.env" << 'EOF'
ASTROVISOR_TOKEN=pk-usr-YOUR_TOKEN
ASTROVISOR_BASE_URL=https://astrovisor.io
ASTROVISOR_TIMEOUT=60
EOF
fi

# Default consent
if [ ! -f "$ORACLE_DIR/defaults/consent.yaml" ]; then
    cat > "$ORACLE_DIR/defaults/consent.yaml" << 'EOF'
consent_version: 2
use_hermes_google_default: true
gmail_read: true
calendar_read: true
astrovisor_natal: true
astrovisor_transits: true
EOF
fi

# Profiles registry
if [ ! -f "$ORACLE_DIR/profiles.json" ]; then
    cat > "$ORACLE_DIR/profiles.json" << 'EOF'
{"version":1,"active_profile_id":"user","profiles":[]}
EOF
fi

echo "  ✓ Oracle installed!"
echo ""
echo "To use Oracle, type: /oracle"
echo "Get a free API key at: https://astrovisor.io"
