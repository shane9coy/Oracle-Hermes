#!/usr/bin/env python3
"""
Oracle Daily Briefing Generator

Generates a daily morning briefing with:
- Cosmic weather (transits)
- Calendar events for today and tomorrow
- Unread emails

Usage:
    python oracle_daily_brief.py [--send-telegram]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
ORACLE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from oracle_astrology import get_transits
from oracle_profile import load_profile
from oracle_utils import load_env_file, get_env, PROFILES_DIR


def get_calendar_events(start_date: str, end_date: str) -> list:
    """Get calendar events from Google Calendar."""
    import subprocess
    
    cmd = [
        "python",
        str(Path.home() / ".hermes/skills/productivity/google-workspace/scripts/google_api.py"),
        "calendar", "list",
        "--start", start_date,
        "--end", end_date
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        events = json.loads(result.stdout)
        return events if events else []
    except:
        return []


def get_unread_emails(max_results: int = 10) -> list:
    """Get unread emails from Gmail."""
    import subprocess
    
    cmd = [
        "python",
        str(Path.home() / ".hermes/skills/productivity/google-workspace/scripts/google_api.py"),
        "gmail", "search",
        "is:unread newer_than:1d",
        "--max", str(max_results)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        emails = json.loads(result.stdout)
        return emails if emails else []
    except:
        return []


def format_briefing(profile: dict, today_events: list, tomorrow_events: list, emails: list, transits: dict) -> str:
    """Format the daily briefing message."""
    
    # Parse today's date
    today = datetime.now(ZoneInfo("America/New_York"))
    today_str = today.strftime("%B %d, %Y")
    tomorrow = today + timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%B %d")
    
    # Extract transit info - handle both cached and direct response
    transit_data = transits.get("data", {}).get("data", {})
    transiting = transit_data.get("transiting_planets", {})
    significant = transit_data.get("significant_transits", [])
    
    # Handle various response structures
    if not transiting and "transits" in transits:
        transiting = transits.get("transits", {}).get("data", {}).get("transiting_planets", {})
        significant = transits.get("transits", {}).get("data", {}).get("significant_transits", [])
    
    moon = transiting.get("Moon", {})
    moon_sign = moon.get("sign", "Unknown")
    moon_degree = moon.get("degree_in_sign", 0)
    
    sun = transiting.get("Sun", {})
    sun_sign = sun.get("sign", "Unknown")  
    sun_degree = sun.get("degree_in_sign", 0)
    
    mercury = transiting.get("Mercury", {})
    mercury_status = "RETROGRADE ♻️" if mercury.get("retrograde") else "direct"
    
    # Get top significant transits
    top_transits = significant[:5] if significant else []
    
    message = f"""☀️ *Good Morning Briefing* — {today_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📅 *TODAY*
"""
    
    if today_events:
        for evt in today_events:
            start = evt.get("start", "")[-8:-3]
            message += f"• {start} — {evt.get('summary', 'Event')}\n"
    else:
        message += "• Clear day — no scheduled events\n"
    
    message += f"""
📅 *TOMORROW* ({tomorrow_str})
"""
    
    if tomorrow_events:
        for evt in tomorrow_events:
            start = evt.get("start", "")[-8:-3]
            message += f"• {start} — {evt.get('summary', 'Event')}\n"
    else:
        message += "• No events scheduled\n"
    
    # Urgent emails
    urgent = [e for e in emails if "security" in e.get("subject", "").lower() or "alert" in e.get("subject", "").lower()]
    other = [e for e in emails if e not in urgent]
    
    message += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📧 *UNREAD EMAILS* ({len(emails)} today)
"""
    
    if urgent:
        message += "\n⚠️ *URGENT/ACTION:*\n"
        for e in urgent:
            subject = e.get("subject", "")[:50]
            sender = e.get("from", "")[:30]
            message += f"• {sender}: {subject}\n"
    
    if other:
        message += "\n📬 *Other:*\n"
        for e in other[:5]:
            subject = e.get("subject", "")[:50]
            sender = e.get("from", "")[:30]
            message += f"• {sender}: {subject}\n"
    
    if not emails:
        message += "• No new emails\n"
    
    # Cosmic weather
    message += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🌙 *COSMIC WEATHER*

*Moon:* ♐ {moon_sign} ({moon_degree:.0f}°)
*Sun:* ♓ {sun_sign} ({sun_degree:.0f}°)
*Mercury:* {mercury_status}
"""
    
    if top_transits:
        message += "\n*Major Transits:*\n"
        for t in top_transits:
            tp = t.get("transit_planet", "")
            aspect = t.get("aspect", "")
            np = t.get("natal_planet", "")
            interp = t.get("interpretation", "")[:60]
            message += f"• {tp} {aspect} {np}: {interp}...\n"
    
    message += """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✨ Have a great day!
"""
    
    return message


def send_telegram(message: str, token: str):
    """Send message to Telegram."""
    import requests
    
    # Check for chat ID in environment first
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not chat_id:
        # Try to get updates from bot
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data.get("ok") and data.get("result"):
                # Get the most recent message from a user (not the bot)
                for update in reversed(data["result"]):
                    if "message" in update:
                        chat_id = update["message"]["chat"]["id"]
                        break
            if not chat_id:
                print("No chat ID found. Please message the bot first!")
                print(f"\nOpen Telegram and message @your_bot_username")
                return None
        except Exception as e:
            print(f"Error getting chat ID: {e}")
            return None
    
    # Send the message
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        result = resp.json()
        if result.get("ok"):
            print("✅ Message sent to Telegram!")
            return result
        else:
            print(f"❌ Error: {result.get('description')}")
            return None
    except Exception as e:
        print(f"Error sending message: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Oracle Daily Briefing")
    parser.add_argument("--send-telegram", action="store_true", help="Send to Telegram")
    parser.add_argument("--get-chat-id", action="store_true", help="Get chat ID from recent messages")
    parser.add_argument("--profile", default="user", help="Profile ID")
    args = parser.parse_args()
    
    # Load profile
    profile = load_profile(args.profile)
    bc = profile.get("birth_chart", {})
    
    # Get today's date info
    today = datetime.now(ZoneInfo("America/New_York"))
    today_date = today.strftime("%Y-%m-%d")
    tomorrow = today + timedelta(days=1)
    tomorrow_date = tomorrow.strftime("%Y-%m-%d")
    
    # Get calendar events
    tz = bc.get("timezone", "America/New_York")
    # Format: YYYY-MM-DDTHH:MM:00-offset
    # For simplicity, use midnight to midnight
    today_start = f"{today_date}T00:00:00-05:00"
    today_end = f"{today_date}T23:59:59-05:00"
    tomorrow_start = f"{tomorrow_date}T00:00:00-05:00"
    tomorrow_end = f"{tomorrow_date}T23:59:59-05:00"
    
    print("Fetching calendar events...")
    today_events = get_calendar_events(today_start, today_end)
    tomorrow_events = get_calendar_events(tomorrow_start, tomorrow_end)
    
    print("Fetching emails...")
    emails = get_unread_emails()
    
    print("Fetching cosmic weather...")
    transits = get_transits(profile)
    
    # Format briefing
    message = format_briefing(profile, today_events, tomorrow_events, emails, transits)
    
    if args.send_telegram:
        token = get_env("TELEGRAM_BOT_TOKEN")
        if token:
            send_telegram(message, token)
        else:
            print("No Telegram token found")
    else:
        print(message)


if __name__ == "__main__":
    main()
