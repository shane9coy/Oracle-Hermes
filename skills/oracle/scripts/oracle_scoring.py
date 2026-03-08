from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from oracle_astrology import get_transits
from oracle_profile import load_consent, load_profile
from oracle_utils import GOOGLE_API_PATH, SCORING_WEIGHTS_PATH, load_json_file, load_simple_yaml

DOMAIN_KEYWORDS = {
    "communication": ["call", "meeting", "email", "reply", "pitch", "presentation", "interview", "outreach", "proposal", "conversation"],
    "relationships": ["relationship", "partner", "date", "family", "friend", "repair", "reconcile", "dinner", "anniversary", "love"],
    "finance": ["invoice", "budget", "tax", "payroll", "bank", "expense", "financial", "money", "payment", "contract"],
    "creativity": ["write", "design", "brainstorm", "creative", "draft", "music", "art", "record", "film", "story"],
    "rest": ["rest", "recover", "pause", "therapy", "walk", "meditate", "sleep", "reset", "journal", "yoga"],
    "decisive_action": ["sign", "submit", "ship", "announce", "decide", "approval", "deadline", "launch", "execute", "go-live"],
    "launches": ["launch", "release", "deploy", "publish", "go-live", "announce"],
    "health": ["doctor", "gym", "health", "therapy", "run", "workout", "wellness", "recovery"],
    "spiritual": ["ritual", "tarot", "meditation", "retreat", "prayer", "moon", "altar", "ceremony"],
}

SUPPORTIVE_MOON_SIGNS = {
    "communication": {"Libra", "Gemini", "Leo", "Sagittarius"},
    "relationships": {"Libra", "Cancer", "Taurus"},
    "finance": {"Taurus", "Capricorn", "Cancer", "Virgo"},
    "creativity": {"Pisces", "Leo", "Cancer", "Taurus"},
    "rest": {"Pisces", "Cancer"},
    "decisive_action": {"Aries", "Leo", "Capricorn"},
    "launches": {"Aries", "Leo", "Sagittarius"},
    "health": {"Virgo", "Capricorn", "Cancer"},
    "spiritual": {"Pisces", "Scorpio", "Cancer"},
}


def load_weights(path: Path = SCORING_WEIGHTS_PATH) -> dict[str, Any]:
    return load_simple_yaml(path, default={})


def infer_domain_tags(item: dict[str, Any]) -> list[str]:
    title = " ".join(
        str(item.get(key, ""))
        for key in ("title", "summary", "subject", "description", "snippet")
    ).lower()
    tags = []
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if any(keyword in title for keyword in keywords):
            tags.append(domain)
    if not tags:
        tags.append("communication")
    return tags


def normalize_decision_object(item: dict[str, Any]) -> dict[str, Any]:
    title = item.get("title") or item.get("summary") or item.get("subject") or "Untitled"
    starts_at = (
        item.get("starts_at")
        or item.get("start")
        or (item.get("start", {}) or {}).get("dateTime")
        or item.get("date")
        or datetime.utcnow().isoformat() + "Z"
    )
    return {
        "id": item.get("id") or item.get("threadId") or title.lower().replace(" ", "-"),
        "kind": item.get("kind") or ("email_thread" if item.get("subject") else "calendar_event"),
        "title": title,
        "starts_at": starts_at,
        "domain_tags": item.get("domain_tags") or infer_domain_tags(item),
        "urgency": float(item.get("urgency", 0.5)),
        "raw": item,
    }


def _coerce_astro_context(astro_context: dict[str, Any] | None) -> dict[str, Any]:
    if not astro_context:
        return {}
    if "derived" in astro_context and isinstance(astro_context["derived"], dict):
        return astro_context["derived"]
    return astro_context


def _moon_phase_multiplier(domain: str, moon_phase: str | None) -> float:
    if not moon_phase:
        return 0.0
    phase = moon_phase.lower()
    if domain in {"launches", "decisive_action"} and any(token in phase for token in ["new", "waxing"]):
        return 0.25
    if domain == "rest" and any(token in phase for token in ["waning", "balsamic", "dark"]):
        return 0.2
    if domain == "spiritual" and any(token in phase for token in ["full", "new"]):
        return 0.15
    return 0.0


def _aspect_bonus(domain: str, aspects: list[str]) -> float:
    haystack = " | ".join(aspects).lower()
    bonus = 0.0
    if domain == "communication" and "mercury" in haystack and ("jupiter" in haystack or "trine" in haystack or "sextile" in haystack):
        bonus += 0.25
    if domain == "relationships" and "venus" in haystack:
        bonus += 0.2
    if domain == "creativity" and "neptune" in haystack:
        bonus += 0.15
    if domain == "decisive_action" and "mars" in haystack:
        bonus += 0.15
    if domain == "launches" and "jupiter" in haystack:
        bonus += 0.2
    return bonus


def _risk_penalty(domain: str, astro: dict[str, Any], weight_config: dict[str, Any]) -> tuple[float, list[str]]:
    cautions: list[str] = []
    penalty = 0.0
    mercury_retrograde = astro.get("mercury_retrograde")
    if mercury_retrograde and domain in {"communication", "launches", "decisive_action", "finance"}:
        penalty += float(weight_config.get("mercury_rx_penalty", 0.3))
        cautions.append("Mercury retrograde adds revision energy and can muddle timing-sensitive decisions")
    if astro.get("void_of_course"):
        penalty += float(weight_config.get("void_of_course_penalty", 0.25))
        cautions.append("Void-of-course Moon reduces traction for fresh initiations")
    if astro.get("eclipse_window") and domain in {"launches", "decisive_action", "finance"}:
        penalty += float(weight_config.get("eclipse_penalty", 0.25))
        cautions.append("Eclipse intensity makes irreversible choices feel louder than they are")
    if domain == "relationships":
        aspects = " | ".join(astro.get("aspects", [])).lower()
        if "mars" in aspects and any(token in aspects for token in ["square", "opposition"]):
            penalty += float(weight_config.get("mars_penalty", 0.2))
            cautions.append("Mars tension raises the chance of sharp words or defensiveness")
    return penalty, cautions


def _support_score(domain: str, astro: dict[str, Any], weight_config: dict[str, Any]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    support = 0.0
    moon_sign = astro.get("moon_sign")
    if moon_sign and moon_sign in SUPPORTIVE_MOON_SIGNS.get(domain, set()):
        support += float(weight_config.get("moon_weight", 0.15))
        reasons.append(f"{moon_sign} Moon supports {domain.replace('_', ' ')} work")
    phase_bonus = _moon_phase_multiplier(domain, astro.get("moon_phase"))
    if phase_bonus:
        support += phase_bonus
        reasons.append(f"{astro.get('moon_phase')} Moon supports this kind of action")
    aspect_bonus = _aspect_bonus(domain, astro.get("aspects", []))
    if aspect_bonus:
        support += aspect_bonus
        reasons.append("Current aspects add extra support for this domain")
    return support, reasons


def _score_domain(domain: str, tags: list[str], astro: dict[str, Any], profile: dict[str, Any], weights: dict[str, Any], urgency: float) -> tuple[float, dict[str, Any]]:
    event_domain_weight = 0.55 if domain in tags else 0.15
    user_priority_weight = float((profile.get("life_domains") or {}).get(domain, 0.5))
    weight_config = weights.get(domain, {}) if isinstance(weights.get(domain), dict) else {}
    support, reasons = _support_score(domain, astro, weight_config)
    risk, cautions = _risk_penalty(domain, astro, weight_config)
    urgency_modifier = urgency * 0.2
    total = event_domain_weight + user_priority_weight + support + urgency_modifier - risk
    breakdown = {
        "event_domain_weight": round(event_domain_weight, 3),
        "user_priority_weight": round(user_priority_weight, 3),
        "support": round(support, 3),
        "urgency_modifier": round(urgency_modifier, 3),
        "risk": round(risk, 3),
    }
    return total, {"reasons": reasons, "cautions": cautions, "breakdown": breakdown}


def _score_band(score: float) -> str:
    if score >= 1.9:
        return "green"
    if score >= 1.35:
        return "yellow-green"
    if score >= 0.9:
        return "yellow"
    return "amber"


def _data_source_label(astro_context: dict[str, Any] | None) -> str:
    if not astro_context:
        return "neutral"
    if astro_context.get("ok") is False:
        return "neutral"
    return "cached" if astro_context.get("cached") else "live"


def score_decision_objects(
    decision_objects: list[dict[str, Any]],
    astro_context: dict[str, Any] | None,
    profile: dict[str, Any],
    weights: dict[str, Any],
) -> list[dict[str, Any]]:
    astro = _coerce_astro_context(astro_context)
    normalized = [normalize_decision_object(obj) for obj in decision_objects]
    scored: list[dict[str, Any]] = []
    data_source = _data_source_label(astro_context)

    for obj in normalized:
        tags = obj["domain_tags"]
        domain_results = []
        for domain in weights.keys():
            score, meta = _score_domain(domain, tags, astro, profile, weights, obj["urgency"])
            domain_results.append({"domain": domain, "score": round(score, 3), **meta})
        domain_results.sort(key=lambda item: item["score"], reverse=True)
        best = domain_results[0]
        aggregated_reasons = list(best["reasons"] or [])
        aggregated_cautions = list(best["cautions"] or [])
        for domain_result in domain_results:
            if domain_result["domain"] in tags:
                for reason in domain_result.get("reasons", []):
                    if reason not in aggregated_reasons:
                        aggregated_reasons.append(reason)
                for caution in domain_result.get("cautions", []):
                    if caution not in aggregated_cautions:
                        aggregated_cautions.append(caution)

        scored.append(
            {
                **obj,
                "score": best["score"],
                "score_band": _score_band(best["score"]),
                "best_domain": best["domain"],
                "reasons": aggregated_reasons or ["No major support detected; this is a neutral window"],
                "cautions": aggregated_cautions,
                "score_breakdown": best["breakdown"],
                "all_domains": domain_results,
                "data_source": data_source,
            }
        )

    return sorted(scored, key=lambda item: item["score"], reverse=True)


def _run_google_calendar_list(start_iso: str, end_iso: str) -> list[dict[str, Any]]:
    if not GOOGLE_API_PATH.exists():
        return []
    try:
        completed = subprocess.run(
            [
                "python3",
                str(GOOGLE_API_PATH),
                "calendar",
                "list",
                "--start",
                start_iso,
                "--end",
                end_iso,
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


def _day_bounds(target_date: str, tz_name: str) -> tuple[str, str]:
    zone = ZoneInfo(tz_name)
    start = datetime.fromisoformat(f"{target_date}T00:00:00").replace(tzinfo=zone)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    return start.isoformat(), end.isoformat()


def _build_default_day_windows(target_date: str, tz_name: str) -> list[dict[str, Any]]:
    zone = ZoneInfo(tz_name)
    windows = [("Morning focus window", 9), ("Afternoon action window", 14), ("Evening reflection window", 19)]
    objects = []
    for index, (title, hour) in enumerate(windows, start=1):
        dt = datetime.fromisoformat(f"{target_date}T{hour:02d}:00:00").replace(tzinfo=zone)
        objects.append({
            "id": f"window_{index}",
            "kind": "timing_window",
            "title": title,
            "starts_at": dt.isoformat(),
            "urgency": 0.4,
        })
    return objects


def load_day_decision_objects(target_date: str, profile: dict[str, Any], profile_id: str | None = None) -> list[dict[str, Any]]:
    consent = load_consent(profile_id=profile_id)
    tz_name = profile.get("timezone") or "UTC"
    if consent.get("use_hermes_google_default", True) and consent.get("calendar_read"):
        start_iso, end_iso = _day_bounds(target_date, tz_name)
        events = _run_google_calendar_list(start_iso, end_iso)
        if events:
            return events
    return _build_default_day_windows(target_date, tz_name)


def _load_input_objects(args: argparse.Namespace, profile: dict[str, Any], profile_id: str | None) -> list[dict[str, Any]]:
    if args.input_file:
        payload = load_json_file(Path(args.input_file), default=[])
        return payload if isinstance(payload, list) else []
    if args.date:
        return load_day_decision_objects(args.date, profile, profile_id)
    return []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Oracle scoring engine")
    parser.add_argument("--profile", help="Profile ID to use; defaults to the active Oracle profile")
    parser.add_argument("--date", help="Score a single day of events or fallback windows")
    parser.add_argument("--input-file", help="Path to JSON decision objects")
    parser.add_argument("--astro-file", help="Path to normalized astro JSON")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    profile = load_profile(profile_id=args.profile)
    weights = load_weights()
    decision_objects = _load_input_objects(args, profile, args.profile)

    if args.astro_file:
        astro_context = load_json_file(Path(args.astro_file), default={})
    elif args.date:
        astro_context = get_transits(profile, args.date)
    else:
        astro_context = {}

    scored = score_decision_objects(decision_objects, astro_context, profile, weights)
    print(json.dumps(scored, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
