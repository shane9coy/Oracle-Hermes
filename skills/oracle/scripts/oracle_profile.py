from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from oracle_utils import (
    CONSENT_PATH,
    DEFAULT_CONSENT_PATH,
    USER_PROFILE_PATH,
    default_consent_data,
    get_active_profile_id,
    get_env,
    get_profile_paths,
    http_json_request,
    load_json_file,
    load_simple_yaml,
    save_json_file,
    save_simple_yaml,
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")

DEFAULT_PROFILE = {
    "schema_version": "1.0.0",
    "preferred_name": "",
    "timezone": "America/New_York",
    "locale": "en-US",
    "house_system": "P",
    "source_of_birth_data": "user_provided",
    "coordinates_verified": False,
    "birth_chart": {
        "date": "",
        "time": "",
        "time_known": False,
        "location": "",
        "latitude": None,
        "longitude": None,
        "timezone": "",
    },
    "guidance_preferences": {
        "tone": "warm, mystical, grounded",
        "directness": "medium",
        "ritual_language": True,
        "default_view": "brief",
        "include_reflective_questions": True,
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
        "spiritual": 0.6,
    },
    "cached_chart": None,
    "last_reading": None,
    "streak": 0,
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolved_profile_context(profile_id: str | None = None) -> tuple[str | None, Path, Path]:
    resolved_id = profile_id or get_active_profile_id()
    if resolved_id:
        paths = get_profile_paths(resolved_id)
        return resolved_id, paths["profile_path"], paths["consent_path"]
    return None, USER_PROFILE_PATH, CONSENT_PATH


def _attach_meta(profile: dict[str, Any], profile_id: str | None, profile_path: Path, consent_path: Path) -> dict[str, Any]:
    payload = deepcopy(profile)
    payload["__meta__"] = {
        "profile_id": profile_id,
        "profile_path": str(profile_path),
        "consent_path": str(consent_path),
    }
    return payload


def _strip_meta(profile: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(profile)
    payload.pop("__meta__", None)
    return payload


def profile_meta(profile: dict[str, Any]) -> dict[str, Any]:
    meta = profile.get("__meta__")
    return meta if isinstance(meta, dict) else {}


def load_profile(profile_id: str | None = None, path: Path | None = None) -> dict[str, Any]:
    resolved_id, default_profile_path, default_consent_path = _resolved_profile_context(profile_id)
    source_path = Path(path) if path else default_profile_path
    profile = load_json_file(source_path, default={})
    if not isinstance(profile, dict):
        profile = {}
    return _attach_meta(deep_merge(DEFAULT_PROFILE, profile), resolved_id, source_path, default_consent_path)


def save_profile(profile: dict[str, Any], profile_id: str | None = None, path: Path | None = None) -> Path:
    payload = _strip_meta(profile)
    meta = profile_meta(profile)
    resolved_id = profile_id or meta.get("profile_id")
    target_path = Path(path) if path else _resolved_profile_context(resolved_id)[1]
    save_json_file(target_path, payload)
    return target_path


def load_consent(profile_id: str | None = None, path: Path | None = None) -> dict[str, Any]:
    resolved_id, _, default_consent_target = _resolved_profile_context(profile_id)
    target_path = Path(path) if path else default_consent_target
    payload = load_simple_yaml(target_path, default={})
    if not isinstance(payload, dict):
        payload = {}
    if not payload and DEFAULT_CONSENT_PATH.exists() and target_path != DEFAULT_CONSENT_PATH:
        payload = load_simple_yaml(DEFAULT_CONSENT_PATH, default={})
    return deep_merge(default_consent_data(), payload)


def save_consent(consent: dict[str, Any], profile_id: str | None = None, path: Path | None = None) -> Path:
    resolved_id, _, default_consent_target = _resolved_profile_context(profile_id)
    target_path = Path(path) if path else default_consent_target
    payload = deep_merge(default_consent_data(), consent if isinstance(consent, dict) else {})
    save_simple_yaml(target_path, payload, header="# Oracle consent configuration")
    return target_path


def validate_profile(profile: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    birth = profile.get("birth_chart", {})
    birth_date = str(birth.get("date") or "").strip()
    birth_time = str(birth.get("time") or "").strip()
    time_known = bool(birth.get("time_known"))
    latitude = birth.get("latitude")
    longitude = birth.get("longitude")
    timezone_name = str(birth.get("timezone") or profile.get("timezone") or "").strip()

    if birth_date:
        if not DATE_RE.match(birth_date):
            errors.append("birth_chart.date must be YYYY-MM-DD")
        else:
            try:
                datetime.strptime(birth_date, "%Y-%m-%d")
            except ValueError:
                errors.append("birth_chart.date is not a valid calendar date")
    else:
        warnings.append("birth_chart.date is missing; personalized natal readings will be limited")

    if time_known:
        if not TIME_RE.match(birth_time):
            errors.append("birth_chart.time must be HH:MM when time_known is true")
    elif not birth_time:
        warnings.append("birth time is unknown; rising sign and houses may be approximate or unavailable")

    if latitude is None or longitude is None:
        errors.append("birth coordinates are required; supply latitude and longitude or geocode a birthplace")
    else:
        try:
            lat_value = float(latitude)
            lon_value = float(longitude)
        except (TypeError, ValueError):
            errors.append("birth coordinates must be numeric")
        else:
            if not -90 <= lat_value <= 90:
                errors.append("latitude must be between -90 and 90")
            if not -180 <= lon_value <= 180:
                errors.append("longitude must be between -180 and 180")

    if not timezone_name:
        warnings.append("timezone is missing; Oracle will try to resolve it from coordinates")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def geocode_place(query: str) -> dict[str, Any]:
    url = "https://nominatim.openstreetmap.org/search?" + urllib_parse.urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "limit": 1,
        }
    )
    req = urllib_request.Request(url, headers={"User-Agent": "OracleAgent/1.0"})
    with urllib_request.urlopen(req, timeout=20) as response:
        results = json.loads(response.read().decode("utf-8"))
    if not results:
        raise RuntimeError(f"Could not geocode location: {query}")
    result = results[0]
    return {
        "location": result.get("display_name") or query,
        "latitude": float(result["lat"]),
        "longitude": float(result["lon"]),
    }


def resolve_timezone(latitude: float, longitude: float) -> str:
    api_url = "https://timeapi.io/api/TimeZone/coordinate?" + urllib_parse.urlencode(
        {"latitude": latitude, "longitude": longitude}
    )
    response = http_json_request(api_url, method="GET", timeout=int(get_env("ASTROVISOR_TIMEOUT", "60") or 60))
    timezone_name = response.get("timeZone") if isinstance(response, dict) else None
    if not timezone_name:
        raise RuntimeError("Could not resolve timezone from coordinates")
    return str(timezone_name)


def apply_profile_updates(profile: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    updated = deepcopy(profile)
    birth = updated.setdefault("birth_chart", {})
    prefs = updated.setdefault("guidance_preferences", {})

    if args.preferred_name is not None:
        updated["preferred_name"] = args.preferred_name
    if args.birth_date is not None:
        birth["date"] = args.birth_date
    if args.birth_time is not None:
        birth["time"] = args.birth_time
        birth["time_known"] = True
    if args.no_time_known:
        birth["time"] = ""
        birth["time_known"] = False
    if args.location is not None:
        birth["location"] = args.location
    if args.latitude is not None:
        birth["latitude"] = float(args.latitude)
    if args.longitude is not None:
        birth["longitude"] = float(args.longitude)
    if args.timezone is not None:
        birth["timezone"] = args.timezone
        updated["timezone"] = args.timezone
    if args.house_system is not None:
        updated["house_system"] = args.house_system
    if args.directness is not None:
        prefs["directness"] = args.directness
    if args.tone is not None:
        prefs["tone"] = args.tone
    if args.ritual_language is not None:
        prefs["ritual_language"] = args.ritual_language.lower() == "true"

    if args.city:
        geocoded = geocode_place(args.city)
        birth["location"] = geocoded["location"]
        birth["latitude"] = geocoded["latitude"]
        birth["longitude"] = geocoded["longitude"]
        updated["coordinates_verified"] = True

    if birth.get("latitude") is not None and birth.get("longitude") is not None and not birth.get("timezone"):
        birth["timezone"] = resolve_timezone(float(birth["latitude"]), float(birth["longitude"]))
        updated["timezone"] = birth["timezone"]

    if birth.get("timezone") and not updated.get("timezone"):
        updated["timezone"] = birth["timezone"]

    return updated


def cmd_show(args: argparse.Namespace) -> int:
    profile = load_profile(profile_id=args.profile)
    consent = load_consent(profile_id=args.profile)
    validation = validate_profile(profile)
    print(json.dumps({"profile": _strip_meta(profile), "meta": profile_meta(profile), "consent": consent, "validation": validation}, indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    profile = load_profile(profile_id=args.profile)
    print(json.dumps({"meta": profile_meta(profile), "validation": validate_profile(profile)}, indent=2))
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    profile = load_profile(profile_id=args.profile)
    updated = apply_profile_updates(profile, args)
    validation = validate_profile(updated)
    target_path = save_profile(updated, profile_id=args.profile)
    print(json.dumps({"saved": True, "profile_path": str(target_path), "profile": _strip_meta(updated), "validation": validation}, indent=2))
    return 0


def add_profile_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", help="Profile ID to use; defaults to the active Oracle profile")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Oracle profile manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser("show", help="Show the Oracle profile and consent state")
    add_profile_argument(show_parser)
    show_parser.set_defaults(func=cmd_show)

    validate_parser = subparsers.add_parser("validate", help="Validate the current Oracle profile")
    add_profile_argument(validate_parser)
    validate_parser.set_defaults(func=cmd_validate)

    set_parser = subparsers.add_parser("set", help="Set Oracle profile values")
    add_profile_argument(set_parser)
    set_parser.add_argument("--preferred-name")
    set_parser.add_argument("--birth-date")
    set_parser.add_argument("--birth-time")
    set_parser.add_argument("--no-time-known", action="store_true")
    set_parser.add_argument("--city", help="Geocode a birthplace or location")
    set_parser.add_argument("--location")
    set_parser.add_argument("--latitude")
    set_parser.add_argument("--longitude")
    set_parser.add_argument("--timezone")
    set_parser.add_argument("--house-system")
    set_parser.add_argument("--directness")
    set_parser.add_argument("--tone")
    set_parser.add_argument("--ritual-language", choices=["true", "false"])
    set_parser.set_defaults(func=cmd_set)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
