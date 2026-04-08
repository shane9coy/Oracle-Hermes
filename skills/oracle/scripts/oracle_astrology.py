from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from typing import Any

from oracle_profile import load_profile, profile_meta, validate_profile
from oracle_utils import (
    OracleHTTPError,
    get_cache_dir,
    http_json_request,
    iso_now,
    load_cache,
    query_url,
    recursive_find_first,
    recursive_find_values,
    save_cache,
)

DEFAULT_BASE_URL = "https://ephemeris.fyi"
DEFAULT_TIMEOUT = 60
TTL_BY_KIND = {
    "ephemeris": 3600,
    "moon_phase": 3600,
    "planetary_positions": 3600,
    "aspects": 3600,
    "zodiac_sign": 3600,
    "daily_events": 86400,
}


def _perform_http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: Any = None,
) -> Any:
    return http_json_request(
        url, method=method, headers=headers, payload=payload, timeout=DEFAULT_TIMEOUT
    )


def _profile_id(profile: dict[str, Any] | None) -> str | None:
    if not profile:
        return None
    return str(profile_meta(profile).get("profile_id") or "").strip() or None


def build_location_query(
    profile: dict[str, Any], when: str | None = None
) -> dict[str, Any]:
    birth = profile.get("birth_chart", {})
    lat = birth.get("latitude")
    lon = birth.get("longitude")
    if lat is None or lon is None:
        raise ValueError("Profile is missing birth_chart latitude/longitude")
    query: dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
    }
    if when:
        query["datetime"] = when if isinstance(when, str) else when.isoformat()
    return query


def _extract_aspects(data: Any) -> list[str]:
    raw = recursive_find_values(
        data, {"aspects", "major_aspects", "active_aspects", "aspect_list"}
    )
    aspects: list[str] = []
    for value in raw:
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    parts = [
                        str(item.get(key))
                        for key in (
                            "planet_1",
                            "aspect",
                            "planet_2",
                            "body1",
                            "body2",
                            "name",
                        )
                        if item.get(key)
                    ]
                    aspects.append(
                        " ".join(parts).strip() or json.dumps(item, sort_keys=True)
                    )
                else:
                    aspects.append(str(item))
        elif value:
            aspects.append(str(value))
    deduped: list[str] = []
    for aspect in aspects:
        if aspect and aspect not in deduped:
            deduped.append(aspect)
    return deduped[:20]


def _extract_planets(data: Any) -> list[dict[str, Any]]:
    raw = recursive_find_first(
        data,
        {"bodies", "planets", "planet_positions", "positions", "body_positions"},
        default=[],
    )
    planets: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for name, value in raw.items():
            if isinstance(value, dict):
                entry = {"name": name}
                entry.update(value)
                planets.append(entry)
            else:
                planets.append({"name": name, "value": value})
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                planets.append(item)
    return planets[:20]


def _extract_moon_phase(data: Any) -> str | None:
    value = recursive_find_first(
        data,
        {"moon_phase", "moonphase", "phase", "moon_phase_name", "phase_name", "name"},
        default=None,
    )
    return str(value) if value is not None else None


def _extract_moon_sign(data: Any) -> str | None:
    value = recursive_find_first(
        data, {"moon_sign", "moonsign", "sign", "zodiac_sign"}, default=None
    )
    return str(value) if value is not None else None


def _extract_mercury_retrograde(data: Any) -> bool | None:
    explicit = recursive_find_first(
        data,
        {"mercury_retrograde", "mercury_rx", "is_retrograde", "retrograde"},
        default=None,
    )
    if explicit is not None:
        return bool(explicit)
    haystacks = [
        json.dumps(item, sort_keys=True)
        if isinstance(item, (dict, list))
        else str(item)
        for item in recursive_find_values(
            data, {"summary", "interpretation", "status", "description"}
        )
    ]
    combined = " ".join(haystacks).lower()
    if "mercury retrograde" in combined:
        return True
    if "mercury direct" in combined:
        return False
    return None


def _derive_summary(kind: str, data: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "moon_phase": _extract_moon_phase(data),
        "moon_sign": _extract_moon_sign(data),
        "mercury_retrograde": _extract_mercury_retrograde(data),
        "aspects": _extract_aspects(data),
        "planets": _extract_planets(data),
    }


def _error_wrapper(
    kind: str,
    endpoint: str,
    message: str,
    *,
    status: int | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "kind": kind,
        "source": "ephemeris.fyi",
        "endpoint": endpoint,
        "requested_at": iso_now(),
        "cached": False,
        "data": {},
        "derived": {},
        "error": {
            "message": message,
            "status": status,
            "body": body,
        },
    }


def _success_wrapper(
    kind: str, endpoint: str, data: Any, *, cached: bool, url: str
) -> dict[str, Any]:
    return {
        "ok": True,
        "kind": kind,
        "source": "ephemeris.fyi",
        "endpoint": endpoint,
        "url": url,
        "requested_at": iso_now(),
        "cached": cached,
        "data": data,
        "derived": _derive_summary(kind, data),
    }


def call_endpoint(
    *,
    kind: str,
    endpoint: str,
    payload: dict[str, Any] | None = None,
    method: str = "GET",
    ttl: int | None = None,
    query: dict[str, Any] | None = None,
    force: bool = False,
    profile_id: str | None = None,
) -> dict[str, Any]:
    base_url = DEFAULT_BASE_URL.rstrip("/")
    path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    url = base_url + path
    if query:
        url = query_url(url, query)

    cache_key_parts = [url, payload or {}, method]
    ttl = TTL_BY_KIND.get(kind) if ttl is None else ttl
    cache_dir = get_cache_dir(profile_id)

    if ttl != 0 and not force:
        cached_payload = load_cache(kind, cache_key_parts, ttl, cache_dir=cache_dir)
        if cached_payload:
            cached_payload = dict(cached_payload)
            cached_payload["cached"] = True
            return cached_payload

    try:
        response_data = _perform_http_request(
            url, method=method, headers=None, payload=payload
        )
    except OracleHTTPError as exc:
        return _error_wrapper(
            kind,
            endpoint,
            f"Ephemeris request failed with HTTP {exc.status}",
            status=exc.status,
            body=exc.body,
        )
    except Exception as exc:  # noqa: BLE001
        return _error_wrapper(kind, endpoint, str(exc))

    wrapped = _success_wrapper(kind, endpoint, response_data, cached=False, url=url)
    if ttl != 0:
        save_cache(kind, cache_key_parts, wrapped, cache_dir=cache_dir)
    return wrapped


def get_current_sky(profile: dict[str, Any], when: str | None = None) -> dict[str, Any]:
    query = build_location_query(profile, when)
    return call_endpoint(
        kind="ephemeris",
        endpoint="/ephemeris/get_current_sky",
        query=query,
        profile_id=_profile_id(profile),
    )


def get_planetary_positions(
    profile: dict[str, Any], when: str | None = None
) -> dict[str, Any]:
    query = build_location_query(profile, when)
    return call_endpoint(
        kind="planetary_positions",
        endpoint="/ephemeris/get_planetary_positions",
        query=query,
        profile_id=_profile_id(profile),
    )


def get_luminaries(profile: dict[str, Any], when: str | None = None) -> dict[str, Any]:
    query = build_location_query(profile, when)
    return call_endpoint(
        kind="ephemeris",
        endpoint="/ephemeris/get_luminaries",
        query=query,
        profile_id=_profile_id(profile),
    )


def get_ephemeris_data(
    profile: dict[str, Any], when: str | None = None, bodies: list[str] | None = None
) -> dict[str, Any]:
    query = build_location_query(profile, when)
    if bodies:
        query["bodies"] = ",".join(bodies) if isinstance(bodies, list) else bodies
    return call_endpoint(
        kind="ephemeris",
        endpoint="/ephemeris/get_ephemeris_data",
        query=query,
        profile_id=_profile_id(profile),
    )


def get_moon_phase(when: str | None = None) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if when:
        query["datetime"] = when if isinstance(when, str) else when.isoformat()
    return call_endpoint(
        kind="moon_phase",
        endpoint="/ephemeris/get_moon_phase",
        query=query if query else None,
    )


def get_zodiac_sign(
    profile: dict[str, Any], body: str, when: str | None = None
) -> dict[str, Any]:
    query = build_location_query(profile, when)
    query["body"] = body
    return call_endpoint(
        kind="zodiac_sign",
        endpoint="/ephemeris/get_zodiac_sign",
        query=query,
        profile_id=_profile_id(profile),
    )


def calculate_aspects(
    profile: dict[str, Any],
    when: str | None = None,
    orb: float = 8.0,
    bodies: list[str] | None = None,
) -> dict[str, Any]:
    query = build_location_query(profile, when)
    query["orb"] = orb
    if bodies:
        query["bodies"] = ",".join(bodies) if isinstance(bodies, list) else bodies
    return call_endpoint(
        kind="aspects",
        endpoint="/ephemeris/calculate_aspects",
        query=query,
        profile_id=_profile_id(profile),
    )


def get_daily_events(
    profile: dict[str, Any], body: str, when: str | None = None
) -> dict[str, Any]:
    query = build_location_query(profile, when)
    query["body"] = body
    return call_endpoint(
        kind="daily_events",
        endpoint="/ephemeris/get_daily_events",
        query=query,
        profile_id=_profile_id(profile),
    )


def get_earth_position(when: str | None = None) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if when:
        query["datetime"] = when if isinstance(when, str) else when.isoformat()
    return call_endpoint(
        kind="ephemeris",
        endpoint="/ephemeris/get_earth_position",
        query=query if query else None,
    )


def compare_positions(
    profile: dict[str, Any], date1: str, date2: str, bodies: list[str] | None = None
) -> dict[str, Any]:
    query = build_location_query(profile, None)
    query["date1"] = date1
    query["date2"] = date2
    if bodies:
        query["bodies"] = ",".join(bodies) if isinstance(bodies, list) else bodies
    return call_endpoint(
        kind="ephemeris",
        endpoint="/ephemeris/compare_positions",
        query=query,
        profile_id=_profile_id(profile),
    )


def get_natal_chart(profile: dict[str, Any]) -> dict[str, Any]:
    birth = profile.get("birth_chart", {})
    birth_time = birth.get("time") or "12:00"
    natal_dt = f"{birth.get('date')}T{birth_time}:00"
    return get_ephemeris_data(profile, when=natal_dt)


def get_transits(profile: dict[str, Any], when: str | None = None) -> dict[str, Any]:
    target = when or date.today().isoformat()
    return get_ephemeris_data(profile, when=target)


def get_solar_return(profile: dict[str, Any], year: int) -> dict[str, Any]:
    target = f"{year}-06-21T12:00:00"
    return get_ephemeris_data(profile, when=target)


def _load_validated_profile(profile_id: str | None = None) -> dict[str, Any]:
    profile = load_profile(profile_id=profile_id)
    validation = validate_profile(profile)
    if not validation["ok"]:
        profile["validation"] = validation
    return profile


def _add_profile_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile", help="Profile ID to use; defaults to the active Oracle profile"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Oracle Ephemeris client")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sky = subparsers.add_parser("sky")
    _add_profile_argument(sky)
    sky.add_argument("--datetime", default=None)

    planets = subparsers.add_parser("planets")
    _add_profile_argument(planets)
    planets.add_argument("--datetime", default=None)

    luminaries = subparsers.add_parser("luminaries")
    _add_profile_argument(luminaries)
    luminaries.add_argument("--datetime", default=None)

    moon_phase = subparsers.add_parser("moon-phase")
    moon_phase.add_argument("--datetime", default=None)

    natal = subparsers.add_parser("natal")
    _add_profile_argument(natal)

    transit = subparsers.add_parser("transits")
    _add_profile_argument(transit)
    transit.add_argument("--date", dest="date_value", default=date.today().isoformat())

    aspects = subparsers.add_parser("aspects")
    _add_profile_argument(aspects)
    aspects.add_argument("--datetime", default=None)
    aspects.add_argument("--orb", type=float, default=8.0)
    aspects.add_argument("--bodies", default=None)

    zodiac = subparsers.add_parser("zodiac")
    _add_profile_argument(zodiac)
    zodiac.add_argument("--body", required=True)
    zodiac.add_argument("--datetime", default=None)

    daily_events = subparsers.add_parser("daily-events")
    _add_profile_argument(daily_events)
    daily_events.add_argument("--body", required=True)
    daily_events.add_argument("--datetime", default=None)

    earth = subparsers.add_parser("earth")
    earth.add_argument("--datetime", default=None)

    compare = subparsers.add_parser("compare")
    _add_profile_argument(compare)
    compare.add_argument("--date1", required=True)
    compare.add_argument("--date2", required=True)
    compare.add_argument("--bodies", default=None)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    profile = _load_validated_profile(getattr(args, "profile", None))

    if args.command == "sky":
        result = get_current_sky(profile, args.datetime)
    elif args.command == "planets":
        result = get_planetary_positions(profile, args.datetime)
    elif args.command == "luminaries":
        result = get_luminaries(profile, args.datetime)
    elif args.command == "moon-phase":
        result = get_moon_phase(args.datetime)
    elif args.command == "natal":
        result = get_natal_chart(profile)
    elif args.command == "transits":
        result = get_transits(profile, args.date_value)
    elif args.command == "aspects":
        bodies = args.bodies.split(",") if args.bodies else None
        result = calculate_aspects(profile, args.datetime, args.orb, bodies)
    elif args.command == "zodiac":
        result = get_zodiac_sign(profile, args.body, args.datetime)
    elif args.command == "daily-events":
        result = get_daily_events(profile, args.body, args.datetime)
    elif args.command == "earth":
        result = get_earth_position(args.datetime)
    elif args.command == "compare":
        bodies = args.bodies.split(",") if args.bodies else None
        result = compare_positions(profile, args.date1, args.date2, bodies)
    else:
        result = _error_wrapper("unknown", args.command, "Unknown command")

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
