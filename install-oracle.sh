#!/bin/bash
# =============================================================================
# ORACLE AUTO-INSTALL SCRIPT
# =============================================================================
# Run this script to install Oracle into your Hermes Agent
# 
# Usage:
#   1. Download this script to ~/Downloads/
#   2. Open Hermes
#   3. Run: bash ~/Downloads/install-oracle.sh
#
# =============================================================================

set -e

echo "✨ Installing Oracle - Millionaires study markets, billionaires study stars..."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Paths
HERMES_DIR="$HOME/.hermes"
ORACLE_DIR="$HERMES_DIR/oracle"
SKILLS_DIR="$HERMES_DIR/skills/oracle"

# =============================================================================
# STEP 1: Create Oracle directories
# =============================================================================
echo -e "${GREEN}[1/5]${NC} Creating Oracle directories..."

mkdir -p "$ORACLE_DIR"
mkdir -p "$ORACLE_DIR/profiles/user/cache"
mkdir -p "$ORACLE_DIR/profiles/user/reports"
mkdir -p "$ORACLE_DIR/profiles/user/journal"
mkdir -p "$ORACLE_DIR/defaults"
mkdir -p "$ORACLE_DIR/cache"

# =============================================================================
# STEP 2: Create Oracle skill link
# =============================================================================
echo -e "${GREEN}[2/5]${NC} Linking Oracle skill..."

# Create skills directory if needed
mkdir -p "$HERMES_DIR/skills"

# Link oracle skill (assumes skill is in this repo)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -d "$SCRIPT_DIR/oracle-astro" ]; then
    cp -r "$SCRIPT_DIR/oracle-astro" "$SKILLS_DIR"
elif [ -d "$SCRIPT_DIR/skills/oracle" ]; then
    cp -r "$SCRIPT_DIR/skills/oracle" "$SKILLS_DIR"
else
    echo -e "${YELLOW}[WARNING]${NC} Could not find Oracle skill files. Please copy manually."
fi

# =============================================================================
# STEP 3: Configure API key
# =============================================================================
echo -e "${GREEN}[3/5]${NC} Configuring..."

# Create .env file
cat > "$ORACLE_DIR/.env" << 'EOF'
# Oracle local environment
# Get your free API key from https://astrovisor.io
ASTROVISOR_TOKEN=pk-usr-YOUR_TOKEN_HERE
ASTROVISOR_BASE_URL=https://astrovisor.io
ASTROVISOR_TIMEOUT=60
EOF

# Create default consent
cat > "$ORACLE_DIR/defaults/consent.yaml" << 'EOF'
consent_version: 2
use_hermes_google_default: true
gmail_read: true
gmail_send: false
calendar_read: true
calendar_write: false
store_cached_summaries: true
journal_reflections: true
requires_confirmation_for_external_actions: true
astrovisor_natal: true
astrovisor_transits: true
astrovisor_tarot: true
astrovisor_numerology: true
astrovisor_chakra: true
astrovisor_financial: true
EOF

# =============================================================================
# STEP 4: Create user profile (example)
# =============================================================================
echo -e "${GREEN}[4/5]${NC} Creating profile template..."

cat > "$ORACLE_DIR/profiles/user/profile.json" << 'EOF'
{
  "schema_version": "1.0.0",
  "preferred_name": "YOUR_NAME",
  "timezone": "America/New_York",
  "house_system": "P",
  "birth_chart": {
    "date": "1990-01-01",
    "time": "12:00",
    "time_known": true,
    "location": "Your City, Your State",
    "latitude": 40.7128,
    "longitude": -74.006,
    "timezone": "America/New_York"
  },
  "guidance_preferences": {
    "tone": "warm, mystical, grounded",
    "directness": "medium",
    "ritual_language": true,
    "default_view": "brief",
    "include_reflective_questions": true
  },
  "life_domains": {
    "communication": 0.8,
    "relationships": 0.9,
    "finance": 0.7,
    "creativity": 0.8,
    "rest": 0.5,
    "decisive_action": 0.8,
    "launches": 0.9,
    "health": 0.7,
    "spiritual": 0.6
  }
}
EOF

# Create profiles registry
cat > "$ORACLE_DIR/profiles.json" << 'EOF'
{
  "version": 1,
  "active_profile_id": "user",
  "profiles": [
    {
      "id": "user",
      "name": "YOUR_NAME",
      "profile_path": "profiles/user/profile.json",
      "consent_path": "profiles/user/consent.yaml",
      "created_at": "2026-03-08T12:00:00Z",
      "last_used_at": "2026-03-08T12:00:00Z"
    }
  ]
}
EOF

# Copy consent
cp "$ORACLE_DIR/defaults/consent.yaml" "$ORACLE_DIR/profiles/user/consent.yaml"

# =============================================================================
# STEP 5: Start Oracle!
# =============================================================================
echo -e "${GREEN}[5/5]${NC} Installation complete!"

echo ""
echo -e "${GREEN}✨ ORACLE INSTALLED!${NC}"
echo ""
echo "Next steps:"
echo "  1. Get your free API key: https://astrovisor.io"
echo "  2. Edit: ~/.hermes/oracle/.env"
echo "  3. Update your birth info in: ~/.hermes/oracle/profiles/user/profile.json"
echo "  4. Run: /oracle"
echo ""
echo -e "${YELLOW}Want to start the browser star map?${NC}"
echo "  cd ~/.hermes/skills/oracle/astro-companion/ui && python server.py"
echo ""
echo "✧ Millionaires study markets, billionaires study stars ✧"
