from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from oracle_astrology import get_natal_chart, get_transits
from oracle_profile import load_consent, load_profile, profile_meta
from oracle_scoring import load_day_decision_objects, load_weights, score_decision_objects
from oracle_utils import GOOGLE_API_PATH, ensure_runtime_dirs, get_reports_dir
from oracle_render import normalize_chart_geometry, render_wheel, render_aspect_grid

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

SUN_SIGN_BOUNDARIES = [
    ((1, 20), "Aquarius"),
    ((2, 19), "Pisces"),
    ((3, 21), "Aries"),
    ((4, 20), "Taurus"),
    ((5, 21), "Gemini"),
    ((6, 21), "Cancer"),
    ((7, 23), "Leo"),
    ((8, 23), "Virgo"),
    ((9, 23), "Libra"),
    ((10, 23), "Scorpio"),
    ((11, 22), "Sagittarius"),
    ((12, 22), "Capricorn"),
]

DAY_RULERS = {
    0: ("☾", "Moon", "tend the emotional weather and move gently with what you feel"),
    1: ("♂", "Mars", "act cleanly, directly, and with courage"),
    2: ("☿", "Mercury", "speak, write, negotiate, and clarify"),
    3: ("♃", "Jupiter", "expand, teach, pitch, and think bigger"),
    4: ("♀", "Venus", "connect, harmonize, beautify, and soften"),
    5: ("♄", "Saturn", "structure, edit, commit, and get serious"),
    6: ("☉", "Sun", "create, lead, and be seen"),
}

PHASE_GLYPHS = {
    "new": "🌑",
    "waxing": "🌒",
    "first quarter": "🌓",
    "gibbous": "🌔",
    "full": "🌕",
    "waning": "🌖",
    "last quarter": "🌗",
    "balsamic": "🌘",
}


try:  # optional enhancement
    from rich.console import Console  # type: ignore
    from rich.table import Table  # type: ignore
except Exception:  # noqa: BLE001
    Console = None
    Table = None


def _template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def _profile_id(profile: dict[str, Any]) -> str | None:
    return str(profile_meta(profile).get("profile_id") or "").strip() or None


def _sun_sign(target_date: str) -> str:
    dt = datetime.fromisoformat(target_date)
    month, day_value = dt.month, dt.day
    sign = "Capricorn"
    for (boundary_month, boundary_day), boundary_sign in SUN_SIGN_BOUNDARIES:
        if (month, day_value) >= (boundary_month, boundary_day):
            sign = boundary_sign
    return sign


def _phase_glyph(phase_name: str | None) -> str:
    if not phase_name:
        return "◐"
    lowered = phase_name.lower()
    for key, glyph in PHASE_GLYPHS.items():
        if key in lowered:
            return glyph
    return "◐"


def _mercury_status(astro: dict[str, Any]) -> str:
    derived = astro.get("derived", astro)
    retro = derived.get("mercury_retrograde")
    if retro is True:
        return "☿ Retrograde — revise, review, and slow the send-button impulse"
    if retro is False:
        return "☿ Direct — words travel more cleanly today"
    return "☿ Status unclear — timing guidance is running on partial data"


def _day_ruler(target_date: str) -> tuple[str, str, str]:
    dt = datetime.fromisoformat(target_date)
    return DAY_RULERS[dt.weekday()]


def _calendar_overlay(scored: list[dict[str, Any]]) -> str:
    if not scored:
        return "Calendar Overlay:\n  No calendar data available; Oracle is reading pure timing windows."
    lines = ["Calendar Overlay:"]
    for item in scored[:5]:
        lines.append(
            f"  • {item['title']} — {item['score_band']} for {item['best_domain'].replace('_', ' ')} ({item['score']:.2f})"
        )
    return "\n".join(lines)


def _action_items(scored: list[dict[str, Any]]) -> str:
    if not scored:
        return "Action Items:\n  • Gather birth data or connect live context to sharpen the reading."
    top = scored[:3]
    lines = ["Action Items:"]
    for item in top:
        reason = item["reasons"][0] if item.get("reasons") else "Neutral timing"
        lines.append(f"  • {item['title']}: {reason}")
    cautions = [caution for item in scored[:3] for caution in item.get("cautions", [])][:2]
    for caution in cautions:
        lines.append(f"  • Caution: {caution}")
    return "\n".join(lines)


def _segment_energies(scored: list[dict[str, Any]]) -> tuple[str, str, str, str]:
    default = ("☀", "Build momentum with communication or planning.", "Best for meetings, sending, and visible work.", "Best for reflection, repair, and closure.")
    if not scored:
        return default
    ordered = sorted(scored, key=lambda item: item["starts_at"])
    morning = ordered[0]["best_domain"].replace("_", " ")
    afternoon = ordered[min(1, len(ordered) - 1)]["best_domain"].replace("_", " ")
    evening = ordered[-1]["best_domain"].replace("_", " ")
    return ("☀", f"Leans toward {morning}.", f"Leans toward {afternoon}.", f"Leans toward {evening}.")


def _natal_overlay_text(astro: dict[str, Any]) -> str:
    if not astro.get("ok"):
        return "Astrovisor data is not live yet. Oracle is giving a graceful fallback reading until the token is configured."
    derived = astro.get("derived", {})
    pieces = []
    if derived.get("moon_sign"):
        pieces.append(f"Moon in {derived['moon_sign']}")
    if derived.get("moon_phase"):
        pieces.append(f"Phase: {derived['moon_phase']}")
    if derived.get("aspects"):
        pieces.append(f"Key aspects: {', '.join(derived['aspects'][:2])}")
    return " · ".join(pieces) if pieces else "The chart is live, but no concise overlay was exposed in the current payload."


def _aspects_text(astro: dict[str, Any]) -> str:
    derived = astro.get("derived", {})
    aspects = derived.get("aspects") or []
    if not aspects:
        return "- No major aspects extracted from the current payload"
    return "\n".join(f"- {aspect}" for aspect in aspects[:6])


def _daily_context(target_date: str, profile_id: str | None = None) -> dict[str, Any]:
    ensure_runtime_dirs(profile_id)
    profile = load_profile(profile_id=profile_id)
    resolved_profile_id = _profile_id(profile)
    weights = load_weights()
    astro = get_transits(profile, target_date)
    decision_objects = load_day_decision_objects(target_date, profile, resolved_profile_id)
    scored = score_decision_objects(decision_objects, astro, profile, weights)
    glyph, day_ruler_name, day_ruler_meaning = _day_ruler(target_date)
    morning_icon, morning_energy, afternoon_energy, evening_energy = _segment_energies(scored)
    derived = astro.get("derived", {})
    moon_phase_name = derived.get("moon_phase") or "Unknown phase"
    return {
        "profile": profile,
        "astro": astro,
        "scored": scored,
        "date": target_date,
        "sun_sign": _sun_sign(target_date),
        "moon_sign": derived.get("moon_sign") or "Unknown",
        "moon_phase_glyph": _phase_glyph(moon_phase_name),
        "moon_phase_name": moon_phase_name,
        "illumination": 0 if not moon_phase_name else 50,
        "day_ruler_glyph": glyph,
        "day_ruler_name": day_ruler_name,
        "day_ruler_meaning": day_ruler_meaning,
        "mercury_status": _mercury_status(astro),
        "natal_overlay": _natal_overlay_text(astro),
        "aspects": _aspects_text(astro),
        "moon_energy": derived.get("moon_phase") or "Subtle and unreadable from current payload",
        "morning_icon": morning_icon,
        "morning_energy": morning_energy,
        "afternoon_energy": afternoon_energy,
        "evening_energy": evening_energy,
        "calendar_overlay": _calendar_overlay(scored),
        "action_items": _action_items(scored),
        "profile_id": resolved_profile_id,
    }


def generate_daily_brief(target_date: str, profile_id: str | None = None) -> str:
    context = _daily_context(target_date, profile_id)
    brief = _template("daily_brief.txt").format(**context)
    report_path = get_reports_dir(context["profile_id"]) / f"daily-{target_date}.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(brief + "\n", encoding="utf-8")
    return brief


def generate_weekly_review(start_date: str, profile_id: str | None = None) -> str:
    start = datetime.fromisoformat(start_date).date()
    sections = []
    highlight_tracker: dict[str, tuple[str, float]] = {}
    resolved_profile_id = profile_id
    for offset in range(7):
        current = start + timedelta(days=offset)
        context = _daily_context(current.isoformat(), profile_id)
        resolved_profile_id = context["profile_id"]
        top = context["scored"][0] if context["scored"] else None
        section = [
            f"{current.isoformat()} · ☉ {context['sun_sign']} · ☽ {context['moon_sign']} · {context['moon_phase_glyph']} {context['moon_phase_name']}",
            f"  Best focus: {top['best_domain'].replace('_', ' ')} ({top['score']:.2f})" if top else "  Best focus: gather more data",
            f"  Timing: {context['morning_energy']} / {context['afternoon_energy']} / {context['evening_energy']}",
        ]
        if top:
            best_domain = top["best_domain"]
            prev = highlight_tracker.get(best_domain)
            if prev is None or top["score"] > prev[1]:
                highlight_tracker[best_domain] = (current.isoformat(), top["score"])
        sections.append("\n".join(section))

    highlight_lines = ["Weekly Highlights:"]
    for domain in ["communication", "launches", "relationships", "finance", "rest"]:
        if domain in highlight_tracker:
            day_string, score = highlight_tracker[domain]
            highlight_lines.append(f"  • {domain.replace('_', ' ').title()}: {day_string} ({score:.2f})")

    weekly = _template("weekly_review.txt").format(
        start_date=start_date,
        end_date=(start + timedelta(days=6)).isoformat(),
        daily_sections="\n\n".join(sections),
        highlights="\n".join(highlight_lines),
    )
    report_path = get_reports_dir(resolved_profile_id) / f"weekly-{start_date}.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(weekly + "\n", encoding="utf-8")
    return weekly


def compact_line(target_date: str, profile_id: str | None = None) -> str:
    context = _daily_context(target_date, profile_id)
    mercury = "☿Rx" if context["astro"].get("derived", {}).get("mercury_retrograde") else "☿Direct"
    return f"☉{context['sun_sign'][:2]} ☽{context['moon_sign'][:2]} {context['moon_phase_glyph']} {mercury}"


def _planet_table_rows(astro: dict[str, Any]) -> list[tuple[str, str, str]]:
    planets = (astro.get("derived") or {}).get("planets") or []
    rows = []
    for planet in planets[:12]:
        name = str(planet.get("name") or planet.get("planet") or "Planet")
        sign = str(planet.get("sign") or planet.get("zodiac_sign") or "?")
        degree = str(planet.get("degree") or planet.get("longitude") or planet.get("value") or "?")
        rows.append((name, sign, degree))
    return rows


def render_chart(profile_id: str | None = None, use_wheel: bool = True) -> str:
    """Render the natal chart with optional wheel visualization."""
    profile = load_profile(profile_id=profile_id)
    natal = get_natal_chart(profile)

    if not natal.get("ok"):
        return f"Error fetching chart: {natal.get('error', {}).get('message', 'Unknown error')}"

    # Get raw planet data for table
    rows = _planet_table_rows(natal)

    # Get normalized geometry for wheel
    chart = normalize_chart_geometry(natal)
    planets = chart.get("planets", [])
    aspects = chart.get("aspects", [])

    # Build output
    output_parts = []

    if use_wheel and planets:
        # Add wheel visualization
        output_parts.extend([
            "╭──────────────────────────────────────────────────────────────────╮",
            "│                      ORACLE NATAL WHEEL                        │",
            "╰──────────────────────────────────────────────────────────────────╯",
            "",
            render_wheel(planets),
            "",
        ])

        # Add aspect grid
        output_parts.extend([
            "╭──────────────────────────────────────────────────────────────────╮",
            "│                       ASPECT MATRIX                            │",
            "╰──────────────────────────────────────────────────────────────────╯",
            "",
            render_aspect_grid(planets, aspects),
            "",
        ])

    # Always add the table view as backup
    header = "═══ Oracle Natal Chart ═══"
    overlay = _natal_overlay_text(natal)
    output_parts.extend([header, overlay, ""])

    if Console and Table and rows:
        console = Console(record=True)
        table = Table(title="Planetary Positions")
        table.add_column("Planet")
        table.add_column("Sign")
        table.add_column("Degree / Longitude")
        for row in rows:
            table.add_row(*row)
        console.print(table)
        aspects_text = _aspects_text(natal)
        console.print("\nActive Aspects:\n" + aspects_text)
        table_output = console.export_text()
        output_parts.append(table_output)
    else:
        lines = ["Planetary Positions:"]
        if rows:
            lines.extend(f"  {name:<10} {sign:<12} {degree}" for name, sign, degree in rows)
        else:
            lines.append("  No planet table available from current payload")
        lines.append("")
        lines.append("Active Aspects:")
        lines.append(_aspects_text(natal))
        output_parts.append("\n".join(lines))

    return "\n".join(output_parts)


def _run_gmail_digest(profile_id: str | None = None) -> list[dict[str, Any]]:
    consent = load_consent(profile_id=profile_id)
    if not consent.get("use_hermes_google_default", True) or not consent.get("gmail_read") or not GOOGLE_API_PATH.exists():
        return []
    try:
        completed = subprocess.run(
            [
                "python3",
                str(GOOGLE_API_PATH),
                "gmail",
                "search",
                "is:unread newer_than:3d",
                "--max",
                "5",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
    except Exception:
        return []
    if completed.returncode != 0:
        return []
    try:
        payload = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Oracle briefing and chart renderer")
    parser.add_argument("command", nargs="?", choices=["daily", "weekly", "chart", "reading"], default="daily")
    parser.add_argument("--profile", help="Profile ID to use; defaults to the active Oracle profile")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--no-wheel", action="store_true", help="Skip wheel visualization in chart output")
    parser.add_argument("--no-live", action="store_true", help="Skip live transit data in reading")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.compact:
        print(compact_line(args.date, args.profile))
        return 0

    if args.command == "daily":
        brief = generate_daily_brief(args.date, args.profile)
        inbox = _run_gmail_digest(args.profile)
        if inbox:
            brief += "\n\nInbox Signals:\n" + "\n".join(
                f"  • {item.get('subject', 'Untitled')} — {item.get('from', 'Unknown sender')}" for item in inbox[:5]
            )
        print(brief)
    elif args.command == "weekly":
        print(generate_weekly_review(args.date, args.profile))
    elif args.command == "chart":
        print(render_chart(args.profile, use_wheel=not args.no_wheel))
    elif args.command == "reading":
        from oracle_render import render_full_reading
        print(render_full_reading(args.profile, include_live=not args.no_live))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
