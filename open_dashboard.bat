@echo off
title Antigravity Token Tracker
cd /d "%~dp0"
python scripts\tracker.py --html
start "" "dashboard.html"
