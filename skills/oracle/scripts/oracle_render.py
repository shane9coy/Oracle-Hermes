#!/usr/bin/env python3
"""Oracle terminal renderer: natal wheel, aspect matrix, transit timeline."""

from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timedelta
from typing import Any

# Planet glyphs
PLANET_GLYPHS = {
    "sun": "☉", "sun's": "☉",
    "moon": "☽", "luna": "☽",
    "mercury": "☿",
    "venus": "♀",
    "mars": "♂",
    "jupiter": "♃",
    "saturn": "♄",
    "uranus": "♅",
    "neptune": "♆",
    "pluto": "♇",
    "north node": "☊", "north node's": "☊",
    "south node": "☋", "south node's": "☋",
    "chiron": "⚷",
    "ascendant": "ASC", "rising": "ASC",
    "midheaven": "MC", "mc": "MC",
    "ic": "IC",
    "part of fortune": "⊗",
}

# Sign glyphs
SIGN_GLYPHS = {
    "aries": "♈",
    "taurus": "♉",
    "gemini": "♊",
    "cancer": "♋",
    "leo": "♌",
    "virgo": "♍",
    "libra": "♎",
    "scorpio": "♏",
    "sagittarius": "♐",
    "capricorn": "♑",
    "aquarius": "♒",
    "pisces": "♓",
}

# Element colors (for Rich)
ELEMENT_COLORS = {
    "fire": "red",
    "earth": "green", 
    "air": "cyan",
    "water": "blue",
}

# Aspect symbols
ASPECT_SYMBOLS = {
    "conjunction": "☌",     # 0°
    "sextile": "□",          # 60° (often shown as sextile symbol)
    "square": "□",           # 90°
    "trine": "△",            # 120°
    "opposition": "☍",       # 180°
    "quincunx": "⚻",         # 150°
    "semisextile": "⚄",      # 30°
    "semiquintile": "⚳",     # 36°
    "novile": "⦿",           # 40°
    "binovile": "⦿",         # 80°
    "septile": "⚴",          # ~51.43°
}

# Plain aspect fallback symbols
ASPECT_CHARS = {
    "conjunction": "*",
    "sextile": "x",
    "square": "#",
    "trine": "△",
    "opposition": "o",
    "quincunx": "⚻",
}

# Try to import Rich
try:
    from rich.console import Console
    from rich.text import Text
    from rich.table import Table
    HAS_RICH = True
except Exception:  # noqa: BLE001
    HAS_RICH = False
    Console = None


def _normalize_planet_name(name: str) -> str:
    """Normalize planet name to key."""
    n = name.lower().strip()
    for key in PLANET_GLYPHS:
        if key in n:
            return key
    return n


def _normalize_sign_name(name: str | None) -> str | None:
    """Normalize sign name."""
    if not name:
        return None
    n = name.lower().strip()
    for key in SIGN_GLYPHS:
        if key in n:
            return key
    return n


def _glyph_for_planet(name: str) -> str:
    """Get glyph for a planet."""
    key = _normalize_planet_name(name)
    return PLANET_GLYPHS.get(key, "●")


def _glyph_for_sign(name: str) -> str:
    """Get glyph for a sign."""
    key = _normalize_sign_name(name)
    return SIGN_GLYPHS.get(key, "?")


def _parse_longitude(planet: dict[str, Any]) -> float | None:
    """Extract longitude in degrees (0-360) from planet data."""
    # Try direct longitude
    lon = planet.get("longitude")
    if lon is not None:
        try:
            return float(lon) % 360
        except (ValueError, TypeError):
            pass
    
    # Try degree + sign
    degree = planet.get("degree")
    sign = planet.get("sign")
    if degree is not None and sign:
        try:
            deg_val = float(degree)
            sign_key = _normalize_sign_name(sign)
            sign_offset = {"aries": 0, "taurus": 30, "gemini": 60, "cancer": 90,
                          "leo": 120, "virgo": 150, "libra": 180, "scorpio": 210,
                          "sagittarius": 240, "capricorn": 270, "aquarius": 300, "pisces": 330}.get(sign_key, 0)
            return (sign_offset + deg_val) % 360
        except (ValueError, TypeError):
            pass
    
    # Try value field
    val = planet.get("value")
    if val is not None:
        try:
            return float(val) % 360
        except (ValueError, TypeError):
            pass
    
    return None


def _angle_to_position(angle: float, center_x: float, center_y: float, radius: float, y_scale: float = 0.5) -> tuple[int, int]:
    """Convert angle (degrees) to terminal grid position.
    
    angle: 0° = right (3 o'clock), goes counterclockwise
    """
    rad = math.radians(angle)
    x = int(center_x + radius * math.cos(rad))
    y = int(center_y + radius * y_scale * math.sin(rad))
    return (x, y)


def _extract_planets_from_astro(astro: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalized planet list from Astrovisor response."""
    derived = astro.get("derived", {})
    planets = derived.get("planets", [])
    
    # Also check data root
    if not planets:
        data = astro.get("data", {})
        planets = data.get("planets") or data.get("planet_positions") or []
    
    normalized = []
    for p in planets:
        name = p.get("name") or p.get("planet") or "Unknown"
        lon = _parse_longitude(p)
        sign = p.get("sign") or p.get("zodiac_sign")
        degree = p.get("degree")
        
        if lon is not None:
            normalized.append({
                "name": name,
                "glyph": _glyph_for_planet(name),
                "longitude": lon,
                "sign": sign,
                "degree_in_sign": degree,
                "raw": p,
            })
    
    return normalized


def _calculate_aspects(planets: list[dict[str, Any]], orb: float = 8.0) -> list[dict[str, Any]]:
    """Calculate aspects between planets.
    
    orb: maximum orb in degrees for applying aspect
    """
    aspects_found = []
    aspect_patterns = {
        0: "conjunction",
        60: "sextile", 
        90: "square",
        120: "trine",
        180: "opposition",
    }
    
    for i, p1 in enumerate(planets):
        for p2 in planets[i+1:]:
            lon1 = p1["longitude"]
            lon2 = p2["longitude"]
            
            # Calculate angular distance
            diff = abs(lon1 - lon2)
            diff = min(diff, 360 - diff)  # Shortest arc
            
            for angle, aspect_name in aspect_patterns.items():
                if abs(diff - angle) <= orb:
                    aspects_found.append({
                        "p1": p1["name"],
                        "p2": p2["name"],
                        "glyph1": p1["glyph"],
                        "glyph2": p2["glyph"],
                        "aspect": aspect_name,
                        "symbol": ASPECT_CHARS.get(aspect_name, "?"),
                        "angle": angle,
                        "actual_angle": diff,
                        "orb": abs(diff - angle),
                    })
                    break
    
    return aspects_found


def _render_wheel_unicode(planets: list[dict[str, Any]], width: int = 60, height: int = 28) -> str:
    """Render natal wheel using Unicode characters."""
    
    # Initialize grid
    center_x = width // 2
    center_y = height // 2
    outer_radius = min(center_x, center_y) - 2
    inner_radius = outer_radius - 4
    
    grid = [[" " for _ in range(width)] for _ in range(height)]
    
    # Draw outer circle (approximate with Unicode)
    for angle in range(0, 360, 3):
        x, y = _angle_to_position(angle, center_x, center_y, outer_radius, 0.5)
        if 0 <= x < width and 0 <= y < height:
            grid[y][x] = "●"
    
    # Draw inner circle
    for angle in range(0, 360, 6):
        x, y = _angle_to_position(angle, center_x, center_y, inner_radius, 0.5)
        if 0 <= x < width and 0 <= y < height:
            grid[y][x] = "○"
    
    # Draw center point
    if 0 <= center_x < width and 0 <= center_y < height:
        grid[center_y][center_x] = "⊕"
    
    # Place sign glyphs on outer ring
    sign_names = list(SIGN_GLYPHS.keys())
    for i, sign in enumerate(sign_names):
        angle = i * 30 + 15  # Middle of each sign
        x, y = _angle_to_position(angle, center_x, center_y, outer_radius + 1, 0.5)
        if 0 <= x < width and 0 <= y < height:
            grid[y][x] = SIGN_GLYPHS[sign]
    
    # Place planets on inner ring with collision handling
    planet_positions = []
    for planet in planets:
        angle = planet["longitude"]
        # Check for collision
        for existing_angle, existing_name in planet_positions:
            if abs(angle - existing_angle) < 8 or abs(angle - existing_angle) > 352:
                # Offset slightly
                angle = (angle + 5) % 360
        planet_positions.append((angle, planet["name"]))
        
        # Use different radii for different planets to reduce overlap
        radius = inner_radius - 2
        
        x, y = _angle_to_position(angle, center_x, center_y, radius, 0.5)
        if 0 <= x < width and 0 <= y < height:
            glyph = planet["glyph"]
            # Place glyph
            if len(glyph) == 1:
                grid[y][x] = glyph
            else:
                # For 2-char glyphs like ASC
                if x + 1 < width:
                    grid[y][x] = glyph[0]
                    grid[y][x+1] = glyph[1]
    
    # Convert to string
    lines = []
    for y, row in enumerate(grid):
        line = "".join(row)
        # Add zodiac labels on the sides
        if y == center_y - outer_radius // 2:
            line = "♈ Aries" + line[12:]
        elif y == center_y + outer_radius // 2 - 2:
            line = line[:-12] + "♎ Libra"
        lines.append(line)
    
    return "\n".join(lines)


def _render_wheel_plain(planets: list[dict[str, Any]], width: int = 50) -> str:
    """Render simplified ASCII wheel without Unicode."""
    
    lines = []
    lines.append(" " * 20 + "╭─ Natal Wheel ─╮")
    
    # Simplified ring representation
    signs = ["Ari", "Tau", "Gem", "Can", "Leo", "Vir", "Lib", "Sco", "Sag", "Cap", "Aqu", "Pis"]
    ring = " ".join(signs)
    lines.append(" " * (width // 2 - len(ring) // 2) + ring)
    lines.append("")
    
    # Planet list organized by element
    fire_earth_air_water = {"fire": [], "earth": [], "air": [], "water": []}
    for planet in planets:
        sign = planet.get("sign", "").lower()
        if sign in ["aries", "leo", "sagittarius"]:
            fire_earth_air_water["fire"].append(planet)
        elif sign in ["taurus", "virgo", "capricorn"]:
            fire_earth_air_water["earth"].append(planet)
        elif sign in ["gemini", "libra", "aquarius"]:
            fire_earth_air_water["air"].append(planet)
        else:
            fire_earth_air_water["water"].append(planet)
    
    for element, p_list in fire_earth_air_water.items():
        if p_list:
            parts = [f"{p['glyph']} {p['name'][:6]}" for p in p_list]
            lines.append(f"  {element.upper()}: {' | '.join(parts)}")
    
    lines.append("")
    lines.append(" " * 20 + "╰─ End Wheel ─╯")
    
    return "\n".join(lines)


def _render_aspect_matrix(planets: list[dict[str, Any]], aspects: list[dict[str, Any]]) -> str:
    """Render aspect matrix as a grid."""
    
    if not planets:
        return "No planet data available for aspect matrix."
    
    # Get top planets (exclude points)
    main_planets = [p for p in planets if p["name"].lower() not in 
                    ["ascendant", "midheaven", "ic", "part of fortune", "north node", "south node"]]
    main_planets = main_planets[:8]  # Limit to 8 for readable matrix
    
    # Build matrix
    glyphs = [p["glyph"] for p in main_planets]
    
    if HAS_RICH:
        lines = ["═══ Aspect Matrix ═══", ""]
        # Header
        header = "       " + " ".join(f"{g:>3}" for g in glyphs)
        lines.append(header)
        
        for i, p1 in enumerate(main_planets):
            row = [f"{p1['glyph']:>3}"]
            for j, p2 in enumerate(main_planets):
                if i == j:
                    row.append("  •")
                else:
                    # Find aspect
                    aspect = None
                    for a in aspects:
                        if (a["p1"] == p1["name"] and a["p2"] == p2["name"]) or \
                           (a["p2"] == p1["name"] and a["p1"] == p2["name"]):
                            aspect = a
                            break
                    if aspect:
                        row.append(f" {aspect['symbol']:>2}")
                    else:
                        row.append("  -")
            lines.append(" ".join(row))
        
        return "\n".join(lines)
    
    # Plain text fallback
    lines = ["=== Aspect Matrix ===", ""]
    header = "    " + " ".join(f"{g:>4}" for g in glyphs)
    lines.append(header)
    lines.append("-" * len(header))
    
    for i, p1 in enumerate(main_planets):
        row = [f"{p1['glyph']:<4}"]
        for j, p2 in enumerate(main_planets):
            if i == j:
                row.append("  • ")
            else:
                aspect = None
                for a in aspects:
                    if (a["p1"] == p1["name"] and a["p2"] == p2["name"]) or \
                       (a["p2"] == p1["name"] and a["p1"] == p2["name"]):
                        aspect = a
                        break
                if aspect:
                    row.append(f" {aspect['symbol']:<2} ")
                else:
                    row.append("  - ")
        lines.append("".join(row))
    
    # Add aspect legend
    lines.append("")
    lines.append("Legend:")
    for name, symbol in ASPECT_CHARS.items():
        lines.append(f"  {symbol} = {name}")
    
    return "\n".join(lines)


def _render_timeline(scored_days: list[dict[str, Any]], days: int = 7) -> str:
    """Render transit score timeline as heatmap strip."""
    
    if not scored_days:
        return "No transit timing data available."
    
    # Bar characters for heatmap
    bars = " ▁▂▃▄▅▆▇█"
    
    if HAS_RICH:
        lines = ["═══ Transit Timeline ═══", ""]
    else:
        lines = ["=== Transit Timeline ===", ""]
    
    # Group by domain
    domains = {}
    for day_data in scored_days:
        domain = day_data.get("best_domain", "unknown")
        if domain not in domains:
            domains[domain] = []
        domains[domain].append(day_data)
    
    # Render each domain as a strip
    for domain in sorted(domains.keys()):
        day_scores = domains[domain]
        if not day_scores:
            continue
            
        # Create bar for each day
        domain_bars = []
        for ds in day_scores[:days]:
            score = ds.get("score", 0.5)
            bar_idx = int(score * 8)
            bar_idx = max(0, min(8, bar_idx))
            domain_bars.append(bars[bar_idx])
        
        domain_label = domain.replace("_", " ").title()[:20]
        
        if HAS_RICH:
            lines.append(f"  {domain_label:<18} {' '.join(domain_bars)}")
        else:
            lines.append(f"  {domain_label:<18} {' '.join(domain_bars)}")
    
    lines.append("")
    lines.append("Score: ▁=low █=high")
    
    return "\n".join(lines)


def _render_timeline_simple(daily_contexts: list[dict[str, Any]]) -> str:
    """Simple timeline from daily contexts."""
    
    if not daily_contexts:
        return "No timeline data available."
    
    bars = " ▁▂▃▄▅▆▇█"
    lines = ["=== Daily Transit Strip ===", ""]
    
    for ctx in daily_contexts:
        dt = ctx.get("date", "?")
        scored = ctx.get("scored", [])
        
        if scored:
            best = scored[0]
            score = best.get("score", 0.5)
            domain = best.get("best_domain", "?").replace("_", " ")[:12]
            bar_idx = int(score * 8)
            bar = bars[max(0, min(8, bar_idx))]
            moon = ctx.get("moon_phase_glyph", "◐")
            lines.append(f"  {dt} {moon} {bar} {domain}")
        else:
            lines.append(f"  {dt} ◐   - no data")
    
    return "\n".join(lines)


# === Public API ===

def normalize_chart_geometry(astro: dict[str, Any]) -> dict[str, Any]:
    """Normalize chart data for rendering.
    
    Returns:
        Dictionary with planets, aspects, and metadata
    """
    planets = _extract_planets_from_astro(astro)
    aspects = _calculate_aspects(planets)
    
    return {
        "planets": planets,
        "aspects": aspects,
        "count": len(planets),
        "aspect_count": len(aspects),
    }


def render_wheel(planets: list[dict[str, Any]], use_unicode: bool = True) -> str:
    """Render natal wheel.
    
    Args:
        planets: List of planet dicts with name, glyph, longitude, sign
        use_unicode: Use Unicode glyphs (default True)
    
    Returns:
        Rendered wheel as string
    """
    if not planets:
        return "No planet data available for wheel rendering."
    
    if use_unicode:
        return _render_wheel_unicode(planets)
    else:
        return _render_wheel_plain(planets)


def render_aspect_grid(planets: list[dict[str, Any]], aspects: list[dict[str, Any]] | None = None) -> str:
    """Render aspect matrix grid.
    
    Args:
        planets: List of planet dicts
        aspects: Optional pre-calculated aspects (will calculate if not provided)
    
    Returns:
        Rendered aspect matrix
    """
    if not planets:
        return "No planet data available."
    
    if aspects is None:
        aspects = _calculate_aspects(planets)
    
    return _render_aspect_matrix(planets, aspects)


def render_timeline(daily_scores: list[dict[str, Any]]) -> str:
    """Render transit timeline heatmap.
    
    Args:
        daily_scores: List of daily score dicts with date, score, best_domain
    
    Returns:
        Rendered timeline strip
    """
    if not daily_scores:
        return "No timing data available."
    
    return _render_timeline(daily_scores)


# === CLI ===

def _load_profile_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", help="Profile ID to use")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Oracle chart renderer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Wheel command
    wheel = subparsers.add_parser("wheel", help="Render natal wheel")
    _load_profile_argument(wheel)
    wheel.add_argument("--ascii", action="store_true", help="Use plain ASCII")

    # Aspect command
    aspects = subparsers.add_parser("aspects", help="Render aspect matrix")
    _load_profile_argument(aspects)

    # Timeline command
    timeline = subparsers.add_parser("timeline", help="Render transit timeline")
    _load_profile_argument(timeline)
    timeline.add_argument("--days", type=int, default=7, help="Number of days")

    # Full chart command
    chart = subparsers.add_parser("chart", help="Render full chart (wheel + aspects)")
    _load_profile_argument(chart)

    # Full reading command (comprehensive)
    reading = subparsers.add_parser("reading", help="Full natal reading with interpretations")
    _load_profile_argument(reading)
    reading.add_argument("--no-live", action="store_true", help="Skip live transit data")

    # Element balance
    elements = subparsers.add_parser("elements", help="Element balance display")
    _load_profile_argument(elements)

    # Dignities
    dignities = subparsers.add_parser("dignities", help="Dignities table")
    _load_profile_argument(dignities)

    # Planet readings
    readings = subparsers.add_parser("planet-readings", help="Planet-by-planet readings")
    _load_profile_argument(readings)

    # Live positions
    live = subparsers.add_parser("live", help="Current planetary positions")
    _load_profile_argument(live)

    # Moon clock
    moon = subparsers.add_parser("moon", help="Moon sign clock")
    _load_profile_argument(moon)

    # Transit pulse
    pulse = subparsers.add_parser("pulse", help="Active transit pulse")
    _load_profile_argument(pulse)

    return parser


def main() -> int:
    # Import here to avoid issues if not available
    from oracle_astrology import get_natal_chart, get_transits
    from oracle_profile import load_profile
    from oracle_scoring import score_decision_objects, load_weights, load_day_decision_objects
    from oracle_utils import ensure_runtime_dirs

    parser = build_parser()
    args = parser.parse_args()

    profile_id = getattr(args, "profile", None)
    ensure_runtime_dirs(profile_id)
    profile = load_profile(profile_id=profile_id)

    if args.command == "wheel":
        natal = get_natal_chart(profile)
        geo = normalize_chart_geometry(natal)
        print(render_wheel(geo["planets"], use_unicode=not args.ascii))

    elif args.command == "aspects":
        natal = get_natal_chart(profile)
        geo = normalize_chart_geometry(natal)
        print(render_aspect_grid(geo["planets"], geo["aspects"]))

    elif args.command == "timeline":
        days = args.days
        start = date.today()
        daily_contexts = []

        weights = load_weights()

        for offset in range(days):
            current = start + timedelta(days=offset)
            astro = get_transits(profile, current.isoformat())
            decision_objects = load_day_decision_objects(current.isoformat(), profile, profile_id)
            scored = score_decision_objects(decision_objects, astro, profile, weights)
            daily_contexts.append({
                "date": current.isoformat(),
                "scored": scored,
                "astro": astro,
            })

        print(render_timeline([{"date": d["date"], "score": d["scored"][0].get("score", 0.5) if d["scored"] else 0.5,
                               "best_domain": d["scored"][0].get("best_domain", "none") if d["scored"] else "none"}
                              for d in daily_contexts]))

    elif args.command == "chart":
        natal = get_natal_chart(profile)
        geo = normalize_chart_geometry(natal)

        print("╔══════════════════════════════════════════════════════════╗")
        print("║                    ORACLE NATAL CHART                     ║")
        print("╚══════════════════════════════════════════════════════════╝")
        print("")
        print(render_wheel(geo["planets"]))
        print("")
        print(render_aspect_grid(geo["planets"], geo["aspects"]))
        print("")

    elif args.command == "reading":
        print(render_full_reading(profile_id, include_live=not args.no_live))

    elif args.command == "elements":
        natal = get_natal_chart(profile)
        geo = normalize_chart_geometry(natal)
        print(render_element_balance(geo["planets"]))
        print("")
        print(render_modal_balance(geo["planets"]))

    elif args.command == "dignities":
        natal = get_natal_chart(profile)
        geo = normalize_chart_geometry(natal)
        print(render_dignities_table(geo["planets"]))

    elif args.command == "planet-readings":
        natal = get_natal_chart(profile)
        geo = normalize_chart_geometry(natal)
        print(render_planet_readings(geo["planets"]))

    elif args.command == "live":
        print(render_live_positions(profile_id))

    elif args.command == "moon":
        print(render_moon_clock(profile_id))

    elif args.command == "pulse":
        print(render_transit_pulse(profile_id))

    return 0


# ============================================================================
# ELEMENT & MODAL BALANCE
# ============================================================================

# Element assignments (sign -> element)
ELEMENT_OF_SIGN = {
    "aries": "fire", "leo": "fire", "sagittarius": "fire",
    "taurus": "earth", "virgo": "earth", "capricorn": "earth",
    "gemini": "air", "libra": "air", "aquarius": "air",
    "cancer": "water", "scorpio": "water", "pisces": "water",
}

# Modal assignments (sign -> mode)
MODE_OF_SIGN = {
    "aries": "cardinal", "cancer": "cardinal", "libra": "cardinal", "capricorn": "cardinal",
    "taurus": "fixed", "leo": "fixed", "scorpio": "fixed", "aquarius": "fixed",
    "gemini": "mutable", "virgo": "mutable", "sagittarius": "mutable", "pisces": "mutable",
}

ELEMENT_SYMBOLS = {"fire": "🔥", "earth": "🌍", "air": "💨", "water": "💧"}
MODE_SYMBOLS = {"cardinal": "⚡", "fixed": "⛓", "mutable": "🔄"}


def calculate_element_balance(planets: list[dict[str, Any]]) -> dict[str, int]:
    """Calculate element distribution in the chart."""
    counts = {"fire": 0, "earth": 0, "air": 0, "water": 0}
    for planet in planets:
        sign = (planet.get("sign") or "").lower()
        elem = ELEMENT_OF_SIGN.get(sign)
        if elem:
            counts[elem] += 1
    return counts


def calculate_modal_balance(planets: list[dict[str, Any]]) -> dict[str, int]:
    """Calculate modal distribution in the chart."""
    counts = {"cardinal": 0, "fixed": 0, "mutable": 0}
    for planet in planets:
        sign = (planet.get("sign") or "").lower()
        mode = MODE_OF_SIGN.get(sign)
        if mode:
            counts[mode] += 1
    return counts


def render_element_balance(planets: list[dict[str, Any]]) -> str:
    """Render element balance as a bar chart."""
    counts = calculate_element_balance(planets)
    total = sum(counts.values())
    if total == 0:
        return "Element balance: No data"

    lines = ["═══ Element Balance ═══"]
    for elem in ["fire", "earth", "air", "water"]:
        count = counts[elem]
        pct = (count / total) * 100
        bar_len = int(pct / 5)  # 20 chars = 100%
        bar = "█" * bar_len + "░" * (20 - bar_len)
        lines.append(f"  {ELEMENT_SYMBOLS[elem]} {elem.capitalize():6} {bar} {pct:5.1f}% ({count})")

    # Interpretation
    dominant = max(counts, key=counts.get)
    deficient = min(counts, key=counts.get)
    if counts[deficient] == 0:
        lines.append(f"  → Strong {dominant} emphasis, {deficient} absent")
    elif counts[dominant] - counts[deficient] >= 2:
        lines.append(f"  → Emphasizes {dominant}, lacking {deficient}")

    return "\n".join(lines)


def render_modal_balance(planets: list[dict[str, Any]]) -> str:
    """Render modal balance as a bar chart."""
    counts = calculate_modal_balance(planets)
    total = sum(counts.values())
    if total == 0:
        return "Modal balance: No data"

    lines = ["═══ Modal Balance ═══"]
    for mode in ["cardinal", "fixed", "mutable"]:
        count = counts[mode]
        pct = (count / total) * 100
        bar_len = int(pct / 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        lines.append(f"  {MODE_SYMBOLS[mode]} {mode.capitalize():8} {bar} {pct:5.1f}% ({count})")

    # Interpretation
    dominant = max(counts, key=counts.get)
    lines.append(f"  → {dominant.capitalize()} emphasis")

    return "\n".join(lines)


# ============================================================================
# DIGNITIES TABLE
# ============================================================================

# Sign rulership (which planet rules which sign)
SIGN_RULERS = {
    "aries": "mars", "scorpio": "mars", "pluto": "mars",
    "taurus": "venus", "libra": "venus",
    "gemini": "mercury", "virgo": "mercury",
    "cancer": "moon",
    "leo": "sun",
    "sagittarius": "jupiter",
    "capricorn": "saturn",
    "aquarius": "saturn", "uranus": "aquarius",
    "pisces": "jupiter", "neptune": "pisces",
}

# Exalted signs
EXALTED = {
    "sun": "aries",
    "moon": "taurus",
    "mercury": "virgo",
    "venus": "pisces",
    "mars": "capricorn",
    "jupiter": "cancer",
    "saturn": "libra",
    "uranus": "scorpio",
    "neptune": "sagittarius",
    "pluto": "aries",
}

# Detriment (opposite to ruling)
DETRIMENT = {
    "sun": "aquarius",
    "moon": "scorpio",
    "mercury": "pisces",
    "venus": "virgo",
    "mars": "libra",
    "jupiter": "gemini",
    "saturn": "cancer",
    "uranus": "taurus",
    "neptune": "virgo",
    "pluto": "libra",
}

# Fall (opposite to exaltation)
FALL = {
    "sun": "libra",
    "moon": "scorpio",
    "mercury": "pisces",
    "venus": "virgo",
    "mars": "cancer",
    "jupiter": "capricorn",
    "saturn": "aries",
    "uranus": "taurus",
    "neptune": "cancer",
    "pluto": "libra",
}

DIGNITY_SYMBOLS = {
    "rulership": "●",
    "exalted": "▲",
    "detriment": "○",
    "fall": "▼",
}


def get_planet_dignity(planet_name: str, sign_name: str) -> str | None:
    """Get the dignity status of a planet in a sign."""
    planet = planet_name.lower()
    sign = sign_name.lower()

    if SIGN_RULERS.get(sign) == planet:
        return "rulership"
    if EXALTED.get(planet) == sign:
        return "exalted"
    if DETRIMENT.get(planet) == sign:
        return "detriment"
    if FALL.get(planet) == sign:
        return "fall"
    return None


def render_dignities_table(planets: list[dict[str, Any]]) -> str:
    """Render dignities table for planets."""
    main_planets = ["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn"]
    lines = ["═══ Dignities Table ═══"]
    lines.append(f"{'Planet':<10} {'Sign':<12} {'Status':<12} {'Symbol'}")
    lines.append("─" * 45)

    for planet in planets:
        name = planet.get("name", "").lower()
        if name not in main_planets:
            continue

        sign = planet.get("sign", "")
        dignity = get_planet_dignity(name, sign)
        symbol = DIGNITY_SYMBOLS.get(dignity, "")

        if dignity:
            lines.append(f"{planet.get('name', name):<10} {sign:<12} {dignity:<12} {symbol}")
        else:
            lines.append(f"{planet.get('name', name):<10} {sign:<12} {'—':<12}")

    lines.append("")
    lines.append("Legend: ● rulership  ▲ exalted  ○ detriment  ▼ fall")

    return "\n".join(lines)


# ============================================================================
# PLANET INTERPRETATIONS
# ============================================================================

PLANET_INTERPRETATIONS = {
    "sun": {
        "rulership": "Core identity, vitality, creative expression, ego",
        "exalted": "Strong sense of self, creativity honored",
        "detriment": "Struggle with identity, ego conflicts",
        "fall": "Identity crisis, creative blocks",
    },
    "moon": {
        "rulership": "Emotional nature, instincts, habits, home",
        "exalted": "Intuitive clarity, emotional intelligence",
        "detriment": "Emotional instability, home conflicts",
        "fall": "Emotional confusion, insecure attachment",
    },
    "mercury": {
        "rulership": "Communication, intellect, reasoning",
        "exalted": "Sharp mind, articulate expression",
        "detriment": "Communication difficulties, scattered thinking",
        "fall": "Miscommunication, mental confusion",
    },
    "venus": {
        "rulership": "Love, beauty, values, relationships",
        "exalted": "Harmonious relationships, artistic talent",
        "detriment": "Relationship challenges, value conflicts",
        "fall": "Love difficulties, aesthetic confusion",
    },
    "mars": {
        "rulership": "Energy, action, desire, assertion",
        "exalted": "Strong drive, effective action",
        "detriment": "Aggressive tendencies, conflict proneness",
        "fall": "Weak drive, frustration, passive aggression",
    },
    "jupiter": {
        "rulership": "Growth, expansion, optimism, wisdom",
        "exalted": "Philosophical mind, generous spirit",
        "detriment": "Excessive optimism, overexpansion",
        "fall": "Dogmatic thinking, missed opportunities",
    },
    "saturn": {
        "rulership": "Structure, discipline, karma, time",
        "exalted": "Mastery through discipline, wisdom",
        "detriment": "Fear of restriction, authority issues",
        "fall": "Delayed growth, self-limitation",
    },
    "uranus": {
        "rulership": "Innovation, rebellion, sudden change",
        "exalted": "Genius, revolutionary thinking",
        "detriment": "Rebellious without cause, erratic",
        "fall": "Shock for growth, unexpected disruptions",
    },
    "neptune": {
        "rulership": "Dreams, intuition, spirituality",
        "exalted": "Spiritual insight, artistic inspiration",
        "detriment": "Illusion, escapism, confusion",
        "fall": "Spiritual confusion, deception",
    },
    "pluto": {
        "rulership": "Transformation, power, rebirth",
        "exalted": "Profound transformation, power under control",
        "detriment": "Power struggles, obsessive tendencies",
        "fall": "Forced transformation, power games",
    },
}


def render_planet_readings(planets: list[dict[str, Any]]) -> str:
    """Render interpretive readings for each planet."""
    lines = ["═══ Planet Readings ═══", ""]

    main_planets = ["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune", "pluto"]

    for planet in planets:
        name = planet.get("name", "").lower()
        if name not in main_planets:
            continue

        sign = planet.get("sign", "unknown")
        degree = planet.get("degree_in_sign", planet.get("degree", "?"))
        dignity = get_planet_dignity(name, sign)

        glyph = planet.get("glyph", "")
        lines.append(f"{glyph} {name.capitalize()} in {sign} ({degree}°):")

        # Get interpretation based on dignity
        if dignity and dignity in PLANET_INTERPRETATIONS.get(name, {}):
            interp = PLANET_INTERPRETATIONS[name][dignity]
            lines.append(f"   → {interp}")
        else:
            # General sign interpretation
            lines.append(f"   → {name.capitalize()} in {sign} expresses uniquely")

        # Add retrograde indicator
        if planet.get("retrograde") or planet.get("is_retrograde"):
            lines.append(f"   ⚠ Retrograde - internalizes the {name} energy")

        lines.append("")

    return "\n".join(lines)


# ============================================================================
# ASPECT INTERPRETATIONS
# ============================================================================

ASPECT_INTERPRETATIONS = {
    "conjunction": "Blends energies, creates focus. Can be harmonious or challenging depending on planets involved.",
    "sextile": "Opportunity aspect. Harmonious but requires effort to manifest potential.",
    "square": "Tension aspect. Creates friction that can motivate action or cause frustration.",
    "trine": "Harmonious flow. Natural talent and ease in expressing these energies together.",
    "opposition": "Polarities in tension. Can cause projection or encourage integration of opposites.",
    "quincunx": "Incongruent aspect. Requires adjustment and adaptation.",
    "semisextile": "Subtle opportunity. Minor tension that can lead to growth.",
    "semisquare": "Minor tension. Slight friction that attracts attention.",
}


def render_aspect_readings(aspects: list[dict[str, Any]]) -> str:
    """Render interpretive readings for aspects."""
    if not aspects:
        return "═══ Aspect Readings ═══\n  No major aspects calculated"

    lines = ["═══ Aspect Readings ═══", ""]

    for aspect in aspects[:10]:  # Limit to top 10
        p1 = aspect.get("p1_name", aspect.get("planet1", ""))
        p2 = aspect.get("p2_name", aspect.get("planet2", ""))
        aspect_type = aspect.get("aspect", "")
        glyph = aspect.get("symbol", "")

        lines.append(f"{glyph} {p1.capitalize()} {aspect_type} {p2.capitalize()}:")

        # Get interpretation
        interp = ASPECT_INTERPRETATIONS.get(aspect_type.lower(), "Unique planetary relationship")
        lines.append(f"   → {interp}")

        # Add orb info
        orb = aspect.get("orb", 0)
        if orb:
            lines.append(f"   (orb: {orb:.1f}°)")

        lines.append("")

    return "\n".join(lines)


# ============================================================================
# HOUSE CUSPS ON WHEEL
# ============================================================================

def render_house_overview(planets: list[dict[str, Any]]) -> str:
    """Render house position overview."""
    lines = ["═══ House Overview ═══"]

    # Look for house-sensitive points
    house_points = []
    for planet in planets:
        name = planet.get("name", "").lower()
        if name in ["ascendant", "midheaven", "ic", "dsc", "rising", "mc"]:
            house = planet.get("house")
            sign = planet.get("sign", "?")
            glyph = planet.get("glyph", "")
            house_points.append((name, sign, house, glyph))

    if house_points:
        for name, sign, house, glyph in house_points:
            house_str = f"House {house}" if house else ""
            lines.append(f"  {glyph} {name.capitalize():12} {sign:<10} {house_str}")
    else:
        lines.append("  (House positions not available)")

    return "\n".join(lines)


# ============================================================================
# PLANET SPEED / RETROGRADE BAR
# ============================================================================

def render_planet_speeds(planets: list[dict[str, Any]]) -> str:
    """Render planet speed indicators showing retrograde status."""
    lines = ["═══ Planet Motion ═══"]

    for planet in planets:
        name = planet.get("name", "")
        glyph = planet.get("glyph", "")
        speed = planet.get("speed", 0)
        is_retrograde = planet.get("retrograde") or planet.get("is_retrograde", False)

        if is_retrograde:
            motion = "↺ RETROGRADE"
        elif speed and speed > 0:
            motion = "→ Direct"
        else:
            motion = "? Unknown"

        lines.append(f"  {glyph} {name:<10} {motion}")

    return "\n".join(lines)


# ============================================================================
# MOON PHASE ARC
# ============================================================================

MOON_PHASE_ANGLES = {
    "new": (0, 45),
    "waxing_crescent": (45, 90),
    "first_quarter": (90, 135),
    "waxing_gibbous": (135, 180),
    "full": (180, 225),
    "waning_gibbous": (225, 270),
    "last_quarter": (270, 315),
    "waning_crescent": (315, 360),
}

MOON_PHASE_GLYPHS = {
    "new": "🌑",
    "waxing_crescent": "🌒",
    "first_quarter": "🌓",
    "waxing_gibbous": "🌔",
    "full": "🌕",
    "waning_gibbous": "🌖",
    "last_quarter": "🌗",
    "waning_crescent": "🌘",
}

MOON_PHASE_NAMES = {
    "new": "New Moon",
    "waxing_crescent": "Waxing Crescent",
    "first_quarter": "First Quarter",
    "waxing_gibbous": "Waxing Gibbous",
    "full": "Full Moon",
    "waning_gibbous": "Waning Gibbous",
    "last_quarter": "Last Quarter",
    "waning_crescent": "Waning Crescent",
}


def render_moon_phase(astro: dict[str, Any]) -> str:
    """Render moon phase with visual arc."""
    derived = astro.get("derived", {})
    moon_phase = derived.get("moon_phase", "").lower()

    # Try to find matching phase
    phase_glyph = "🌑"
    phase_name = "Unknown"

    for key, glyph in MOON_PHASE_GLYPHS.items():
        if key.replace("_", " ") in moon_phase or moon_phase in key.replace("_", " "):
            phase_glyph = glyph
            phase_name = MOON_PHASE_NAMES.get(key, moon_phase.title())
            break

    # Also check derived data directly
    if not phase_name or phase_name == "Unknown":
        moon = next((p for p in derived.get("planets", []) if p.get("name", "").lower() == "moon"), None)
        if moon:
            lon = moon.get("longitude", 0)
            for key, (start, end) in MOON_PHASE_ANGLES.items():
                if start <= lon < end:
                    phase_glyph = MOON_PHASE_GLYPHS.get(key, "🌑")
                    phase_name = MOON_PHASE_NAMES.get(key, "Unknown")
                    break

    lines = ["═══ Moon Phase ═══"]
    lines.append(f"  {phase_glyph} {phase_name}")

    # Create visual arc
    arc = ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"]
    lines.append("  " + " ".join(arc))

    return "\n".join(lines)


# ============================================================================
# LIVE PLANETARY POSITIONS
# ============================================================================

def render_live_positions(profile_id: str | None = None) -> str:
    """Render current planetary positions (live transits)."""
    from datetime import datetime
    from oracle_profile import load_profile
    from oracle_astrology import get_transits

    profile = load_profile(profile_id=profile_id)
    now = datetime.now().date().isoformat()
    astro = get_transits(profile, now)

    if not astro.get("ok"):
        return f"Could not fetch live positions: {astro.get('error', {}).get('message', 'Unknown')}"

    planets = astro.get("derived", {}).get("planets", [])

    lines = ["═══ Live Planetary Positions ═══", ""]
    lines.append("Current transits:")

    for planet in planets[:10]:
        name = planet.get("name", "Unknown")
        glyph = _glyph_for_planet(name)
        sign = planet.get("sign", "?")
        degree = planet.get("degree_in_sign", planet.get("degree", "?"))
        rx = " (Rx)" if (planet.get("retrograde") or planet.get("is_retrograde")) else ""
        lines.append(f"  {glyph} {name:<10} {sign:<10} {degree}°{rx}")

    return "\n".join(lines)


# ============================================================================
# COUNTDOWN TO ASPECTS & INGRESS
# ============================================================================

def render_upcoming_events(profile_id: str | None = None, days_ahead: int = 14) -> str:
    """Render upcoming planetary events (aspects, ingress)."""
    from oracle_profile import load_profile
    from oracle_astrology import get_transits
    from datetime import date, timedelta

    profile = load_profile(profile_id=profile_id)

    # Get current and future positions
    today = date.today()
    events = []

    for offset in range(1, days_ahead + 1):
        future_date = today + timedelta(days=offset)
        astro = get_transits(profile, future_date.isoformat())

        if not astro.get("ok"):
            continue

        planets = astro.get("derived", {}).get("planets", [])

        # Check for ingress (planet entering new sign)
        current_astro = get_transits(profile, (future_date - timedelta(days=1)).isoformat())
        if current_astro.get("ok"):
            current_planets = current_astro.get("derived", {}).get("planets", [])
            for planet in planets:
                name = planet.get("name", "")
                sign = planet.get("sign", "")
                for cp in current_planets:
                    if cp.get("name") == name and cp.get("sign") != sign:
                        events.append(f"{future_date.strftime('%m/%d')}: {name} enters {sign}")
                        break

    lines = ["═══ Upcoming Events ═══"]
    if events:
        for event in events[:7]:
            lines.append(f"  • {event}")
    else:
        lines.append("  No major events in next 14 days")

    return "\n".join(lines)


# ============================================================================
# MOON SIGN CLOCK
# ============================================================================

def render_moon_clock(profile_id: str | None = None) -> str:
    """Render current moon sign as a clock-style display."""
    from oracle_profile import load_profile
    from oracle_astrology import get_transits
    from datetime import date

    profile = load_profile(profile_id=profile_id)
    astro = get_transits(profile, date.today().isoformat())

    derived = astro.get("derived", {})
    moon_sign = derived.get("moon_sign", "Unknown")
    moon_phase = derived.get("moon_phase", "Unknown")

    # Moon glyph based on phase
    phase_glyph = "🌑"
    for key, glyph in MOON_PHASE_GLYPHS.items():
        if key.replace("_", " ") in moon_phase.lower():
            phase_glyph = glyph
            break

    lines = ["╭── Moon Sign Clock ──╮", f"│ {phase_glyph} {moon_sign:<18} │", "╰─────────────────────╯"]

    return "\n".join(lines)


# ============================================================================
# TRANSIT PULSE (Active transits)
# ============================================================================

def render_transit_pulse(profile_id: str | None = None) -> str:
    """Render active transit indicators."""
    from oracle_profile import load_profile
    from oracle_astrology import get_transits
    from datetime import date

    profile = load_profile(profile_id=profile_id)
    astro = get_transits(profile, date.today().isoformat())

    if not astro.get("ok"):
        return "Could not fetch transit pulse"

    derived = astro.get("derived", {})
    aspects = derived.get("aspects", [])

    # Find significant transits (tight orbs)
    significant = []
    for aspect in aspects:
        orb = aspect.get("orb", 10)
        if orb < 2:  # Tight aspect
            p1 = aspect.get("planet1", "")
            p2 = aspect.get("planet2", "")
            aspect_type = aspect.get("aspect", "")
            significant.append(f"{p1} {aspect_type} {p2}")

    lines = ["═══ Transit Pulse ═══"]

    # Check for retrograde
    planets = derived.get("planets", [])
    rx_planets = [p.get("name") for p in planets if p.get("retrograde") or p.get("is_retrograde")]

    if rx_planets:
        lines.append("  ⚠ Retrograde:")
        lines.append(f"    {', '.join(rx_planets)}")

    # Significant transits
    if significant:
        lines.append("  Tight Aspects (active):")
        for s in significant[:5]:
            lines.append(f"    • {s}")
    else:
        lines.append("  No tight aspect transits today")

    return "\n".join(lines)


# ============================================================================
# COMPREHENSIVE CHART DISPLAY
# ============================================================================

def render_full_reading(profile_id: str | None = None, include_live: bool = True) -> str:
    """Render comprehensive chart reading with all available information."""
    from oracle_profile import load_profile
    from oracle_astrology import get_natal_chart, get_transits

    profile = load_profile(profile_id=profile_id)
    natal = get_natal_chart(profile)
    today_transits = get_transits(profile, date.today().isoformat())

    if not natal.get("ok"):
        return f"Error: {natal.get('error', {}).get('message', 'Unknown')}"

    chart = normalize_chart_geometry(natal)
    planets = chart.get("planets", [])
    aspects = chart.get("aspects", [])

    output = []

    # Header
    output.extend([
        "╔══════════════════════════════════════════════════════════════════════╗",
        "║                      ORACLE NATAL READING                           ║",
        "╚══════════════════════════════════════════════════════════════════════╝",
        "",
    ])

    # Wheel
    output.extend([
        "╭──────────────────────────────────────────────────────────────────────╮",
        "│                           NATAL WHEEL                               │",
        "╰──────────────────────────────────────────────────────────────────────╯",
        "",
        render_wheel(planets),
        "",
    ])

    # Element & Modal Balance
    output.extend([
        "╭──────────────────────────────────────────────────────────────────────╮",
        "│                      ELEMENT & MODAL BALANCE                        │",
        "╰──────────────────────────────────────────────────────────────────────╯",
        "",
        render_element_balance(planets),
        "",
        render_modal_balance(planets),
        "",
    ])

    # Dignities
    output.extend([
        "╭──────────────────────────────────────────────────────────────────────╮",
        "│                          DIGNITIES TABLE                            │",
        "╰──────────────────────────────────────────────────────────────────────╯",
        "",
        render_dignities_table(planets),
        "",
    ])

    # House Overview
    output.extend([
        "╭──────────────────────────────────────────────────────────────────────╮",
        "│                          HOUSE OVERVIEW                             │",
        "╰──────────────────────────────────────────────────────────────────────╯",
        "",
        render_house_overview(planets),
        "",
    ])

    # Planet Motion
    output.extend([
        "╭──────────────────────────────────────────────────────────────────────╮",
        "│                         PLANET MOTION                               │",
        "╰──────────────────────────────────────────────────────────────────────╯",
        "",
        render_planet_speeds(planets),
        "",
    ])

    # Moon Phase
    output.extend([
        "╭──────────────────────────────────────────────────────────────────────╮",
        "│                            MOON PHASE                               │",
        "╰──────────────────────────────────────────────────────────────────────╯",
        "",
        render_moon_phase(today_transits),
        "",
    ])

    # Aspect Matrix & Readings
    output.extend([
        "╭──────────────────────────────────────────────────────────────────────╮",
        "│                         ASPECT MATRIX                               │",
        "╰──────────────────────────────────────────────────────────────────────╯",
        "",
        render_aspect_grid(planets, aspects),
        "",
        render_aspect_readings(aspects),
        "",
    ])

    # Planet Readings
    output.extend([
        "╭──────────────────────────────────────────────────────────────────────╮",
        "│                       PLANET READINGS                              │",
        "╰──────────────────────────────────────────────────────────────────────╯",
        "",
        render_planet_readings(planets),
        "",
    ])

    # Transit Pulse (if live)
    if include_live:
        output.extend([
            "╭──────────────────────────────────────────────────────────────────────╮",
            "│                         TRANSIT PULSE                             │",
            "╰──────────────────────────────────────────────────────────────────────╯",
            "",
            render_transit_pulse(profile_id),
            "",
            render_moon_clock(profile_id),
            "",
            render_live_positions(profile_id),
            "",
            render_upcoming_events(profile_id),
            "",
        ])

    return "\n".join(output)


if __name__ == "__main__":
    raise SystemExit(main())
