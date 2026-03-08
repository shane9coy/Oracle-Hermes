#!/usr/bin/env python3
"""
Oracle SVG Chart Generator

Generates natal and transit charts as SVG images using the natal library.
Can also generate composite (synastry) and solar return charts.

Usage:
    python oracle_svg_chart.py natal --profile <id>              # Your natal chart
    python oracle_svg_chart.py transit --profile <id> --date 2026-06-15  # Transit chart
    python oracle_svg_chart.py solar-return --profile <id> --year 2026    # Solar return
    python oracle_svg_chart.py composite --profile <id> --partner-id <id> # Synastry
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
ORACLE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import natal.chart as nc
import natal.data as nd
from oracle_utils import (
    ACTIVE_PROFILE_PATH,
    PROFILES_DIR,
)
from oracle_profile import load_profile


def load_active_profile() -> dict:
    """Load the active profile."""
    if not ACTIVE_PROFILE_PATH.exists():
        print("ERROR: No active profile. Run oracle_profiles.py first.")
        sys.exit(1)
    
    with open(ACTIVE_PROFILE_PATH) as f:
        data = json.load(f)
    
    profile_id = data.get("active_profile_id")
    if not profile_id:
        print("ERROR: No active profile ID.")
        sys.exit(1)
    
    return load_profile(profile_id)


def get_utc_from_local(dt_str: str, tz_str: str) -> datetime:
    """Convert local datetime to UTC."""
    local_tz = ZoneInfo(tz_str)
    local_dt = datetime.fromisoformat(dt_str).replace(tzinfo=local_tz)
    return local_dt.astimezone(ZoneInfo("UTC"))


def create_natal_data(profile: dict, width: int = 800) -> tuple:
    """Create natal Data and Chart objects from profile."""
    bc = profile["birth_chart"]
    
    # Convert birth time to UTC
    local_dt = datetime.fromisoformat(f"{bc['date']}T{bc['time']}:00")
    local_tz = ZoneInfo(bc["timezone"])
    local_dt = local_dt.replace(tzinfo=local_tz)
    utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
    
    # Create custom dark theme with black background
    import natal.config as ncfg
    dark_theme = ncfg.DarkTheme(
        fire='#ef476f',
        earth='#ffd166',
        air='#06d6a0',
        water='#81bce7',
        points='#118ab2',
        asteroids='#AA96DA',
        positive='#FFC0CB',
        negative='#AD8B73',
        others='#FFA500',
        transparency=0.1,
        foreground='#F7F3F0',
        background='#000000',  # Pure black
        dim='#515860'
    )
    config = ncfg.Config(
        theme_type='dark',
        dark_theme=dark_theme
    )
    
    # Create Data object
    data = nd.Data(
        name=profile.get("preferred_name", "Unknown"),
        lat=bc["latitude"],
        lon=bc["longitude"],
        utc_dt=utc_dt.strftime("%Y-%m-%d %H:%M:%S"),
        config=config
    )
    
    # Create Chart
    chart = nc.Chart(data, width=width)
    
    return data, chart


def create_transit_data(profile: dict, transit_date: str, width: int = 800) -> tuple:
    """Create natal Data + transit Chart for composite view."""
    bc = profile["birth_chart"]
    
    # Create custom dark theme with black background
    import natal.config as ncfg
    dark_theme = ncfg.DarkTheme(
        fire='#ef476f',
        earth='#ffd166',
        air='#06d6a0',
        water='#81bce7',
        points='#118ab2',
        asteroids='#AA96DA',
        positive='#FFC0CB',
        negative='#AD8B73',
        others='#FFA500',
        transparency=0.1,
        foreground='#F7F3F0',
        background='#000000',
        dim='#515860'
    )
    config = ncfg.Config(
        theme_type='dark',
        dark_theme=dark_theme
    )
    
    # Natal data
    local_dt = datetime.fromisoformat(f"{bc['date']}T{bc['time']}:00")
    local_tz = ZoneInfo(bc["timezone"])
    local_dt = local_dt.replace(tzinfo=local_tz)
    utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
    
    natal_data = nd.Data(
        name=profile.get("preferred_name", "Unknown"),
        lat=bc["latitude"],
        lon=bc["longitude"],
        utc_dt=utc_dt.strftime("%Y-%m-%d %H:%M:%S"),
        config=config
    )
    
    # Transit data
    transit_dt = datetime.fromisoformat(transit_date)
    if transit_dt.tzinfo is None:
        transit_dt = transit_dt.replace(tzinfo=ZoneInfo("UTC"))
    else:
        transit_dt = transit_dt.astimezone(ZoneInfo("UTC"))
    
    transit_data = nd.Data(
        name=f"Transits: {transit_date}",
        lat=bc["latitude"],
        lon=bc["longitude"],
        utc_dt=transit_dt.strftime("%Y-%m-%d %H:%M:%S"),
        config=config
    )
    
    # Composite chart (natal + transits)
    chart = nc.Chart(natal_data, width=width, data2=transit_data)
    
    return natal_data, chart


def save_svg(chart: nc.Chart, output_path: Path, description: str):
    """Save chart SVG to file."""
    svg_content = chart.svg
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w") as f:
        f.write(svg_content)
    
    print(f"✓ {description}")
    print(f"  Saved to: {output_path}")
    return output_path


def cmd_natal(args):
    """Generate natal chart."""
    profile = load_profile(args.profile) if args.profile != "active" else load_active_profile()
    
    # Get profile ID from meta
    profile_id = profile.get("__meta__", {}).get("profile_id") or args.profile
    
    output_dir = PROFILES_DIR / profile_id / "charts"
    output_path = output_dir / "natal.svg"
    
    _, chart = create_natal_data(profile, width=args.width)
    result = save_svg(chart, output_path, f"Natal chart for {profile.get('preferred_name')}")
    
    if args.open:
        import subprocess
        subprocess.run(["open", str(result)])


def cmd_transit(args):
    """Generate transit chart (composite natal + transit)."""
    profile = load_profile(args.profile) if args.profile != "active" else load_active_profile()
    
    # Get profile ID from meta
    profile_id = profile.get("__meta__", {}).get("profile_id") or args.profile
    
    output_dir = PROFILES_DIR / profile_id / "charts"
    output_path = output_dir / f"transit_{args.date}.svg"
    
    _, chart = create_transit_data(profile, args.date, width=args.width)
    result = save_svg(chart, output_path, f"Transit chart for {args.date}")
    
    if args.open:
        import subprocess
        subprocess.run(["open", str(result)])


def cmd_solar_return(args):
    """Generate solar return chart."""
    profile = load_profile(args.profile) if args.profile != "active" else load_active_profile()
    
    # Get profile ID from meta
    profile_id = profile.get("__meta__", {}).get("profile_id") or args.profile
    
    bc = profile["birth_chart"]
    year = args.year
    
    # Calculate solar return date (birthday in target year)
    birthday = f"{year}-{bc['date'][5:]}"  # Replace year
    local_tz = ZoneInfo(bc["timezone"])
    
    # Approximate: noon on birthday in local timezone
    sr_dt = datetime.fromisoformat(f"{birthday}T12:00:00").replace(tzinfo=local_tz)
    utc_dt = sr_dt.astimezone(ZoneInfo("UTC"))
    
    # Create custom dark theme with black background
    import natal.config as ncfg
    dark_theme = ncfg.DarkTheme(
        fire='#ef476f',
        earth='#ffd166',
        air='#06d6a0',
        water='#81bce7',
        points='#118ab2',
        asteroids='#AA96DA',
        positive='#FFC0CB',
        negative='#AD8B73',
        others='#FFA500',
        transparency=0.1,
        foreground='#F7F3F0',
        background='#000000',
        dim='#515860'
    )
    config = ncfg.Config(
        theme_type='dark',
        dark_theme=dark_theme
    )
    
    # Create solar return "natal" data
    sr_data = nd.Data(
        name=f"Solar Return {year}",
        lat=bc["latitude"],
        lon=bc["longitude"],
        utc_dt=utc_dt.strftime("%Y-%m-%d %H:%M:%S"),
        config=config
    )
    
    chart = nc.Chart(sr_data, width=args.width)
    
    output_dir = PROFILES_DIR / profile_id / "charts"
    output_path = output_dir / f"solar_return_{year}.svg"
    
    result = save_svg(chart, output_path, f"Solar Return {year}")
    
    if args.open:
        import subprocess
        subprocess.run(["open", str(result)])


def main():
    parser = argparse.ArgumentParser(description="Oracle SVG Chart Generator")
    subparsers = parser.add_subparsers(dest="command", help="Chart type")
    
    # Natal chart
    natal_parser = subparsers.add_parser("natal", help="Generate natal chart")
    natal_parser.add_argument("--profile", default="active", help="Profile ID (default: active)")
    natal_parser.add_argument("--width", type=int, default=800, help="SVG width")
    natal_parser.add_argument("--open", action="store_true", help="Open in browser")
    
    # Transit chart
    transit_parser = subparsers.add_parser("transit", help="Generate transit chart (composite)")
    transit_parser.add_argument("--profile", default="active", help="Profile ID (default: active)")
    transit_parser.add_argument("--date", required=True, help="Transit date (YYYY-MM-DD)")
    transit_parser.add_argument("--width", type=int, default=800, help="SVG width")
    transit_parser.add_argument("--open", action="store_true", help="Open in browser")
    
    # Solar return
    sr_parser = subparsers.add_parser("solar-return", help="Generate solar return chart")
    sr_parser.add_argument("--profile", default="active", help="Profile ID (default: active)")
    sr_parser.add_argument("--year", type=int, required=True, help="Year for solar return")
    sr_parser.add_argument("--width", type=int, default=800, help="SVG width")
    sr_parser.add_argument("--open", action="store_true", help="Open in browser")
    
    args = parser.parse_args()
    
    if args.command == "natal":
        cmd_natal(args)
    elif args.command == "transit":
        cmd_transit(args)
    elif args.command == "solar-return":
        cmd_solar_return(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    import json
    main()
