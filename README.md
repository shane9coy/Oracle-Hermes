# ✧🔮  Oracle — AI Astrology Companion ✧

![oracle](https://github.com/user-attachments/assets/5ef3a46a-564a-4aaa-9601-4a93194c1168)

Oracle is an AI-powered astrology companion that integrates with Hermes Agent to provide cosmic timing guidance, natal chart analysis, and intelligent calendar management in coherence with astrological knowledge used by history's most powerful figures.

## Features

- **Daily Brief** — Personalized cosmic weather each morning
- **Weekly Outlook** — Best days for launches, relationships, finances
- **Natal Charts** — Full birth chart with planets, houses, aspects
- **Timing Optimizer** — When to launch, sign, post, schedule
- **Tarot Pulls** — Daily cards and spreads
- **Solar Returns** — Year-ahead themes and predictions
- **Numerology** — Life path and personal year numbers
- **Browser Star Map** — Interactive 3D zodiac visualization
- **Calendar Overlay** — Your schedule through the stars

## Quick Start

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/oracle-astro.git
cd oracle-astro

# Run the demo
./demo.sh
```

## Demo Video Script

See `DEMO_SCRIPT.md` for the full walkthrough.

## Architecture

```
oracle-astro/
├── SKILL.md              # Hermes skill definition
├── SOUL.md               # Voice/personality
├── scripts/              # Core Python modules
│   ├── oracle_utils.py   # API helpers, caching
│   ├── oracle_astrology.py
│   ├── oracle_digest.py
│   ├── oracle_launcher.py
│   └── oracle_render.py
├── ui/                   # Browser star map
│   ├── oracle_chart.html
│   └── server.py
└── references/          # Documentation
```

## Requirements

- Hermes Agent (latest)
- Python 3.9+

## Setup

1. **Configure Oracle:**
   ```bash
   # Ephemeris API (ephemeris.fyi) requires no authentication
   ```
2. **Run Oracle:**
   ```
   /oracle
   ```

## Commands

```
/oracle              # Open Oracle
/oracle daily       # Get today's brief
/oracle weekly     # Get weekly outlook
/oracle natal      # View natal chart
/oracle tarot      # Pull a card
/oracle timing     # Ask "when should I launch?"
```

## Browser Star Map

```bash
cd ui && python server.py
# Open http://localhost:8081
```

## Tech Stack

- **Hermes Agent** — AI agent framework
- **Ephemeris API** (ephemeris.fyi) — Planetary and astrological data
- **Three.js** — 3D browser visualization

## License

MIT

---

*Built for the Nous Research Hermes Hackathon 2026*
