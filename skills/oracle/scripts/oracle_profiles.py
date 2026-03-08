from __future__ import annotations

import argparse
import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from oracle_profile import (
    DEFAULT_PROFILE,
    DATE_RE,
    TIME_RE,
    deep_merge,
    geocode_place,
    load_consent as load_legacy_consent,
    resolve_timezone,
    save_consent,
    save_profile,
    validate_profile,
)
from oracle_utils import (
    CACHE_DIR,
    CONSENT_PATH,
    JOURNAL_DIR,
    LEGACY_USER_PROFILE_PATH,
    PROFILES_REGISTRY_PATH,
    REPORTS_DIR,
    USER_PROFILE_PATH,
    ensure_profile_dirs,
    ensure_runtime_dirs,
    get_active_profile_id,
    get_profile_paths,
    iso_now,
    load_json_file,
    load_profile_registry,
    save_profile_registry,
    set_active_profile_id,
    slugify_profile_id,
)


def _registry_with_migration() -> dict[str, Any]:
    migrate_legacy_profile()
    return load_profile_registry()


def _find_profile_entry(profile_id: str) -> dict[str, Any] | None:
    registry = load_profile_registry()
    for entry in registry.get("profiles", []):
        if entry.get("id") == profile_id:
            return entry
    return None


def _next_available_profile_id(base_id: str) -> str:
    registry = load_profile_registry()
    existing = {str(item.get("id")) for item in registry.get("profiles", []) if item.get("id")}
    if base_id not in existing:
        return base_id
    index = 2
    while f"{base_id}-{index}" in existing:
        index += 1
    return f"{base_id}-{index}"


def _profile_has_meaningful_data(profile: dict[str, Any]) -> bool:
    birth = profile.get("birth_chart") or {}
    return any(
        [
            str(profile.get("preferred_name") or "").strip(),
            str(birth.get("date") or "").strip(),
            str(birth.get("time") or "").strip(),
            str(birth.get("location") or "").strip(),
            birth.get("latitude") is not None,
            birth.get("longitude") is not None,
            profile.get("cached_chart") is not None,
            profile.get("last_reading") is not None,
        ]
    )


def _display_name(profile_data: dict[str, Any], profile_id: str) -> str:
    return str(profile_data.get("preferred_name") or profile_id.replace("-", " ").title())


def _sync_active_profile(active_profile_id: str | None) -> None:
    set_active_profile_id(active_profile_id)


def _copy_legacy_state_dirs(profile_id: str) -> None:
    targets = get_profile_paths(profile_id)
    for source, target in (
        (CACHE_DIR, targets["cache_dir"]),
        (REPORTS_DIR, targets["reports_dir"]),
        (JOURNAL_DIR, targets["journal_dir"]),
    ):
        if not source.exists():
            continue
        for item in source.iterdir():
            destination = target / item.name
            if item.is_dir():
                shutil.copytree(item, destination, dirs_exist_ok=True)
            elif item.is_file() and not destination.exists():
                shutil.copy2(item, destination)


def list_profiles() -> list[dict[str, Any]]:
    registry = _registry_with_migration()
    return registry.get("profiles", [])


def get_active_profile() -> dict[str, Any] | None:
    registry = _registry_with_migration()
    active_profile_id = get_active_profile_id() or registry.get("active_profile_id")
    if not active_profile_id:
        return None
    for entry in registry.get("profiles", []):
        if entry.get("id") == active_profile_id:
            return entry
    return None


def create_profile_from_data(
    profile_data: dict[str, Any],
    *,
    consent: dict[str, Any] | None = None,
    profile_id: str | None = None,
    name: str | None = None,
    make_active: bool = True,
) -> dict[str, Any]:
    ensure_runtime_dirs()
    registry = load_profile_registry()
    payload = deep_merge(DEFAULT_PROFILE, profile_data if isinstance(profile_data, dict) else {})
    if name and not payload.get("preferred_name"):
        payload["preferred_name"] = name

    slug_base = profile_id or slugify_profile_id(payload.get("preferred_name") or "primary", fallback="primary")
    resolved_profile_id = _next_available_profile_id(slug_base)
    paths = ensure_profile_dirs(resolved_profile_id)

    save_profile(payload, profile_id=resolved_profile_id)
    save_consent(consent or {}, profile_id=resolved_profile_id)

    now = iso_now()
    entry = {
        "id": resolved_profile_id,
        "name": _display_name(payload, resolved_profile_id),
        "profile_path": f"profiles/{resolved_profile_id}/profile.json",
        "consent_path": f"profiles/{resolved_profile_id}/consent.yaml",
        "created_at": now,
        "last_used_at": now,
    }
    registry.setdefault("profiles", []).append(entry)
    registry["active_profile_id"] = resolved_profile_id if make_active else registry.get("active_profile_id")
    save_profile_registry(registry)
    if make_active:
        _sync_active_profile(resolved_profile_id)
    return entry


def create_profile(
    name: str,
    birth_date: str,
    birth_time: str | None,
    birth_place: str,
    *,
    profile_id: str | None = None,
    make_active: bool = True,
) -> dict[str, Any]:
    if not DATE_RE.match(birth_date):
        raise ValueError("birth_date must be YYYY-MM-DD")

    normalized_time = (birth_time or "").strip()
    time_known = bool(normalized_time)
    if time_known and not TIME_RE.match(normalized_time):
        raise ValueError("birth_time must be HH:MM or omitted")

    geocoded = geocode_place(birth_place)
    timezone_name = resolve_timezone(float(geocoded["latitude"]), float(geocoded["longitude"]))
    payload = deep_merge(
        DEFAULT_PROFILE,
        {
            "preferred_name": name,
            "timezone": timezone_name,
            "coordinates_verified": True,
            "birth_chart": {
                "date": birth_date,
                "time": normalized_time,
                "time_known": time_known,
                "location": geocoded["location"],
                "latitude": geocoded["latitude"],
                "longitude": geocoded["longitude"],
                "timezone": timezone_name,
            },
        },
    )
    validation = validate_profile(payload)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))
    return create_profile_from_data(payload, profile_id=profile_id, name=name, make_active=make_active)


def select_profile(profile_id: str) -> dict[str, Any]:
    registry = load_profile_registry()
    selected: dict[str, Any] | None = None
    for entry in registry.get("profiles", []):
        if entry.get("id") == profile_id:
            entry["last_used_at"] = iso_now()
            selected = entry
            break
    if not selected:
        raise ValueError(f"Unknown profile: {profile_id}")
    registry["active_profile_id"] = profile_id
    save_profile_registry(registry)
    _sync_active_profile(profile_id)
    return selected


def delete_profile(profile_id: str) -> dict[str, Any]:
    registry = load_profile_registry()
    remaining = [entry for entry in registry.get("profiles", []) if entry.get("id") != profile_id]
    if len(remaining) == len(registry.get("profiles", [])):
        raise ValueError(f"Unknown profile: {profile_id}")

    profile_dir = get_profile_paths(profile_id)["dir"]
    if profile_dir.exists():
        shutil.rmtree(profile_dir)

    registry["profiles"] = remaining
    next_active = registry.get("active_profile_id")
    if next_active == profile_id:
        next_active = remaining[0]["id"] if remaining else None
    registry["active_profile_id"] = next_active
    save_profile_registry(registry)
    _sync_active_profile(next_active)
    return {"deleted_profile_id": profile_id, "active_profile_id": next_active, "remaining_profiles": len(remaining)}


def migrate_legacy_profile() -> dict[str, Any] | None:
    ensure_runtime_dirs()
    registry = load_profile_registry()
    if registry.get("profiles"):
        return None
    legacy_profile = load_json_file(USER_PROFILE_PATH, default={})
    if not isinstance(legacy_profile, dict) or not legacy_profile or not _profile_has_meaningful_data(legacy_profile):
        return None
    legacy_consent = load_legacy_consent()
    guessed_name = str(legacy_profile.get("preferred_name") or "primary")
    entry = create_profile_from_data(
        deepcopy(legacy_profile),
        consent=legacy_consent,
        profile_id=slugify_profile_id(guessed_name, fallback="primary"),
        name=guessed_name,
        make_active=True,
    )
    _copy_legacy_state_dirs(entry["id"])
    return entry


def _prompt_nonempty(message: str) -> str:
    while True:
        value = input(message).strip()
        if value:
            return value
        print("Please enter a value.")


def _prompt_birth_date() -> str:
    while True:
        value = input("What is your date of birth? (YYYY-MM-DD): ").strip()
        if DATE_RE.match(value):
            return value
        print("Please use YYYY-MM-DD.")


def _prompt_birth_time() -> str | None:
    while True:
        value = input("What is your time of birth? (HH:MM or unknown): ").strip()
        lowered = value.lower()
        if not value or lowered in {"unknown", "u", "?", "none"}:
            return None
        if TIME_RE.match(value):
            return value
        print("Please use HH:MM or type unknown.")


def onboarding_wizard() -> dict[str, Any]:
    print("\nWho seeks the stars? Let us begin your Oracle profile.\n")
    while True:
        name = _prompt_nonempty("What is your name? ")
        birth_date = _prompt_birth_date()
        birth_time = _prompt_birth_time()
        birth_place = _prompt_nonempty("Where were you born? (City, State/Country): ")
        try:
            entry = create_profile(name, birth_date, birth_time, birth_place, make_active=True)
        except Exception as exc:  # noqa: BLE001
            print(f"Could not create the profile yet: {exc}")
            print("Let’s try that once more.\n")
            continue
        print(f"\nOracle profile created and activated: {entry['name']} ({entry['id']})\n")
        return entry


def _print_profile_choices(profiles: list[dict[str, Any]]) -> None:
    for index, entry in enumerate(profiles, start=1):
        print(f"  {index}. {entry.get('name', entry['id'])} [{entry['id']}]  last used {entry.get('last_used_at', 'unknown')}")


def _choose_existing_profile_interactive() -> dict[str, Any] | None:
    profiles = list_profiles()
    if not profiles:
        print("No Oracle profiles are saved yet.")
        return None
    print("\nChoose an existing Oracle profile:\n")
    _print_profile_choices(profiles)
    while True:
        choice = input("Select a profile number (or press Enter to cancel): ").strip()
        if not choice:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(profiles):
            return select_profile(profiles[int(choice) - 1]["id"])
        print("Please choose a valid number.")


def _delete_profile_interactive() -> None:
    profiles = list_profiles()
    if not profiles:
        print("No Oracle profiles are saved yet.")
        return
    print("\nChoose a profile to delete:\n")
    _print_profile_choices(profiles)
    while True:
        choice = input("Delete which profile number? (or press Enter to cancel): ").strip()
        if not choice:
            return
        if not choice.isdigit() or not (1 <= int(choice) <= len(profiles)):
            print("Please choose a valid number.")
            continue
        entry = profiles[int(choice) - 1]
        confirm = input(f"Type DELETE to remove {entry['name']} [{entry['id']}]: ").strip()
        if confirm != "DELETE":
            print("Delete cancelled.")
            return
        result = delete_profile(entry["id"])
        print(json.dumps(result, indent=2))
        return


def startup_selection_menu() -> dict[str, Any]:
    migrate_legacy_profile()
    while True:
        profiles = list_profiles()
        active = get_active_profile()
        if not profiles:
            print("No Oracle profiles found. Beginning onboarding.")
            return onboarding_wizard()

        print("\nWho seeks the stars?\n")
        if active:
            print(f"Active profile: {active.get('name', active['id'])} [{active['id']}]\n")
        print("  1. Load active profile")
        print("  2. Choose existing profile")
        print("  3. Add new profile")
        print("  4. Delete profile")

        choice = input("Select an option [1]: ").strip() or "1"
        if choice == "1":
            if active:
                return select_profile(active["id"])
            return select_profile(profiles[0]["id"])
        if choice == "2":
            chosen = _choose_existing_profile_interactive()
            if chosen:
                return chosen
            continue
        if choice == "3":
            return onboarding_wizard()
        if choice == "4":
            _delete_profile_interactive()
            continue
        print("Please choose 1, 2, 3, or 4.")


def cmd_list(_: argparse.Namespace) -> int:
    registry = _registry_with_migration()
    print(json.dumps(registry, indent=2))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    if args.name and args.birth_date and args.location:
        birth_time = None if args.birth_time in {None, "", "unknown"} else args.birth_time
        entry = create_profile(args.name, args.birth_date, birth_time, args.location, profile_id=args.profile_id, make_active=True)
    else:
        entry = onboarding_wizard()
    print(json.dumps(entry, indent=2))
    return 0


def cmd_select(args: argparse.Namespace) -> int:
    entry = select_profile(args.profile_id)
    print(json.dumps(entry, indent=2))
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    if not args.yes:
        raise SystemExit("Refusing to delete without --yes")
    result = delete_profile(args.profile_id)
    print(json.dumps(result, indent=2))
    return 0


def cmd_whoami(_: argparse.Namespace) -> int:
    active = get_active_profile()
    if not active:
        print(json.dumps({"active_profile_id": None, "message": "No active Oracle profile"}, indent=2))
        return 0
    print(json.dumps(active, indent=2))
    return 0


def cmd_onboard(_: argparse.Namespace) -> int:
    entry = onboarding_wizard()
    print(json.dumps(entry, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Oracle multi-profile manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List Oracle profiles")
    list_parser.set_defaults(func=cmd_list)

    add_parser = subparsers.add_parser("add", help="Create a new Oracle profile")
    add_parser.add_argument("--name")
    add_parser.add_argument("--birth-date")
    add_parser.add_argument("--birth-time")
    add_parser.add_argument("--location", help="Birthplace as City, State/Country")
    add_parser.add_argument("--profile-id")
    add_parser.set_defaults(func=cmd_add)

    select_parser = subparsers.add_parser("select", help="Select the active Oracle profile")
    select_parser.add_argument("profile_id")
    select_parser.set_defaults(func=cmd_select)

    delete_parser = subparsers.add_parser("delete", help="Delete an Oracle profile")
    delete_parser.add_argument("profile_id")
    delete_parser.add_argument("--yes", action="store_true")
    delete_parser.set_defaults(func=cmd_delete)

    whoami_parser = subparsers.add_parser("whoami", help="Show the active Oracle profile")
    whoami_parser.set_defaults(func=cmd_whoami)

    onboard_parser = subparsers.add_parser("onboard", help="Run the Oracle onboarding wizard")
    onboard_parser.set_defaults(func=cmd_onboard)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
