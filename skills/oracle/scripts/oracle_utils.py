from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

HOME = Path.home()
HERMES_DIR = Path(os.environ.get("HERMES_HOME", HOME / ".hermes")).expanduser()
ORACLE_STATE_DIR = Path(
    os.environ.get("ORACLE_STATE_DIR", HERMES_DIR / "oracle")
).expanduser()
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

DEFAULTS_DIR = ORACLE_STATE_DIR / "defaults"
PROFILES_DIR = ORACLE_STATE_DIR / "profiles"
PROFILES_REGISTRY_PATH = ORACLE_STATE_DIR / "profiles.json"
ACTIVE_PROFILE_PATH = ORACLE_STATE_DIR / "active_profile.json"

CACHE_DIR = ORACLE_STATE_DIR / "cache"
REPORTS_DIR = ORACLE_STATE_DIR / "reports"
JOURNAL_DIR = ORACLE_STATE_DIR / "journal"

LEGACY_USER_PROFILE_PATH = ORACLE_STATE_DIR / "user_profile.json"
LEGACY_CONSENT_PATH = ORACLE_STATE_DIR / "consent.yaml"
LEGACY_SCORING_WEIGHTS_PATH = ORACLE_STATE_DIR / "scoring_weights.yaml"

USER_PROFILE_PATH = LEGACY_USER_PROFILE_PATH
CONSENT_PATH = LEGACY_CONSENT_PATH
DEFAULT_CONSENT_PATH = DEFAULTS_DIR / "consent.yaml"
SCORING_WEIGHTS_PATH = DEFAULTS_DIR / "scoring_weights.yaml"

ENV_PATH = ORACLE_STATE_DIR / ".env"
ENV_EXAMPLE_PATH = ORACLE_STATE_DIR / ".env.example"
GOOGLE_API_PATH = (
    HERMES_DIR
    / "skills"
    / "productivity"
    / "google-workspace"
    / "scripts"
    / "google_api.py"
)
DEFAULT_TIMEOUT = 60
PROFILE_SUBDIRS = ("cache", "reports", "journal")

DEFAULT_CONSENT = {
    "consent_version": 2,
    "use_hermes_google_default": True,
    "gmail_read": True,
    "gmail_send": False,
    "calendar_read": True,
    "calendar_write": False,
    "store_cached_summaries": True,
    "journal_reflections": True,
    "requires_confirmation_for_external_actions": True,
    "ephemeris_data": True,
    "ephemeris_planetary": True,
}

DEFAULT_SCORING_WEIGHTS_TEXT = """# Oracle Scoring Weights
# Used by oracle_scoring.py to rank timing windows.
# Keys here should align with the active profile life_domains map.

communication:
  mercury_weight: 0.5
  moon_weight: 0.2
  jupiter_weight: 0.2
  saturn_penalty: 0.1
  mercury_rx_penalty: 0.8
  void_of_course_penalty: 0.6

relationships:
  venus_weight: 0.5
  moon_weight: 0.3
  mars_penalty: 0.2
  neptune_boost: 0.1

finance:
  venus_weight: 0.4
  jupiter_weight: 0.4
  saturn_weight: 0.2
  mercury_rx_penalty: 0.5

creativity:
  venus_weight: 0.4
  neptune_weight: 0.3
  moon_weight: 0.2
  jupiter_boost: 0.1

rest:
  moon_weight: 0.5
  neptune_weight: 0.3
  saturn_release: 0.2

launches:
  mercury_rx_penalty: 0.8
  moon_phase_weight: 0.3
  jupiter_weight: 0.3
  eclipse_penalty: 0.5
  mars_boost: 0.2

decisive_action:
  mars_weight: 0.4
  sun_weight: 0.3
  jupiter_weight: 0.2
  saturn_weight: 0.1
  mercury_rx_penalty: 0.3

health:
  sun_weight: 0.35
  moon_weight: 0.25
  saturn_weight: 0.15
  mars_penalty: 0.1
  rest_boost: 0.15

spiritual:
  neptune_weight: 0.35
  moon_weight: 0.25
  jupiter_weight: 0.2
  saturn_weight: 0.1
  eclipse_boost: 0.1
"""


class OracleHTTPError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")


def iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def default_profile_registry() -> dict[str, Any]:
    return {
        "version": 1,
        "active_profile_id": None,
        "profiles": [],
    }


def default_active_profile_payload() -> dict[str, Any]:
    return {"active_profile_id": None}


def ensure_runtime_dirs(profile_id: str | None = None) -> None:
    ORACLE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULTS_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)

    if not DEFAULT_CONSENT_PATH.exists():
        save_simple_yaml(
            DEFAULT_CONSENT_PATH,
            default_consent_data(),
            header="# Oracle default consent template\n# Per-profile consent files inherit these values by default.",
        )

    if not SCORING_WEIGHTS_PATH.exists():
        SCORING_WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        if (
            LEGACY_SCORING_WEIGHTS_PATH.exists()
            and LEGACY_SCORING_WEIGHTS_PATH != SCORING_WEIGHTS_PATH
        ):
            SCORING_WEIGHTS_PATH.write_text(
                LEGACY_SCORING_WEIGHTS_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        else:
            SCORING_WEIGHTS_PATH.write_text(
                DEFAULT_SCORING_WEIGHTS_TEXT.rstrip() + "\n", encoding="utf-8"
            )

    if not PROFILES_REGISTRY_PATH.exists():
        save_json_file(PROFILES_REGISTRY_PATH, default_profile_registry())
    if not ACTIVE_PROFILE_PATH.exists():
        save_json_file(ACTIVE_PROFILE_PATH, default_active_profile_payload())

    if profile_id:
        ensure_profile_dirs(profile_id)


def load_env_file(path: Path | None = None) -> dict[str, str]:
    target = path or ENV_PATH
    values: dict[str, str] = {}
    if not target.exists():
        return values
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_env(key: str, default: str | None = None) -> str | None:
    env_file_values = load_env_file()
    return os.environ.get(key) or env_file_values.get(key) or default


def resolve_token_alias(default: str | None = None) -> str | None:
    return None


def validate_api_key() -> dict[str, Any]:
    return {
        "valid": True,
        "error": None,
        "message": "Ephemeris API requires no authentication",
    }


def load_json_file(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {} if default is None else default
    return json.loads(text)


def save_json_file(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def normalize_profile_registry(registry: dict[str, Any] | None) -> dict[str, Any]:
    payload = registry if isinstance(registry, dict) else {}
    profiles = payload.get("profiles")
    normalized_profiles = (
        [item for item in profiles if isinstance(item, dict)]
        if isinstance(profiles, list)
        else []
    )
    active_profile_id = payload.get("active_profile_id")
    profile_ids = {
        str(item.get("id")) for item in normalized_profiles if item.get("id")
    }
    if active_profile_id not in profile_ids:
        active_profile_id = (
            normalized_profiles[0].get("id") if normalized_profiles else None
        )
    return {
        "version": int(payload.get("version") or 1),
        "active_profile_id": active_profile_id,
        "profiles": normalized_profiles,
    }


def load_profile_registry() -> dict[str, Any]:
    ensure_runtime_dirs()
    registry = normalize_profile_registry(
        load_json_file(PROFILES_REGISTRY_PATH, default=default_profile_registry())
    )
    if registry != load_json_file(
        PROFILES_REGISTRY_PATH, default=default_profile_registry()
    ):
        save_json_file(PROFILES_REGISTRY_PATH, registry)
    return registry


def save_profile_registry(registry: dict[str, Any]) -> dict[str, Any]:
    ensure_runtime_dirs()
    normalized = normalize_profile_registry(registry)
    save_json_file(PROFILES_REGISTRY_PATH, normalized)
    return normalized


def get_active_profile_id() -> str | None:
    ensure_runtime_dirs()
    registry = load_profile_registry()
    profile_ids = {
        str(item.get("id")) for item in registry.get("profiles", []) if item.get("id")
    }
    active_state = load_json_file(
        ACTIVE_PROFILE_PATH, default=default_active_profile_payload()
    )
    active_profile_id = active_state.get("active_profile_id")

    if active_profile_id in profile_ids:
        return str(active_profile_id)
    if registry.get("active_profile_id") in profile_ids:
        resolved = str(registry["active_profile_id"])
        save_json_file(ACTIVE_PROFILE_PATH, {"active_profile_id": resolved})
        return resolved
    if profile_ids:
        fallback = str(registry["profiles"][0]["id"])
        set_active_profile_id(fallback)
        return fallback
    save_json_file(ACTIVE_PROFILE_PATH, default_active_profile_payload())
    return None


def set_active_profile_id(profile_id: str | None) -> None:
    ensure_runtime_dirs()
    save_json_file(ACTIVE_PROFILE_PATH, {"active_profile_id": profile_id})
    registry = load_profile_registry()
    registry["active_profile_id"] = profile_id
    save_profile_registry(registry)


def slugify_profile_id(name: str, fallback: str = "profile") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug or fallback


def get_profile_dir(profile_id: str) -> Path:
    if not profile_id:
        raise ValueError("profile_id is required")
    return PROFILES_DIR / profile_id


def get_profile_paths(profile_id: str) -> dict[str, Path]:
    profile_dir = get_profile_dir(profile_id)
    return {
        "dir": profile_dir,
        "profile_path": profile_dir / "profile.json",
        "consent_path": profile_dir / "consent.yaml",
        "cache_dir": profile_dir / "cache",
        "reports_dir": profile_dir / "reports",
        "journal_dir": profile_dir / "journal",
    }


def ensure_profile_dirs(profile_id: str) -> dict[str, Path]:
    paths = get_profile_paths(profile_id)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    for key in ("cache_dir", "reports_dir", "journal_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def get_cache_dir(profile_id: str | None = None) -> Path:
    resolved = profile_id or get_active_profile_id()
    return get_profile_paths(resolved)["cache_dir"] if resolved else CACHE_DIR


def get_reports_dir(profile_id: str | None = None) -> Path:
    resolved = profile_id or get_active_profile_id()
    return get_profile_paths(resolved)["reports_dir"] if resolved else REPORTS_DIR


def get_journal_dir(profile_id: str | None = None) -> Path:
    resolved = profile_id or get_active_profile_id()
    return get_profile_paths(resolved)["journal_dir"] if resolved else JOURNAL_DIR


def default_consent_data() -> dict[str, Any]:
    return deepcopy(DEFAULT_CONSENT)


def _parse_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "none", "None", "~"}:
        return None
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError:
            pass
    if re.fullmatch(r"-?\d+\.\d+", value):
        try:
            return float(value)
        except ValueError:
            pass
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def load_simple_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    lines = path.read_text(encoding="utf-8").splitlines()
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if ":" not in stripped:
            continue

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        parent = stack[-1][1]
        if value == "":
            node: dict[str, Any] = {}
            parent[key] = node
            stack.append((indent, node))
        else:
            parent[key] = _parse_scalar(value)

    return root if root else ({} if default is None else default)


def dump_simple_yaml(data: Any, indent: int = 0) -> str:
    spaces = " " * indent
    if isinstance(data, dict):
        lines: list[str] = []
        for key, value in data.items():
            if isinstance(value, dict):
                lines.append(f"{spaces}{key}:")
                lines.append(dump_simple_yaml(value, indent + 2))
            else:
                lines.append(f"{spaces}{key}: {format_yaml_scalar(value)}")
        return "\n".join(lines)
    if isinstance(data, list):
        return "\n".join(f"{spaces}- {format_yaml_scalar(item)}" for item in data)
    return f"{spaces}{format_yaml_scalar(data)}"


def format_yaml_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text or any(ch in text for ch in [":", "#", "\n"]):
        return json.dumps(text)
    return text


def save_simple_yaml(path: Path, data: Any, header: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dump_simple_yaml(data).rstrip() + "\n"
    if header:
        body = header.rstrip() + "\n\n" + body
    path.write_text(body, encoding="utf-8")


def stable_hash(*parts: Any) -> str:
    normalized = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def cache_file_path(
    kind: str, key_parts: Iterable[Any], cache_dir: Path | None = None
) -> Path:
    digest = stable_hash(kind, list(key_parts))
    base_dir = cache_dir or CACHE_DIR
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"{kind}-{digest}.json"


def load_cache(
    kind: str,
    key_parts: Iterable[Any],
    ttl_seconds: int | None,
    cache_dir: Path | None = None,
) -> dict[str, Any] | None:
    path = cache_file_path(kind, key_parts, cache_dir=cache_dir)
    if not path.exists():
        return None
    data = load_json_file(path, default={})
    if ttl_seconds is None:
        return data
    created_at = data.get("cache_meta", {}).get("created_at")
    if not created_at:
        return None
    try:
        created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    age_seconds = (
        datetime.now(timezone.utc) - created_dt.astimezone(timezone.utc)
    ).total_seconds()
    if age_seconds > ttl_seconds:
        return None
    return data


def save_cache(
    kind: str,
    key_parts: Iterable[Any],
    payload: dict[str, Any],
    cache_dir: Path | None = None,
) -> Path:
    path = cache_file_path(kind, key_parts, cache_dir=cache_dir)
    payload = dict(payload)
    payload.setdefault("cache_meta", {})
    payload["cache_meta"].setdefault("created_at", iso_now())
    save_json_file(path, payload)
    return path


DEFAULT_USER_AGENT = "Oracle/1.0"


def http_json_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: Any = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Any:
    raw_data = None
    request_headers = headers.copy() if headers else {}
    request_headers.setdefault("User-Agent", DEFAULT_USER_AGENT)

    if payload is not None:
        raw_data = (
            json.dumps(payload).encode("utf-8")
            if not isinstance(payload, (bytes, bytearray))
            else payload
        )
        request_headers.setdefault("Content-Type", "application/json")

    request_obj = urllib_request.Request(
        url, data=raw_data, headers=request_headers, method=method.upper()
    )
    try:
        with urllib_request.urlopen(request_obj, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise OracleHTTPError(exc.code, body, url) from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"Network error calling {url}: {exc}") from exc

    stripped = body.strip()
    if not stripped:
        return {}
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return {"raw": stripped}


def query_url(base_url: str, query: dict[str, Any] | None = None) -> str:
    if not query:
        return base_url
    encoded = urllib_parse.urlencode({k: v for k, v in query.items() if v is not None})
    return f"{base_url}?{encoded}"


def recursive_find_values(data: Any, key_names: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in key_names:
                found.append(value)
            found.extend(recursive_find_values(value, key_names))
    elif isinstance(data, list):
        for item in data:
            found.extend(recursive_find_values(item, key_names))
    return found


def recursive_find_first(data: Any, key_names: set[str], default: Any = None) -> Any:
    values = recursive_find_values(data, key_names)
    return values[0] if values else default


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


# ----------------------------------------------------------------------
# Daily Brief & Cosmic Snapshot Generation
# ----------------------------------------------------------------------


def get_transits_for_datetime(
    dt: str, lat: float, lon: float, location: str, tz: str
) -> dict:
    """Fetch ephemeris data for a given datetime using Ephemeris API."""
    import requests

    url = "https://ephemeris.fyi/ephemeris/get_ephemeris_data"
    params = {
        "latitude": lat,
        "longitude": lon,
        "datetime": dt,
    }
    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Ephemeris error {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def get_solar_return(
    year: int, birth_dt: str, lat: float, lon: float, location: str, tz: str
) -> dict:
    """Fetch ephemeris data for solar return date using Ephemeris API."""
    import requests

    target_dt = f"{year}-06-21T12:00:00"
    url = "https://ephemeris.fyi/ephemeris/get_ephemeris_data"
    params = {
        "latitude": lat,
        "longitude": lon,
        "datetime": target_dt,
    }
    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Ephemeris error {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def generate_cosmic_snapshot(profile: dict) -> str:
    """
    Generate a concise 3-6 sentence daily brief summary for the Oracle menu header.
    Combines today's ephemeris data with the user's natal chart.
    """
    import requests

    birth = profile.get("birth_chart", {})
    lat = birth.get("latitude")
    lon = birth.get("longitude")
    location = birth.get("location", "")
    tz = birth.get("timezone", "America/New_York")

    now = datetime.now()
    dt_now = now.strftime("%Y-%m-%dT%H:%M:%S") + tz_to_offset(tz)

    try:
        url = "https://ephemeris.fyi/ephemeris/get_ephemeris_data"
        params = {"latitude": lat, "longitude": lon, "datetime": dt_now}
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            return f"Daily brief unavailable: Ephemeris error {resp.status_code}"
        data = resp.json()
        planets = data.get("bodies", data)

        def get_longitude(body_key):
            body = planets.get(body_key, {})
            if isinstance(body, dict):
                return body.get("longitude", 0)
            return 0

        def get_sign(body_key):
            body = planets.get(body_key, {})
            if isinstance(body, dict):
                sign = body.get("sign", "Unknown")
                if isinstance(sign, dict):
                    return sign.get("name", "Unknown")
                return sign
            return "Unknown"

        sun_long = get_longitude("Sun")
        moon_long = get_longitude("Moon")
        moon_sign = get_sign("Moon")
        mercury = planets.get("Mercury", {})
        if isinstance(mercury, dict):
            mercury_retrograde = mercury.get(
                "is_retrograde", mercury.get("retrograde", False)
            )
        else:
            mercury_retrograde = False
    except Exception as e:
        return f"Daily brief unavailable: {e}"

    phase_angle = (moon_long - sun_long) % 360

    if phase_angle < 7.5 or phase_angle >= 352.5:
        phase_name = "New Moon"
    elif phase_angle < 52.5:
        phase_name = "Waxing Crescent"
    elif phase_angle < 97.5:
        phase_name = "First Quarter"
    elif phase_angle < 142.5:
        phase_name = "Waxing Gibbous"
    elif phase_angle < 187.5:
        phase_name = "Full Moon"
    elif phase_angle < 232.5:
        phase_name = "Waning Gibbous"
    elif phase_angle < 277.5:
        phase_name = "Last Quarter"
    elif phase_angle < 322.5:
        phase_name = "Waning Crescent"
    else:
        phase_name = "New Moon"

    mercury_rx = "retrograde" if mercury_retrograde else "direct"

    year = now.year
    try:
        solar_url = "https://ephemeris.fyi/ephemeris/get_ephemeris_data"
        solar_dt = f"{year}-06-21T12:00:00"
        solar_resp = requests.get(
            solar_url,
            params={"latitude": lat, "longitude": lon, "datetime": solar_dt},
            timeout=30,
        )
        if solar_resp.status_code == 200:
            solar_data = solar_resp.json()
            solar_bodies = solar_data.get("bodies", solar_data)
            solar_sun = solar_bodies.get("Sun", {})
            solar_moon = solar_bodies.get("Moon", {})
            year_theme = f"a year of {phase_name.lower().replace(' moon', '')} energy"
            house_focus = []
        else:
            year_theme = "a year of growth"
            house_focus = []
    except Exception:
        year_theme = "a year of growth"
        house_focus = []

    tone = "balanced"

    parts = []
    parts.append(
        f"Today the cosmos reflects with {phase_name} energy and Moon in {moon_sign}."
    )

    if "New Moon" in phase_name or "First Quarter" in phase_name:
        parts.append("This is a time for new beginnings and forward motion.")
    elif "Full Moon" in phase_name or "Last Quarter" in phase_name:
        parts.append(
            f"{phase_name} invites release and completion of what no longer serves you."
        )
    else:
        parts.append(f"The {phase_name} supports steady progress and reflection.")

    if mercury_rx == "retrograde":
        parts.append(
            "Mercury retrograde turns your attention inward: focus on reviewing, revising, and completing unfinished business."
        )
    else:
        parts.append(
            "Mercury is direct — communication flows clearly and new initiatives are favored."
        )

    parts.append(f"The energy is {tone}. Trust the flow.")

    return " ".join(parts)


def tz_to_offset(tz: str) -> str:
    """Convert timezone name to offset string like -04:00."""
    import zoneinfo

    try:
        tzobj = zoneinfo.ZoneInfo(tz)
        now = datetime.now(tzobj)
        offset = now.strftime("%z")
        return offset
    except Exception:
        return "-0500"


# ----------------------------------------------------------------------
# Ephemeris API - Primary Data Source
# ----------------------------------------------------------------------
# Oracle uses the Ephemeris API at https://ephemeris.fyi for all
# astrological data including planetary positions, moon phases,
# aspects, zodiac signs, and daily events.
# No authentication is required.
# ----------------------------------------------------------------------

import subprocess
import os


def _run_natal_mcp(command: list[str], timeout: int = 30) -> dict:
    """
    Run a natal-mcp command and return parsed JSON output.
    natal-mcp must be in PATH or at /opt/anaconda3/bin/natal-mcp
    """
    natal_mcp_path = os.environ.get("NATAL_MCP_PATH", "/opt/anaconda3/bin/natal-mcp")
    if not os.path.exists(natal_mcp_path):
        # Try PATH
        for p in os.environ.get("PATH", "").split(":"):
            candidate = os.path.join(p, "natal-mcp")
            if os.path.exists(candidate):
                natal_mcp_path = candidate
                break

    try:
        result = subprocess.run(
            [natal_mcp_path] + command, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            raise RuntimeError(f"natal-mcp error: {result.stderr}")

        # Parse JSON from stdout
        import re

        json_match = re.search(r"\{.*\}", result.stdout, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return {"raw": result.stdout}
    except subprocess.TimeoutExpired:
        raise RuntimeError("natal-mcp timed out")
    except Exception as e:
        raise RuntimeError(f"natal-mcp failed: {e}")


def create_natal_chart_via_mcp(
    name: str,
    birth_date: str,
    birth_time: str,
    latitude: float,
    longitude: float,
    location: str,
    timezone: str,
) -> dict:
    """
    Fallback: Create natal chart using natal-mcp if Astrovisor fails.
    """
    # This would call natal-mcp's create_natal_chart
    # For now, raise to indicate fallback needed
    raise NotImplementedError("natal-mcp fallback not yet implemented - use Astrovisor")


def create_transit_chart_via_mcp(
    name: str,
    transit_date: str,
    latitude: float,
    longitude: float,
    location: str,
    timezone: str,
    birth_date: str = None,
    birth_time: str = None,
) -> dict:
    """
    Fallback: Create transit chart using natal-mcp if Astrovisor fails.
    natal-mcp provides: create_transit_chart
    """
    # natal-mcp typically runs as an MCP server, not CLI
    # This would need to be called via MCP protocol
    # For now, raise to indicate fallback needed
    raise NotImplementedError(
        "natal-mcp transit fallback requires MCP integration. "
        "Use Astrovisor directly or configure natal-mcp in Hermes MCP config."
    )


def get_natal_mcp_available() -> bool:
    """Check if natal-mcp is configured and available."""
    # Check if natal is in MCP config
    config_path = os.path.expanduser("~/.hermes/config.yaml")
    if os.path.exists(config_path):
        with open(config_path) as f:
            content = f.read()
            if "natal" in content.lower():
                return True
    # Check if natal-mcp binary exists
    for path in ["/opt/anaconda3/bin/natal-mcp", "/usr/local/bin/natal-mcp"]:
        if os.path.exists(path):
            return True
    return False


def get_transits_with_cache(
    datetime: str,
    lat: float,
    lon: float,
    location: str,
    tz: str,
    profile_id: str = "user",
    force_refresh: bool = False,
) -> dict:
    """
    Get ephemeris data - uses cache first, then Ephemeris API.
    Cached for 1 hour.
    """
    import time
    import requests

    cache_key = f"ephemeris_{datetime[:10]}"
    cache_dir = ORACLE_STATE_DIR / "profiles" / profile_id / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{cache_key}.json"

    if not force_refresh and cache_file.exists():
        cache_age = time.time() - cache_file.stat().st_mtime
        if cache_age < 3600:
            with open(cache_file) as f:
                return json.load(f)

    try:
        url = "https://ephemeris.fyi/ephemeris/get_ephemeris_data"
        params = {"latitude": lat, "longitude": lon, "datetime": datetime}
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Ephemeris error {resp.status_code}")
        data = resp.json()
        with open(cache_file, "w") as f:
            json.dump(data, f)
        return data
    except Exception as e:
        if cache_file.exists():
            with open(cache_file) as f:
                return json.load(f)
        raise RuntimeError(f"Failed to get ephemeris data: {e}") from e


def get_oracle_menu() -> str:
    """
    Returns the Oracle main menu with all options.
    Update this when adding new features.
    """
    return """
**Oracle Menu:**

1. **Ephemeris - Current Sky** — Live planetary positions and aspects
2. **Daily brief** — Full cosmic weather for today
3. **Weekly outlook** — Best days for launches, relationships, communication, finances  
4. **Natal deep-dive** — Your full birth chart analysis
5. **Timing question** — When to launch/sign/schedule/post
6. **Moon Phase** — Current lunar phase and illumination
7. **Zodiac Sign** — Get zodiac sign for any celestial body
8. **Daily Events** — Rising, culmination, and setting times
9. **Tarot pull** — Daily card or 3-card spread (past/present/future)
10. **Help & About** — Commands, features, engineering docs

**Oracle Star Map:** file:///Users/sc/.hermes/skills/oracle/astro-companion/ui/oracle_chart.html
"""


def get_oracle_help() -> str:
    """
    Returns Oracle help/About section with all commands and features.
    Showcases the full engineering stack for demos/hackathons.
    """
    return """
╔══════════════════════════════════════════════════════════════════════════════╗
║                           ORACLE — ABOUT & HELP                              ║
╚══════════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│  WHAT IS ORACLE?                                                            │
└─────────────────────────────────────────────────────────────────────────────┘

Oracle is a cosmic strategist combining:
  • Ephemeris API (ephemeris.fyi) — primary astrological data source
  • Google Calendar/Gmail integration — context-aware scheduling
  • Interactive 3D Star Map — browser-based chart visualization
  • Terminal rendering — ASCII/Unicode natal wheels, aspect matrices

Oracle uses the Ephemeris API for all planetary positions, moon phases,
aspects, zodiac signs, and daily celestial events.


┌─────────────────────────────────────────────────────────────────────────────┐
│  DATA SOURCES & CAPABILITIES                                                │
└─────────────────────────────────────────────────────────────────────────────┘

  ☉ Natal Charts           — Birth chart calculation (Sun, Moon, planets, 
                              houses, angles, aspects) — cached forever
  ☿ Transits               — Current planetary positions affecting your 
                              natal chart — major aspects, returns, 
                              tension/harmony scores — cached 1hr
  ☽ Harmonics              — Multiples of planetary longitudes revealing
                              hidden natal patterns (2nd-13th harmonics)
  ☛ Minor Aspects          — Quintile, Septile, Novile, Decile, Vigintile
                              — subtle psychological dynamics
  ♈ Solar Returns          — Annual chart, houses, aspects, planetary
                              returns, profections — cached 24hr
  ☐ Solar Return Lunation  — New/Full Moons mapped onto SR houses
  ♆ Numerology             — Life Path, Destiny, Soul, Personality, Maturity
                              + Karmic debts, Personal years, Pythagorean Square
  ☿ Chakra Profile         — 7-chakra energetic balance from birth chart
  ⬡ Tarot/Oracle           — Daily card, single pull, multi-card spreads
                              (RWS, Thoth, Lenormand, Marseille)
  ◈ Market Cycles          — Jupiter-Saturn, Mars-Jupiter, Mercury Rx,
                              lunar phases for trading timing
  ☿ Calendar Predictions   — Multi-day/multi-system astrology forecasts


┌─────────────────────────────────────────────────────────────────────────────┐
│  TERMINAL COMMANDS (oracle_render.py)                                       │
└─────────────────────────────────────────────────────────────────────────────┘

  python oracle_render.py wheel --profile <id>         Natal wheel (Unicode/ASCII)
  python oracle_render.py aspects --profile <id>       Aspect matrix grid
  python oracle_render.py timeline --profile <id>      Transit timeline heatmap
  python oracle_render.py chart --profile <id>         Full chart (wheel + aspects)
  python oracle_render.py reading --profile <id>       Natal reading + live transits
  python oracle_render.py elements --profile <id>     Element balance table
  python oracle_render.py dignities --profile <id>    Dignities table
  python oracle_render.py planet-readings --profile <id>  Planet-by-planet
  python oracle_render.py live --profile <id>          Current planetary positions
  python oracle_render.py moon --profile <id>          Moon sign clock
  python oracle_render.py pulse --profile <id>         Active transit pulse


┌─────────────────────────────────────────────────────────────────────────────┐
│  PROFILE COMMANDS (oracle_profiles.py)                                     │
└─────────────────────────────────────────────────────────────────────────────┘

  python oracle_profiles.py list                         List all profiles
  python oracle_profiles.py add                          Create new profile
  python oracle_profiles.py select <id>                  Switch active profile
  python oracle_profiles.py delete <id>                  Delete profile
  python oracle_profiles.py whoami                       Show active profile
  python oracle_profiles.py onboard                      Run onboarding wizard


┌─────────────────────────────────────────────────────────────────────────────┐
│  CACHING STRATEGY                                                           │
└─────────────────────────────────────────────────────────────────────────────┘

  Natal chart     → cached forever (unless profile changes)
  Transits        → cached 1 hour
  Calendar preds  → cached 6 hours
  Solar/Numerology→ cached 24 hours
  Tarot           → never cached


┌─────────────────────────────────────────────────────────────────────────────┐
│  INTERACTIVE STAR MAP                                                       │
└─────────────────────────────────────────────────────────────────────────────┘

  file:///Users/sc/.hermes/skills/oracle/astro-companion/ui/oracle_chart.html

  Features:
    • Drag/zoom 3D celestial sphere
    • Natal/Transit toggle
    • Planet hover tooltips (meaning + aspects)
    • Show/hide natal angles (ASC/MC)
    • Responsive design


┌─────────────────────────────────────────────────────────────────────────────┐
│  SAFETY & DISCLAIMERS                                                       │
└─────────────────────────────────────────────────────────────────────────────┘

  ✦ Never presents astrology as deterministic fact
  ✦ Never diagnoses medical/psychological conditions
  ✦ Never claims financial certainty
  ✦ Retrogrades = revision opportunity, not panic
  ✦ Unknown birth time = lower certainty flag


╔══════════════════════════════════════════════════════════════════════════════╗
║  Say "menu" anytime to return to the main Oracle menu                        ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""


# ----------------------------------------------------------------------
# Profile & Cache Helpers
# ----------------------------------------------------------------------

import os
import json
from pathlib import Path

ORACLE_STATE_DIR = Path(
    os.environ.get("ORACLE_HOME", Path.home() / ".hermes" / "oracle")
)
PROFILES_DIR = ORACLE_STATE_DIR / "profiles"


def get_profile(profile_id: str = "user") -> dict:
    """Load a profile from disk."""
    profile_path = PROFILES_DIR / profile_id / "profile.json"
    if profile_path.exists():
        with open(profile_path) as f:
            return json.load(f)
    return {}


def save_profile(profile_id: str, profile: dict):
    """Save a profile to disk."""
    profile_path = PROFILES_DIR / profile_id / "profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    with open(profile_path, "w") as f:
        json.dump(profile, f, indent=2)


def get_cached_natal(profile_id: str = "user") -> dict | None:
    """Get cached natal chart from profile, or None if not cached."""
    profile = get_profile(profile_id)
    return profile.get("cached_chart")


def cache_natal(profile_id: str, natal_data: dict):
    """Cache natal chart data in profile."""
    profile = get_profile(profile_id)
    profile["cached_chart"] = natal_data
    save_profile(profile_id, profile)


def get_natal_with_cache(profile_id: str = "user", force_refresh: bool = False) -> dict:
    """
    Get natal chart - uses cache if available, otherwise fetches from API.
    Set force_refresh=True to bypass cache.
    """
    if not force_refresh:
        cached = get_cached_natal(profile_id)
        if cached:
            return cached

    # Fetch from API if no cache
    from . import get_token, get_solar_return

    profile = get_profile(profile_id)
    birth = profile.get("birth_chart", {})
    if not birth:
        raise RuntimeError("No birth chart data in profile")

    birth_dt = f"{birth['date']}T{birth['time']}:00"
    natal = get_solar_return(
        2026,  # any year works for natal
        birth_dt,
        birth.get("latitude"),
        birth.get("longitude"),
        birth.get("location", ""),
        birth.get("timezone", "America/New_York"),
    )

    # Cache it
    cache_natal(profile_id, natal.get("data", {}))
    return natal.get("data", {})


# ----------------------------------------------------------------------
# Solar Return & Planetary Returns via natal-mcp (if available)
# ----------------------------------------------------------------------


def get_solar_return_via_mcp(
    birth_dt: str, lat: float, lon: float, location: str, tz: str, year: int
) -> dict:
    """
    Get solar return data via natal-mcp.
    natal-mcp must be configured in Hermes MCP config.
    """
    # This would call the MCP tool if available
    # For now, raise with helpful message
    if not get_natal_mcp_available():
        raise RuntimeError(
            "natal-mcp not configured. Add 'natal' to your MCP servers in ~/.hermes/config.yaml"
        )
    raise NotImplementedError(
        "natal-mcp solar return requires MCP tool call. "
        "Use: tools.create_solar_return_chart"
    )


# ----------------------------------------------------------------------
# Smart API Client with Ephemeris
# ----------------------------------------------------------------------


class OracleAPI:
    """
    Smart API client using Ephemeris API at https://ephemeris.fyi
    """

    def __init__(self, profile: dict = None):
        self.profile = profile

    def get_ephemeris(
        self, lat: float, lon: float, datetime: str | None = None
    ) -> dict:
        """Get full ephemeris data for a location and time."""
        import requests

        url = "https://ephemeris.fyi/ephemeris/get_ephemeris_data"
        params = {"latitude": lat, "longitude": lon}
        if datetime:
            params["datetime"] = datetime

        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_moon_phase(self, datetime: str | None = None) -> dict:
        """Get current moon phase."""
        import requests

        url = "https://ephemeris.fyi/ephemeris/get_moon_phase"
        params = {}
        if datetime:
            params["datetime"] = datetime

        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_planetary_positions(
        self, lat: float, lon: float, datetime: str | None = None
    ) -> dict:
        """Get planetary positions (excluding Sun and Moon)."""
        import requests

        url = "https://ephemeris.fyi/ephemeris/get_planetary_positions"
        params = {"latitude": lat, "longitude": lon}
        if datetime:
            params["datetime"] = datetime

        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def calculate_aspects(
        self, lat: float, lon: float, datetime: str | None = None, orb: float = 8.0
    ) -> dict:
        """Calculate astrological aspects."""
        import requests

        url = "https://ephemeris.fyi/ephemeris/calculate_aspects"
        params = {"latitude": lat, "longitude": lon, "orb": orb}
        if datetime:
            params["datetime"] = datetime

        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
