---
name: astro-companion
description: "Millionaires study markets, billionaires study stars" - AI astrology companion with timing guidance, natal analysis, and cosmic calendar integration.
aliases:
  - oracle
triggers: "oracle, astrology, horoscope, birth chart, moon phase, mercury retrograde, transits, timing, cosmic, planetary, sign, rising, synastry, solar return, zodiac, natal, celestial, vibe, alignment, conjunction, retrograde, when should I, best day, best time, schedule around, tarot, numerology, chakra, harmonic"
---

# Astro Companion — Operating Skill

Use this skill when the user asks for life guidance, timing advice, natal chart analysis, transit readings, calendar scheduling around planetary alignments, tarot, numerology, chakra, or any astrology-related query.

---

## 1. Runtime Paths

| What | Path |
|------|------|
| Oracle env file | `~/.hermes/oracle/.env` |
| Profiles registry | `~/.hermes/oracle/profiles.json` |
| Per-user profile | `~/.hermes/oracle/profiles/<id>/profile.json` |
| Per-user consent | `~/.hermes/oracle/profiles/<id>/consent.yaml` |
| Browser star map | `~/.hermes/skills/oracle/astro-companion/ui/oracle_chart.html` |

---

## 2. Startup Rules

On Oracle entry:
1. Load `~/.hermes/oracle/profiles.json` 
2. Get active profile
3. **Use cached data if available** - never fetch from API if data is already cached
4. Offer menu options

---

## 3. Caching (CRITICAL)

**All Astrovisor data is cached. natal-mcp is preferred for transits (local, free).**

### Cache Locations

| Data Type | Location | TTL |
|-----------|----------|-----|
| Full natal data | `profiles.json` | Forever |
| Transits | `profiles/<id>/cache/transits_YYYY-MM-DD.json` | 1 hour |
| Solar returns | `profiles.json` | 1 year |
| Numerology | `profiles.json` | 1 year |
| Tarot | No cache (different each pull) | - |

### Cache Precedence

1. **Check cache first** - never hit API if data exists
2. **Use natal-mcp** for transits (local, no API cost)
3. **Astrovisor** for everything else

```python
# Transits use cache + natal-mcp
get_transits_with_cache(datetime, lat, lon, location, tz)

# Other data uses profiles.json cache
cached_data = profiles['profiles'][0]['cached_data']
```

---

## 4. Astrovisor API Endpoints

Base URL: `https://astrovisor.io`
Token: from `~/.hermes/oracle/.env` (ASTROVISOR_TOKEN)

### Natal & Core

| Endpoint | Purpose |
|----------|---------|
| `POST /api/natal/chart` | Full natal chart (planets, houses, aspects, analysis) |
| `POST /api/natal/aspects` | Major aspects between planets |
| `POST /api/minor-aspects/calculate` | Minor aspects (quintile, septile, etc.) |
| `POST /api/harmonics/calculate` | Harmonic charts reveal hidden patterns |

### Solar Returns & Predictions

| Endpoint | Purpose |
|----------|---------|
| `POST /api/solar/return` | Solar return for a year |
| `POST /api/solar/all-planetary-returns` | Saturn, Jupiter, etc returns |
| `POST /api/solar/profections` | Annual house profections |
| `POST /api/solar/lunations-overlay` | New/Full Moons mapped to SR houses |
| `POST /api/calendar/generate` | Daily predictions (background job) |

### Transits & Timing

| Endpoint | Purpose |
|----------|---------|
| `POST /api/transits/calculate` | Current transits to natal chart |

### Numerology & Chakra

| Endpoint | Purpose |
|----------|---------|
| `POST /api/numerology/calculate` | Life path, personal year, Pythagorean square |
| `POST /api/medical/chakra-analysis` | 7-chakra energetic profile |

### Tarot

| Endpoint | Purpose |
|----------|---------|
| `GET /api/tarot/divination/daily` | Card of the day |
| `GET /api/tarot/divination/single` | Random single card |
| `POST /api/tarot/divination/spread` | Multi-card spread |

### Standard Payload

```json
{
  "name": "Shane",
  "datetime": "1991-08-21T16:20:00-04:00",
  "latitude": 41.4489,
  "longitude": -82.708,
  "location": "Sandusky, Ohio, USA",
  "timezone": "America/New_York",
  "house_system": "P"
}
```

---

## 5. Menu Options

1. **AstroVisor - Calendar Review** — Your schedule through the stars
2. **Daily brief** — Full cosmic weather for today
3. **Weekly outlook** — Best days for launches, relationships, communication, finances
4. **Natal deep-dive** — Your full birth chart analysis
5. **Timing question** — When to launch/sign/schedule/post
6. **Tarot pull** — Daily card OR 3-card spread (Past/Present/Future) - clarify which they want
7. **Solar Returns** — Year-ahead themes, house focus, key dates
8. **Numerology** — Life path, personal year, key numbers
9. **Chakra analysis** — 7-chakra energetic profile (cached, only hits API on request)
10. **Help & About** — Commands, features, engineering docs

**Oracle Star Map:** `file:///Users/sc/.hermes/skills/oracle/astro-companion/ui/oracle_chart.html`

---

## 6. natal-mcp Fallback

If Astrovisor rate-limits (429), use natal-mcp MCP server if configured.

natal-mcp provides: create_natal_chart, create_transit_chart, create_solar_return_chart

When user asks for Tarot, clarify:
- "Would you like a **daily card** for guidance today, or a **3-card spread** (Past/Present/Future) for deeper clarity?"

---

## 7. Safety Rules

- Never present astrology as deterministic fact
- Never diagnose medical/psychological conditions
- If birth time unknown, lower certainty
- Retrogrades = revision, not panic

---

## 8. Scripts

| Script | Purpose |
|--------|---------|
| oracle_utils.py | API helpers, menu, cache helpers |
| oracle_astrology.py | Astrovisor calls |
| oracle_digest.py | Daily/weekly briefs |
| oracle_render.py | Terminal charts |
| oracle_launcher.py | Entry flow |

---

Full docs: see references/ directory
