#!/usr/bin/env python3
"""Simple HTTP server that serves oracle_chart.html and calendar events"""

import http.server
import socketserver
import json
import os
from urllib.parse import urlparse, parse_qs

PORT = 8081

# HTML file path
HTML_FILE = os.path.join(os.path.dirname(__file__), 'oracle_chart.html')

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        
        if parsed.path == '/calendar-events':
            # Fetch calendar events
            params = parse_qs(parsed.query)
            start = params.get('start', [None])[0]
            end = params.get('end', [None])[0]
            
            events = self.get_calendar_events(start, end)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(events).encode())
            return
        
        elif parsed.path == '/natal-data':
            # Serve cached natal data from profiles.json
            natal = self.get_cached_natal()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(natal).encode())
            return
        
        else:
            # Serve static files
            return super().do_GET()
    
    def get_cached_natal(self):
        """Load cached natal data from profiles.json or profile file"""
        import json
        profiles_path = os.path.expanduser('~/.hermes/oracle/profiles.json')
        try:
            with open(profiles_path) as f:
                data = json.load(f)
            profiles = data.get('profiles', [])
            if profiles:
                profile = profiles[0]
                # Check for cached_data in profiles.json first
                cached = profile.get('cached_data', {})
                if cached and cached.get('natal_chart'):
                    cached['_profile'] = {
                        'preferred_name': profile.get('name', ''),
                        'id': profile.get('id', ''),
                    }
                    return cached
                # Otherwise try loading from profile file
                profile_path = profile.get('profile_path', '')
                if profile_path:
                    full_path = os.path.expanduser(f'~/.hermes/oracle/{profile_path}')
                    if os.path.exists(full_path):
                        with open(full_path) as pf:
                            profile_data = json.load(pf)
                        # cached_chart may have planets/houses directly or nested under natal_chart
                        cached = profile_data.get('cached_chart', {})
                        if cached:
                            # Normalize to natal_chart format if needed
                            if 'natal_chart' not in cached and 'planets' in cached:
                                cached = {'natal_chart': cached}
                            cached['_profile'] = {
                                'preferred_name': profile_data.get('preferred_name', profile.get('name', '')),
                                'id': profile.get('id', ''),
                            }
                            return cached
        except Exception:
            pass
        return {}
    
    def get_calendar_events(self, start, end):
        """Fetch events from Google Calendar"""
        import subprocess
        
        # Default to next 7 days if not specified
        if not start:
            from datetime import datetime, timedelta
            start = (datetime.now()).isoformat() + 'Z'
            end = (datetime.now() + timedelta(days=7)).isoformat() + 'Z'
        
        try:
            # Run Google API command
            cmd = [
                'python3', 
                os.path.expanduser('~/.hermes/skills/productivity/google-workspace/scripts/google_api.py'),
                'calendar', 'list',
                '--start', start,
                '--end', end,
                '--max', '20'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                events = json.loads(result.stdout)
                # Transform to simpler format
                return [
                    {
                        'title': e.get('summary', 'Untitled'),
                        'start': e.get('start', ''),
                        'end': e.get('end', ''),
                        'location': e.get('location', ''),
                    }
                    for e in events
                ]
        except Exception as e:
            print(f"Calendar fetch error: {e}")
        
        return []

print(f"Serving on http://localhost:{PORT}")
print(f"Open http://localhost:{PORT}/oracle_chart.html")

os.chdir(os.path.dirname(__file__))
with socketserver.TCPServer(("", PORT), Handler) as httpd:
    httpd.serve_forever()
