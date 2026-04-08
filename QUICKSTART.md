# ✧ Oracle — Quick Start Guide

## The One-Command Install

```bash
# Copy this folder to your Hermes
cp -r oracle-hackathon-demo ~/.hermes/

# Run setup
cd ~/.hermes/oracle-hackathon-demo
bash setup-oracle.sh
```

## Manual Install (If Above Doesn't Work)

```bash
# 1. Copy skill
cp -r oracle-astro/skills/oracle ~/.hermes/skills/

# 2. Create config
mkdir -p ~/.hermes/oracle
# Ephemeris API (ephemeris.fyi) requires no authentication
touch ~/.hermes/oracle/.env

# 3. Run Oracle
/oracle
```

## Starting the Browser Star Map

```bash
cd ~/.hermes/skills/oracle/astro-companion/ui
python server.py
# Open http://localhost:8081
```

## Demo Commands

```bash
/oracle              # Open Oracle
/oracle daily       # Today's cosmic weather
/oracle weekly     # Best days this week
/oracle tarot      # Pull a card
/oracle natal      # View birth chart
```

## Get Help

- Ephemeris API: https://ephemeris.fyi
- Hermes Agent: https://github.com/nousresearch/hermes
- This repo: https://github.com/YOUR_USERNAME/oracle-astro

---

*"Millionaires study markets, billionaires study stars"*
