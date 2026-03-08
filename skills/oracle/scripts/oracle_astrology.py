from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from typing import Any

from oracle_profile import load_profile, profile_meta, validate_profile
from oracle_utils import (
    OracleHTTPError,
    get_cache_dir,
    get_env,
    http_json_request,
    iso_now,
    load_cache,
    query_url,
    recursive_find_first,
    recursive_find_values,
    resolve_token_alias,
    save_cache,
)

DEFAULT_BASE_URL = get_env("ASTROVISOR_BASE_URL", "https://astrovisor.io") or "https://astrovisor.io"
DEFAULT_TIMEOUT = int(get_env("ASTROVISOR_TIMEOUT", "60") or 60)
TRANSIT_ENDPOINT_CANDIDATES = [
    "/api/transits/calculate",
    "/api/natal/transits",
]
TTL_BY_KIND = {
    "natal": None,
    "transits": 3600,
    "calendar_predictions": 21600,
    "harmonics": 86400,
    "minor_aspects": 86400,
    "solar_return": 86400,
    "lunation_overlay": 86400,
    "planetary_returns": 86400,
    "profections": 86400,
    "numerology": 86400,
    "chakra": 86400,
    "financial_cycles": 21600,
    "tarot_daily": 0,
    "tarot_spread": 0,
    "tarot_single": 0,
}


def _perform_http_request(url: str, *, method: str = "POST", headers: dict[str, str] | None = None, payload: Any = None) -> Any:
    return http_json_request(url, method=method, headers=headers, payload=payload, timeout=DEFAULT_TIMEOUT)


def _token() -> str | None:
    return resolve_token_alias()


def _headers() -> dict[str, str] | None:
    token = _token()
    if not token:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _profile_id(profile: dict[str, Any] | None) -> str | None:
    if not profile:
        return None
    return str(profile_meta(profile).get("profile_id") or "").strip() or None


def build_birth_payload(profile: dict[str, Any], *, target_datetime: str | None = None, extras: dict[str, Any] | None = None) -> dict[str, Any]:
    birth = profile.get("birth_chart", {})
    birth_time = birth.get("time") or "12:00"
    payload = {
        "name": profile.get("preferred_name") or "Oracle User",
        "datetime": target_datetime or f"{birth.get('date')}T{birth_time}:00",
        "latitude": birth.get("latitude"),
        "longitude": birth.get("longitude"),
        "location": birth.get("location") or "Unknown",
        "timezone": birth.get("timezone") or profile.get("timezone") or "UTC",
        "full_name": profile.get("preferred_name") or "Oracle User",
        "house_system": profile.get("house_system", "P"),
    }
    if extras:
        payload.update(extras)
    return payload


def _extract_aspects(data: Any) -> list[str]:
    raw = recursive_find_values(data, {"aspects", "major_aspects", "active_aspects"})
    aspects: list[str] = []
    for value in raw:
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    parts = [str(item.get(key)) for key in ("planet_1", "aspect", "planet_2") if item.get(key)]
                    aspects.append(" ".join(parts).strip() or json.dumps(item, sort_keys=True))
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
    raw = recursive_find_first(data, {"planets", "planet_positions", "positions"}, default=[])
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
    value = recursive_find_first(data, {"moon_phase", "moonphase", "phase", "moon_phase_name"}, default=None)
    return str(value) if value is not None else None


def _extract_moon_sign(data: Any) -> str | None:
    value = recursive_find_first(data, {"moon_sign", "moonsign"}, default=None)
    return str(value) if value is not None else None


def _extract_mercury_retrograde(data: Any) -> bool | None:
    explicit = recursive_find_first(data, {"mercury_retrograde", "mercury_rx"}, default=None)
    if explicit is not None:
        return bool(explicit)
    haystacks = [json.dumps(item, sort_keys=True) if isinstance(item, (dict, list)) else str(item) for item in recursive_find_values(data, {"summary", "interpretation", "status", "description"})]
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


def _error_wrapper(kind: str, endpoint: str, message: str, *, status: int | None = None, body: str | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "kind": kind,
        "source": "astrovisor",
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


def _success_wrapper(kind: str, endpoint: str, data: Any, *, cached: bool, url: str) -> dict[str, Any]:
    return {
        "ok": True,
        "kind": kind,
        "source": "astrovisor",
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
    method: str = "POST",
    ttl: int | None = None,
    query: dict[str, Any] | None = None,
    force: bool = False,
    profile_id: str | None = None,
) -> dict[str, Any]:
    token = _token()
    if not token:
        return _error_wrapper(kind, endpoint, "ASTROVISOR_TOKEN / ASTROVISOR_API_KEY is not configured")

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
        response_data = _perform_http_request(url, method=method, headers=_headers(), payload=payload)
    except OracleHTTPError as exc:
        return _error_wrapper(kind, endpoint, f"Astrovisor request failed with HTTP {exc.status}", status=exc.status, body=exc.body)
    except Exception as exc:  # noqa: BLE001
        return _error_wrapper(kind, endpoint, str(exc))

    wrapped = _success_wrapper(kind, endpoint, response_data, cached=False, url=url)
    if ttl != 0:
        save_cache(kind, cache_key_parts, wrapped, cache_dir=cache_dir)
    return wrapped


def get_natal_chart(profile: dict[str, Any]) -> dict[str, Any]:
    return call_endpoint(kind="natal", endpoint="/api/natal/chart", payload=build_birth_payload(profile), profile_id=_profile_id(profile))


def get_transits(profile: dict[str, Any], when: str | None = None) -> dict[str, Any]:
    target = when or date.today().isoformat()
    payload = build_birth_payload(
        profile,
        extras={
            "date": target,
            "transit_date": target,
        },
    )
    last_error: dict[str, Any] | None = None
    for endpoint in TRANSIT_ENDPOINT_CANDIDATES:
        response = call_endpoint(kind="transits", endpoint=endpoint, payload=payload, profile_id=_profile_id(profile))
        if response.get("ok"):
            return response
        last_error = response
        error_status = (response.get("error") or {}).get("status")
        if error_status not in {404, 405}:
            return response
    return last_error or _error_wrapper("transits", TRANSIT_ENDPOINT_CANDIDATES[0], "No transit endpoint available")


def get_calendar_predictions(profile: dict[str, Any], start: str, end: str) -> dict[str, Any]:
    birth = profile.get("birth_chart", {})
    payload = {
        "start_date": start,
        "end_date": end,
        "name": profile.get("preferred_name") or "Oracle User",
        "datetime": f"{birth.get('date')}T{(birth.get('time') or '12:00')}:00",
        "birth_date": birth.get("date"),
        "birth_time": birth.get("time") or "12:00",
        "birth_place": birth.get("location"),
        "birth_latitude": birth.get("latitude"),
        "birth_longitude": birth.get("longitude"),
        "birth_timezone": birth.get("timezone") or profile.get("timezone") or "UTC",
        "latitude": birth.get("latitude"),
        "longitude": birth.get("longitude"),
        "location": birth.get("location"),
        "timezone": birth.get("timezone") or profile.get("timezone") or "UTC",
    }
    return call_endpoint(kind="calendar_predictions", endpoint="/api/calendar/generate", payload=payload, profile_id=_profile_id(profile))


def get_harmonics(profile: dict[str, Any]) -> dict[str, Any]:
    return call_endpoint(kind="harmonics", endpoint="/api/harmonics/calculate", payload=build_birth_payload(profile), profile_id=_profile_id(profile))


def get_minor_aspects(profile: dict[str, Any]) -> dict[str, Any]:
    return call_endpoint(kind="minor_aspects", endpoint="/api/minor-aspects/calculate", payload=build_birth_payload(profile), profile_id=_profile_id(profile))


def get_solar_return(profile: dict[str, Any], year: int) -> dict[str, Any]:
    return call_endpoint(
        kind="solar_return",
        endpoint="/api/solar/return",
        payload=build_birth_payload(profile, extras={"return_year": year, "year": year, "compare_with_natal": True}),
        profile_id=_profile_id(profile),
    )


def get_lunation_overlay(profile: dict[str, Any], year: int) -> dict[str, Any]:
    return call_endpoint(
        kind="lunation_overlay",
        endpoint="/api/solar/lunations-overlay",
        payload=build_birth_payload(profile),
        query={"year": year},
        profile_id=_profile_id(profile),
    )


def get_planetary_returns(profile: dict[str, Any], start: str, end: str) -> dict[str, Any]:
    return call_endpoint(
        kind="planetary_returns",
        endpoint="/api/solar/all-planetary-returns",
        payload=build_birth_payload(profile, extras={"start_date": start, "end_date": end}),
        profile_id=_profile_id(profile),
    )


def get_profections(profile: dict[str, Any]) -> dict[str, Any]:
    return call_endpoint(kind="profections", endpoint="/api/solar/profections", payload=build_birth_payload(profile), profile_id=_profile_id(profile))


def get_numerology(profile: dict[str, Any]) -> dict[str, Any]:
    birth = profile.get("birth_chart", {})
    payload = build_birth_payload(profile, extras={"birth_date": birth.get("date")})
    return call_endpoint(kind="numerology", endpoint="/api/numerology/calculate", payload=payload, profile_id=_profile_id(profile))


def get_chakra(profile: dict[str, Any]) -> dict[str, Any]:
    return call_endpoint(kind="chakra", endpoint="/api/medical/chakra-analysis", payload=build_birth_payload(profile), profile_id=_profile_id(profile))


def get_financial_cycles(start: str, end: str, index: str = "SPX") -> dict[str, Any]:
    return call_endpoint(
        kind="financial_cycles",
        endpoint="/api/financial/cycles",
        payload={"start_date": start, "end_date": end, "market_index": index},
    )


def get_tarot_daily() -> dict[str, Any]:
    return call_endpoint(kind="tarot_daily", endpoint="/api/tarot/divination/daily", method="GET")


def get_tarot_spread(spread_id: str, deck: str = "rws") -> dict[str, Any]:
    return call_endpoint(
        kind="tarot_spread",
        endpoint="/api/tarot/divination/spread",
        method="GET",
        query={"spread_id": spread_id, "deck_type": deck, "allow_reversed": "false"},
    )


def get_tarot_3card() -> dict[str, Any]:
    """
    Get a 3-card tarot spread: Past, Present, Future.
    This is a convenience wrapper around get_tarot_spread.
    """
    return get_tarot_spread(spread_id="past_present_future", deck="rws")


def get_tarot_single() -> dict[str, Any]:
    return call_endpoint(kind="tarot_single", endpoint="/api/tarot/divination/single", method="GET")


def _load_validated_profile(profile_id: str | None = None) -> dict[str, Any]:
    profile = load_profile(profile_id=profile_id)
    validation = validate_profile(profile)
    if not validation["ok"]:
        profile["validation"] = validation
    return profile


def _add_profile_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", help="Profile ID to use; defaults to the active Oracle profile")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Oracle Astrovisor client")
    subparsers = parser.add_subparsers(dest="command", required=True)

    natal = subparsers.add_parser("natal")
    _add_profile_argument(natal)

    transit = subparsers.add_parser("transits")
    _add_profile_argument(transit)
    transit.add_argument("--date", dest="date_value", default=date.today().isoformat())

    calendar = subparsers.add_parser("calendar")
    _add_profile_argument(calendar)
    calendar.add_argument("--start", required=True)
    calendar.add_argument("--end", required=True)

    harmonics = subparsers.add_parser("harmonics")
    _add_profile_argument(harmonics)

    minor = subparsers.add_parser("minor-aspects")
    _add_profile_argument(minor)

    solar = subparsers.add_parser("solar-return")
    _add_profile_argument(solar)
    solar.add_argument("--year", type=int, default=datetime.now(timezone.utc).year)

    overlay = subparsers.add_parser("lunation-overlay")
    _add_profile_argument(overlay)
    overlay.add_argument("--year", type=int, default=datetime.now(timezone.utc).year)

    returns = subparsers.add_parser("planetary-returns")
    _add_profile_argument(returns)
    returns.add_argument("--start", required=True)
    returns.add_argument("--end", required=True)

    profections = subparsers.add_parser("profections")
    _add_profile_argument(profections)

    numerology = subparsers.add_parser("numerology")
    _add_profile_argument(numerology)

    chakra = subparsers.add_parser("chakra")
    _add_profile_argument(chakra)

    finance = subparsers.add_parser("financial-cycles")
    finance.add_argument("--start", required=True)
    finance.add_argument("--end", required=True)
    finance.add_argument("--index", default="SPX")

    tarot_daily = subparsers.add_parser("tarot-daily")
    _add_profile_argument(tarot_daily)

    spread = subparsers.add_parser("tarot-spread")
    _add_profile_argument(spread)
    spread.add_argument("--spread-id", default="three_cards")
    spread.add_argument("--deck", default="rws")

    tarot_single = subparsers.add_parser("tarot-single")
    _add_profile_argument(tarot_single)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    profile = _load_validated_profile(getattr(args, "profile", None))

    if args.command == "natal":
        result = get_natal_chart(profile)
    elif args.command == "transits":
        result = get_transits(profile, args.date_value)
    elif args.command == "calendar":
        result = get_calendar_predictions(profile, args.start, args.end)
    elif args.command == "harmonics":
        result = get_harmonics(profile)
    elif args.command == "minor-aspects":
        result = get_minor_aspects(profile)
    elif args.command == "solar-return":
        result = get_solar_return(profile, args.year)
    elif args.command == "lunation-overlay":
        result = get_lunation_overlay(profile, args.year)
    elif args.command == "planetary-returns":
        result = get_planetary_returns(profile, args.start, args.end)
    elif args.command == "profections":
        result = get_profections(profile)
    elif args.command == "numerology":
        result = get_numerology(profile)
    elif args.command == "chakra":
        result = get_chakra(profile)
    elif args.command == "financial-cycles":
        result = get_financial_cycles(args.start, args.end, args.index)
    elif args.command == "tarot-daily":
        result = get_tarot_daily()
    elif args.command == "tarot-spread":
        result = get_tarot_spread(args.spread_id, args.deck)
    elif args.command == "tarot-single":
        result = get_tarot_single()
    else:
        result = _error_wrapper("unknown", args.command, "Unknown command")

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
