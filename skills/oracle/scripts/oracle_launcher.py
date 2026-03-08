from __future__ import annotations

import argparse
import json
from typing import Any

from oracle_profile import load_profile, validate_profile
from oracle_profiles import get_active_profile, list_profiles, select_profile
from oracle_utils import ensure_runtime_dirs, get_active_profile_id

# Keep quote for JSON output compatibility
ORACLE_QUOTE = "Millionaires study markets, billionaires study stars"


def _profile_name(entry: dict[str, Any], profile: dict[str, Any]) -> str:
    return str(entry.get("name") or profile.get("preferred_name") or entry.get("id") or "Oracle seeker")


def _build_no_profile_context(user_instruction: str) -> str:
    original = user_instruction.strip() or "No additional instruction was provided."
    return "\n".join(
        [
            "Oracle launcher context:",
            "- no active profile is configured yet",
            "- personalized readings require onboarding with name, birth date, birth time, and birthplace",
            "- if the current surface is interactive, run the Oracle onboarding wizard before personalized guidance",
            f"- original_user_instruction: {original}",
            "Please enter Oracle mode, explain what data is needed, and continue safely without inventing chart data.",
        ]
    )


def _build_launcher_context(entry: dict[str, Any], profile: dict[str, Any], validation: dict[str, Any], user_instruction: str) -> str:
    warnings = validation.get("warnings") or []
    errors = validation.get("errors") or []
    original = user_instruction.strip() or "No additional instruction was provided."
    profile_id = entry["id"]
    profile_path = entry.get("profile_path") or f"profiles/{profile_id}/profile.json"
    consent_path = entry.get("consent_path") or f"profiles/{profile_id}/consent.yaml"
    warning_lines = [f"- validation_warning_{index}: {warning}" for index, warning in enumerate(warnings, start=1)]
    error_lines = [f"- validation_error_{index}: {error}" for index, error in enumerate(errors, start=1)]
    base_lines = [
        "Oracle launcher context:",
        f"- active_profile_id: {profile_id}",
        f"- active_profile_name: {_profile_name(entry, profile)}",
        f"- active_profile_path: {profile_path}",
        f"- active_consent_path: {consent_path}",
        f"- profile_validation_ok: {str(validation.get('ok', False)).lower()}",
        "- use_active_profile_automatically: true",
        "- use_hermes_google_default: true",
        f"- original_user_instruction: {original}",
        "Use the active Oracle profile automatically. If the instruction is empty, greet the user in Oracle mode and offer daily brief, weekly review, natal chart, or timing guidance.",
    ]
    return "\n".join(base_lines + warning_lines + error_lines)


def _print_profile_ready(entry: dict[str, Any], validation: dict[str, Any]) -> None:
    print()
    print(f"Oracle is awakening for {entry.get('name', entry['id'])} [{entry['id']}].")
    if validation.get("warnings"):
        print("Profile warnings:")
        for warning in validation["warnings"]:
            print(f"  - {warning}")
    if validation.get("errors"):
        print("Profile errors:")
        for error in validation["errors"]:
            print(f"  - {error}")
    print()


ORACLE_QUOTE = "Millionaires study markets, billionaires study stars"


def launch_oracle_for_cli(*, user_instruction: str = "", interactive: bool = True, plain: bool = False) -> str:
    ensure_runtime_dirs()

    entry: dict[str, Any] | None
    if interactive:
        import subprocess
        try:
            subprocess.run(["figlet", "ORACLE"], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("ORACLE")
        print(f"🔮 {ORACLE_QUOTE}\n")
        entry = get_active_profile()
        if not entry:
            profiles = list_profiles()
            if profiles:
                entry = profiles[0]
    else:
        profiles = list_profiles()
        if not profiles:
            return _build_no_profile_context(user_instruction)
        entry = get_active_profile()
        if not entry:
            entry = select_profile(profiles[0]["id"])

    if not entry:
        return _build_no_profile_context(user_instruction)

    profile = load_profile(profile_id=entry["id"])
    validation = validate_profile(profile)
    if interactive:
        _print_profile_ready(entry, validation)
        return ""  # Just show greeting, no context dump
    return _build_launcher_context(entry, profile, validation, user_instruction)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Oracle launcher and awakening flow")
    parser.add_argument("--user-instruction", default="")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--plain", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print launcher context as JSON")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    context = launch_oracle_for_cli(
        user_instruction=args.user_instruction,
        interactive=not args.non_interactive,
        plain=args.plain,
    )
    if args.json:
        print(json.dumps({"active_profile_id": get_active_profile_id(), "quote": ORACLE_QUOTE, "context": context}, indent=2))
    else:
        print(context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
