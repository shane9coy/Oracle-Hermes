# Oracle Data Contracts

## 1. `user_profile.json`

```json
{
  "schema_version": "1.0.0",
  "preferred_name": "string",
  "timezone": "IANA timezone string",
  "locale": "string",
  "house_system": "P | other supported code",
  "source_of_birth_data": "string",
  "coordinates_verified": true,
  "birth_chart": {
    "date": "YYYY-MM-DD",
    "time": "HH:MM",
    "time_known": true,
    "location": "string",
    "latitude": 41.29,
    "longitude": -83.15,
    "timezone": "IANA timezone string"
  },
  "guidance_preferences": {
    "tone": "string",
    "directness": "low | medium | high",
    "ritual_language": true,
    "default_view": "brief | deep",
    "include_reflective_questions": true
  },
  "life_domains": {
    "communication": 0.9,
    "relationships": 1.0,
    "finance": 0.8,
    "creativity": 0.7,
    "rest": 0.6,
    "decisive_action": 0.85,
    "launches": 0.9,
    "health": 0.8,
    "spiritual": 0.6
  },
  "cached_chart": null,
  "last_reading": null,
  "streak": 0
}
```

## 2. `decision_object`

Normalized representation of either a calendar event, email thread, or synthetic timing window.

```json
{
  "id": "evt_123",
  "kind": "calendar_event | email_thread | timing_window",
  "title": "Partnership call",
  "starts_at": "2026-03-10T15:00:00-07:00",
  "domain_tags": ["relationships", "communication"],
  "urgency": 0.8,
  "raw": {}
}
```

## 3. `scored_window`

```json
{
  "id": "evt_123",
  "kind": "calendar_event",
  "title": "Partnership call",
  "starts_at": "2026-03-10T15:00:00-07:00",
  "domain_tags": ["relationships", "communication"],
  "score": 1.84,
  "score_band": "yellow-green",
  "best_domain": "communication",
  "reasons": [
    "Libra Moon supports communication work",
    "Current aspects add extra support for this domain"
  ],
  "cautions": [
    "Mercury retrograde adds revision energy and can muddle timing-sensitive decisions"
  ],
  "score_breakdown": {
    "event_domain_weight": 0.55,
    "user_priority_weight": 0.9,
    "support": 0.35,
    "urgency_modifier": 0.16,
    "risk": 0.12
  },
  "all_domains": []
}
```

## 4. `daily_brief`

Structured rendering context used by `daily_brief.txt`.

```json
{
  "date": "2026-03-10",
  "sun_sign": "Pisces",
  "moon_sign": "Libra",
  "moon_phase_glyph": "🌔",
  "moon_phase_name": "Waxing Gibbous",
  "illumination": 78,
  "day_ruler_glyph": "☿",
  "day_ruler_name": "Mercury",
  "day_ruler_meaning": "speak, write, negotiate, and clarify",
  "mercury_status": "☿ Direct — words travel more cleanly today",
  "natal_overlay": "Moon in Libra · Key aspects: Mercury trine Jupiter",
  "aspects": "- Mercury trine Jupiter",
  "moon_energy": "Waxing Gibbous",
  "morning_icon": "☀",
  "morning_energy": "Leans toward communication.",
  "afternoon_energy": "Leans toward decisive action.",
  "evening_energy": "Leans toward rest.",
  "calendar_overlay": "Calendar Overlay: ...",
  "action_items": "Action Items: ..."
}
```

## 5. Normalized Astrovisor Response Wrapper

Every Astrovisor call should be wrapped in a stable envelope so downstream scripts do not depend directly on raw endpoint structure.

```json
{
  "ok": true,
  "kind": "transits",
  "source": "astrovisor",
  "endpoint": "/api/transits/calculate",
  "url": "https://astrovisor.io/api/transits/calculate",
  "requested_at": "2026-03-07T18:00:00+00:00",
  "cached": false,
  "data": {},
  "derived": {
    "kind": "transits",
    "moon_phase": "Waxing Gibbous",
    "moon_sign": "Libra",
    "mercury_retrograde": false,
    "aspects": ["Mercury trine Jupiter"],
    "planets": []
  },
  "error": null
}
```

When an error occurs:

```json
{
  "ok": false,
  "kind": "natal",
  "source": "astrovisor",
  "endpoint": "/api/solar/calculate",
  "requested_at": "2026-03-07T18:00:00+00:00",
  "cached": false,
  "data": {},
  "derived": {},
  "error": {
    "message": "ASTROVISOR_TOKEN is not configured",
    "status": null,
    "body": null
  }
}
```
