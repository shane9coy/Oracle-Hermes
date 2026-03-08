#!/usr/bin/env python3
"""Simple HTTP server for Google Calendar API.

Wraps the Google Calendar API for the Oracle Star Map.
Runs on port 8081 by default.

Usage:
    python calendar_server.py [--port 8081]
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Add Google Workspace scripts to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# Import from google_api
HERMES_HOME = os.path.expanduser("~/.hermes")
TOKEN_PATH = os.path.join(HERMES_HOME, "google_token.json")

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]


def get_credentials():
    """Load and refresh credentials from token file."""
    if not os.path.exists(TOKEN_PATH):
        return None

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Save refreshed token
        with open(TOKEN_PATH, 'w') as f:
            f.write(creds.to_json())
    return creds


def build_calendar_service():
    from googleapiclient.discovery import build
    creds = get_credentials()
    if not creds:
        raise Exception("Not authenticated with Google")
    return build("calendar", "v3", credentials=creds)


def list_events(start, end, max_results=50):
    """List calendar events."""
    service = build_calendar_service()
    
    results = service.events().list(
        calendarId="primary",
        timeMin=start,
        timeMax=end,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = []
    for e in results.get("items", []):
        events.append({
            "id": e.get("id"),
            "title": e.get("summary", "Untitled"),
            "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")),
            "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date", "")),
            "location": e.get("location", ""),
            "description": e.get("description", ""),
            "status": e.get("status", ""),
            "htmlLink": e.get("htmlLink", ""),
        })
    return events


def create_event(summary, description, start_time, end_time):
    """Create a calendar event."""
    service = build_calendar_service()
    
    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_time},
        "end": {"dateTime": end_time},
    }
    
    created = service.events().insert(calendarId="primary", body=event).execute()
    return {
        "id": created.get("id"),
        "link": created.get("htmlLink", ""),
    }


class CalendarHandler(BaseHTTPRequestHandler):
    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()
        
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        
        if path == "/calendar":
            # Get events
            now = datetime.now(timezone.utc)
            
            # Parse start/end from params
            start = params.get("start", [now.isoformat()])[0]
            end = params.get("end", [(now + timedelta(days=14)).isoformat()])[0]
            
            try:
                events = list_events(start, end)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(events).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
                
        elif path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        
        else:
            self.send_response(404)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b"Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == "/calendar/create":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode())
            
            try:
                result = create_event(
                    data.get("summary", ""),
                    data.get("description", ""),
                    data.get("start", {}).get("dateTime", ""),
                    data.get("end", {}).get("dateTime", "")
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        
        else:
            self.send_response(404)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b"Not found")

    def log_message(self, format, *args):
        print(f"[Calendar Server] {args[0]}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Google Calendar HTTP Server")
    parser.add_argument("--port", type=int, default=8081, help="Port to run on")
    args = parser.parse_args()
    
    # Check if authenticated
    try:
        creds = get_credentials()
        if not creds:
            print("⚠️ Not authenticated with Google. Run setup first:")
            print(f"   python {SCRIPT_DIR}/setup.py")
            sys.exit(1)
        print(f"✓ Google Calendar authenticated")
    except Exception as e:
        print(f"⚠️ Google Calendar error: {e}")
    
    server = HTTPServer(("0.0.0.0", args.port), CalendarHandler)
    print(f"🌐 Calendar server running on http://localhost:{args.port}")
    print(f"   GET  /calendar?start=ISO&end=ISO - List events")
    print(f"   POST /calendar/create - Create event")
    print(f"   GET  /health - Health check")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
