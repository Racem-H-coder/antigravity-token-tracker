#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SessionStart Hook for Antigravity Token Tracker.
Fires when opening a new window / session in Antigravity.
Injects a markdown token summary banner in the middle of the chat.
"""

import sys
import os
import json

# Ensure scripts directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tracker import calculate_token_stats, generate_markdown_banner, generate_html_dashboard

def main():
    payload = {}
    try:
        if not sys.stdin.isatty():
            raw_input = sys.stdin.read().strip()
            if raw_input:
                payload = json.loads(raw_input)
    except Exception:
        pass

    ws_paths = payload.get("workspacePaths", [])
    current_ws = ws_paths[0] if ws_paths else ""
    current_ws_name = os.path.basename(current_ws.rstrip("/\\")) if current_ws else ""

    try:
        # Calculate stats
        stats = calculate_token_stats(target_workspace=current_ws)
        # Update dashboard HTML
        generate_html_dashboard(stats)
        # Generate markdown banner
        markdown_text = generate_markdown_banner(stats, current_ws_name=current_ws_name)
    except Exception as e:
        markdown_text = f"> ⚠️ **Token Tracker** : Impossible de charger les statistiques ({e})"

    response = {
        "injectSteps": [
            {
                "systemMessage": {
                    "systemMessage": "",
                    "metadata": {
                        "user_markdown": markdown_text
                    }
                }
            }
        ]
    }

    # Write JSON to stdout
    print(json.dumps(response, ensure_ascii=False))

if __name__ == "__main__":
    main()
