#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Token Tracker Engine
Analyzes token usage (input, output, cached) by day, hour, and project.
Generates CLI summaries, Markdown cards, JSON exports, and interactive HTML dashboards.
"""

import os
import sys
import glob
import json
import sqlite3
import urllib.parse
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
import webbrowser
import threading

def get_antigravity_paths():
    """Detects Antigravity directory, SQLite database, and brain directory."""
    home = os.path.expanduser("~")
    base_dir = os.path.join(home, ".gemini", "antigravity")
    db_path = os.path.join(base_dir, "conversation_summaries.db")
    brain_dir = os.path.join(base_dir, "brain")
    return base_dir, db_path, brain_dir

def format_tokens(n):
    """Formats token numbers in human-readable string (e.g. 1.2M, 450k, 120)."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)

def format_cost(cost):
    """Formats cost in USD."""
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"

def calc_cost(inp, out, cached):
    """Calculates estimated cost in USD based on Gemini Flash rates."""
    # $0.075 / 1M prompt, $0.30 / 1M output, $0.01875 / 1M cache
    return round((inp * 0.075 / 1_000_000) + (out * 0.30 / 1_000_000) + (cached * 0.01875 / 1_000_000), 4)

def load_conversation_metadata(db_path):
    """Reads conversation metadata and workspace mappings from SQLite."""
    conv_map = {}
    if not os.path.exists(db_path):
        return conv_map
    
    try:
        uri_path = f"file:{urllib.parse.quote(db_path)}?mode=ro"
        con = sqlite3.connect(uri_path, uri=True, timeout=5.0)
        cur = con.cursor()
        rows = cur.execute("""
            SELECT conversation_id, title, workspace_uris, project_id, last_modified_time 
            FROM conversation_summaries
        """).fetchall()
        for r in rows:
            cid, title, ws_raw, pid, last_mod = r
            ws_name = "Global / Non défini"
            ws_path = ""
            if ws_raw:
                try:
                    ws_list = json.loads(ws_raw)
                    if ws_list and len(ws_list) > 0:
                        raw_uri = ws_list[0]
                        decoded = urllib.parse.unquote(raw_uri)
                        clean = decoded.replace("file:///", "").replace("/", "\\")
                        ws_path = clean
                        ws_name = os.path.basename(clean.rstrip("\\")) or clean
                except Exception:
                    ws_name = str(ws_raw)
            conv_map[cid] = {
                "title": title or "Conversation sans titre",
                "workspace_name": ws_name,
                "workspace_path": ws_path,
                "project_id": pid or "",
                "last_modified": str(last_mod) if last_mod else ""
            }
        con.close()
    except Exception as e:
        pass
    return conv_map

def calculate_token_stats(target_workspace=None):
    """Parses all transcripts and compiles daily, hourly, and project statistics."""
    base_dir, db_path, brain_dir = get_antigravity_paths()
    conv_map = load_conversation_metadata(db_path)
    
    pattern = os.path.join(brain_dir, "*", ".system_generated", "logs", "transcript.jsonl")
    transcript_files = glob.glob(pattern)
    
    stats_by_day = {}
    stats_by_hour = {}
    stats_by_project = {}
    stats_by_conv = {}
    
    total_input = 0
    total_output = 0
    total_cached = 0
    total_calls = 0
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    for tp in transcript_files:
        try:
            cid = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(tp))))
            cinfo = conv_map.get(cid, {
                "title": "Conversation inconnue",
                "workspace_name": "Global / Non défini",
                "workspace_path": "",
                "project_id": "",
                "last_modified": ""
            })
            
            ws_name = cinfo["workspace_name"]
            ws_path = cinfo["workspace_path"]
            
            conv_inp = 0
            conv_out = 0
            conv_cached = 0
            conv_calls = 0
            conv_last_time = ""
            
            with open(tp, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        step = json.loads(line)
                    except Exception:
                        continue
                    
                    inp = step.get("input_tokens", 0) or 0
                    out = step.get("output_tokens", 0) or 0
                    cached = step.get("cache_read_tokens", 0) or 0
                    
                    if inp > 0 or out > 0 or cached > 0:
                        total_input += inp
                        total_output += out
                        total_cached += cached
                        total_calls += 1
                        
                        conv_inp += inp
                        conv_out += out
                        conv_cached += cached
                        conv_calls += 1
                        
                        created_at = step.get("created_at", "")
                        if created_at and len(created_at) >= 13:
                            conv_last_time = created_at
                            day_str = created_at[:10]
                            hour_str = created_at[11:13]
                            hour_key = f"{day_str} {hour_str}h"
                            
                            # Daily metrics
                            if day_str not in stats_by_day:
                                stats_by_day[day_str] = {
                                    "input": 0, "output": 0, "cached": 0, "calls": 0,
                                    "hours": {f"{h:02d}": {"input": 0, "output": 0, "cached": 0, "calls": 0} for h in range(24)}
                                }
                            stats_by_day[day_str]["input"] += inp
                            stats_by_day[day_str]["output"] += out
                            stats_by_day[day_str]["cached"] += cached
                            stats_by_day[day_str]["calls"] += 1
                            
                            # Sub-hour in day (ensure full 24h dict)
                            if hour_str not in stats_by_day[day_str]["hours"]:
                                stats_by_day[day_str]["hours"][hour_str] = {"input": 0, "output": 0, "cached": 0, "calls": 0}
                            stats_by_day[day_str]["hours"][hour_str]["input"] += inp
                            stats_by_day[day_str]["hours"][hour_str]["output"] += out
                            stats_by_day[day_str]["hours"][hour_str]["cached"] += cached
                            stats_by_day[day_str]["hours"][hour_str]["calls"] += 1
                            
                            # Global hour key
                            if hour_key not in stats_by_hour:
                                stats_by_hour[hour_key] = {"input": 0, "output": 0, "cached": 0, "calls": 0}
                            stats_by_hour[hour_key]["input"] += inp
                            stats_by_hour[hour_key]["output"] += out
                            stats_by_hour[hour_key]["cached"] += cached
                            stats_by_hour[hour_key]["calls"] += 1
                        
                        # Project metrics
                        proj_key = ws_name
                        if proj_key not in stats_by_project:
                            stats_by_project[proj_key] = {
                                "workspace_name": ws_name,
                                "workspace_path": ws_path,
                                "input": 0, 
                                "output": 0, 
                                "cached": 0, 
                                "calls": 0,
                                "last_activity": ""
                            }
                        stats_by_project[proj_key]["input"] += inp
                        stats_by_project[proj_key]["output"] += out
                        stats_by_project[proj_key]["cached"] += cached
                        stats_by_project[proj_key]["calls"] += 1
                        if created_at and created_at > stats_by_project[proj_key]["last_activity"]:
                            stats_by_project[proj_key]["last_activity"] = created_at
            
            if conv_calls > 0:
                stats_by_conv[cid] = {
                    "id": cid,
                    "title": cinfo["title"],
                    "workspace": ws_name,
                    "workspace_path": ws_path,
                    "input": conv_inp,
                    "output": conv_out,
                    "cached": conv_cached,
                    "total": conv_inp + conv_out + conv_cached,
                    "calls": conv_calls,
                    "last_activity": conv_last_time or cinfo["last_modified"]
                }
        except Exception:
            continue

    # Enrich daily statistics
    for d, st in stats_by_day.items():
        st["total"] = st["input"] + st["output"] + st["cached"]
        st["cost_usd"] = calc_cost(st["input"], st["output"], st["cached"])
        tot_in = st["input"] + st["cached"]
        st["cache_hit_pct"] = round((st["cached"] / tot_in * 100), 1) if tot_in > 0 else 0.0

    # Enrich project statistics
    grand_total = total_input + total_output + total_cached
    for p, st in stats_by_project.items():
        st["total"] = st["input"] + st["output"] + st["cached"]
        st["cost_usd"] = calc_cost(st["input"], st["output"], st["cached"])
        st["percent_of_total"] = round((st["total"] / grand_total * 100), 1) if grand_total > 0 else 0.0
        tot_in = st["input"] + st["cached"]
        st["cache_hit_pct"] = round((st["cached"] / tot_in * 100), 1) if tot_in > 0 else 0.0

    # Today stats
    today_stats = stats_by_day.get(today_str, {
        "input": 0, "output": 0, "cached": 0, "total": 0, "calls": 0, "cost_usd": 0.0, "cache_hit_pct": 0.0,
        "hours": {f"{h:02d}": {"input": 0, "output": 0, "cached": 0, "calls": 0} for h in range(24)}
    })
    
    # Current hour stats
    current_hour_str = datetime.now().strftime("%H")
    current_hour_stats = today_stats.get("hours", {}).get(current_hour_str, {"input": 0, "output": 0, "cached": 0, "calls": 0})
    current_hour_total = current_hour_stats["input"] + current_hour_stats["output"] + current_hour_stats["cached"]

    # Match target workspace if provided
    matched_workspace_stats = None
    if target_workspace:
        norm_target = target_workspace.replace("/", "\\").rstrip("\\").lower()
        for p, st in stats_by_project.items():
            norm_p_path = st["workspace_path"].replace("/", "\\").rstrip("\\").lower()
            norm_p_name = st["workspace_name"].lower()
            if norm_target in norm_p_path or norm_p_name in norm_target:
                matched_workspace_stats = st
                break

    return {
        "timestamp": datetime.now().isoformat(),
        "today_date": today_str,
        "current_hour": current_hour_str,
        "summary": {
            "total_input": total_input,
            "total_output": total_output,
            "total_cached": total_cached,
            "total_tokens": grand_total,
            "total_calls": total_calls,
            "estimated_cost_usd": calc_cost(total_input, total_output, total_cached),
            "cache_hit_pct": round((total_cached / (total_input + total_cached) * 100), 1) if (total_input + total_cached) > 0 else 0.0
        },
        "today": today_stats,
        "current_hour_stats": {
            "hour": current_hour_str,
            "total": current_hour_total,
            "calls": current_hour_stats["calls"],
            "input": current_hour_stats["input"],
            "output": current_hour_stats["output"],
            "cached": current_hour_stats["cached"]
        },
        "matched_project": matched_workspace_stats,
        "days": stats_by_day,
        "hours": stats_by_hour,
        "projects": stats_by_project,
        "conversations": sorted(stats_by_conv.values(), key=lambda x: x["total"], reverse=True)
    }

def generate_markdown_banner(stats, current_ws_name=""):
    """Generates the Markdown card shown at SessionStart or on `/tokens`."""
    today = stats["today"]
    curr_h = stats["current_hour_stats"]
    summary = stats["summary"]
    proj = stats.get("matched_project")
    proj_name = proj["workspace_name"] if proj else (current_ws_name or "Global / Non défini")
    proj_tokens = format_tokens(proj["total"]) if proj else "0"
    
    today_total = format_tokens(today["total"])
    today_input = format_tokens(today["input"])
    today_output = format_tokens(today["output"])
    today_cached = format_tokens(today["cached"])
    
    hour_total = format_tokens(curr_h["total"])
    hour_calls = curr_h["calls"]
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    plugin_dir = os.path.dirname(script_dir)
    dashboard_html_path = os.path.join(plugin_dir, "dashboard.html").replace("\\", "/")
    
    md = f"""### 📊 Antigravity Token Tracker — Vue Temps Réel

| 📅 Aujourd'hui ({stats['today_date']}) | ⏱️ Heure Actuelle ({curr_h['hour']}h) | 📁 Projet Actif (`{proj_name}`) | 💰 Coût Estimé |
| :--- | :--- | :--- | :--- |
| **{today_total}** ({today['calls']} appels) | **{hour_total}** ({hour_calls} appels) | **{proj_tokens}** tokens | **{format_cost(today['cost_usd'])}** (Aujourd'hui) |

> ⚡ **Détail du jour** : Input: `{today_input}` · Output: `{today_output}` · Cache: `{today_cached}` (**{today['cache_hit_pct']}%** économisé via cache)  
> 📈 **Total Historique** : **{format_tokens(summary['total_tokens'])}** tokens sur **{len(stats['projects'])}** projets ({format_cost(summary['estimated_cost_usd'])})

[👉 **Ouvrir le Dashboard Graphique Complet**](file:///{dashboard_html_path}) · [🔍 **Actualiser (/tokens)**](/tokens)
"""
    return md

def generate_html_dashboard(stats, output_path=None):
    """Generates a standalone, beautiful HTML dashboard with interactive charts."""
    if not output_path:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(os.path.dirname(script_dir), "dashboard.html")

    data_json_str = json.dumps(stats, ensure_ascii=False)
    
    html_content = f"""<!DOCTYPE html>
<html lang="fr" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Antigravity Token Tracker — Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{
      darkMode: 'class',
      theme: {{
        extend: {{
          colors: {{
            brand: {{
              50: '#eef2ff',
              100: '#e0e7ff',
              400: '#818cf8',
              500: '#6366f1',
              600: '#4f46e5',
              900: '#1e1b4b'
            }},
            darkbg: '#0B0F19',
            darkcard: '#111827',
            darkborder: '#1F2937'
          }}
        }}
      }}
    }}
  </script>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}
    .custom-scrollbar::-webkit-scrollbar {{
      width: 6px;
      height: 6px;
    }}
    .custom-scrollbar::-webkit-scrollbar-track {{
      background: transparent;
    }}
    .custom-scrollbar::-webkit-scrollbar-thumb {{
      background: #374151;
      border-radius: 3px;
    }}
    .bar-hover:hover {{
      opacity: 0.85;
      transform: scaleY(1.02);
      transform-origin: bottom;
    }}
  </style>
</head>
<body class="bg-darkbg text-gray-100 min-h-screen custom-scrollbar antialiased">
  <!-- Top Navigation Bar -->
  <header class="border-b border-darkborder bg-darkcard/80 backdrop-blur sticky top-0 z-50 px-6 py-4 flex items-center justify-between">
    <div class="flex items-center space-x-3">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-brand-600 to-cyan-500 flex items-center justify-center shadow-lg shadow-brand-500/20">
        <span class="text-xl">⚡</span>
      </div>
      <div>
        <h1 class="text-lg font-bold tracking-tight text-white flex items-center gap-2">
          Antigravity Token Tracker
          <span class="text-xs px-2 py-0.5 rounded-full bg-brand-500/20 text-brand-400 border border-brand-500/30">v1.0</span>
        </h1>
        <p class="text-xs text-gray-400">Consommation en temps réel · Par Heure, Jour & Projet</p>
      </div>
    </div>
    
    <div class="flex items-center space-x-3">
      <button id="refresh-btn" onclick="location.reload()" class="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-xs font-medium text-gray-200 border border-gray-700 transition">
        <span>🔄</span>
        <span>Rafraîchir</span>
      </button>
      <div class="text-xs px-3 py-1.5 rounded-lg bg-gray-800/60 border border-gray-700/60 text-gray-300">
        Dernière synchro: <span id="sync-time" class="text-brand-400 font-mono font-semibold"></span>
      </div>
    </div>
  </header>

  <!-- Main Content Container -->
  <main class="max-w-7xl mx-auto px-6 py-8 space-y-8">
    
    <!-- KPI Header Cards -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
      <!-- Total Tokens Card -->
      <div class="bg-darkcard border border-darkborder rounded-2xl p-5 shadow-sm relative overflow-hidden">
        <div class="flex justify-between items-start">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wider text-gray-400">Total Consommé</p>
            <h3 id="kpi-total-tokens" class="text-3xl font-extrabold text-white mt-1 font-mono">--</h3>
          </div>
          <span class="p-2.5 rounded-xl bg-brand-500/10 text-brand-400 text-lg border border-brand-500/20">📈</span>
        </div>
        <div class="mt-4 flex items-center justify-between text-xs text-gray-400 border-t border-gray-800/60 pt-3">
          <span>Appels Modèle : <strong id="kpi-total-calls" class="text-gray-200 font-mono">--</strong></span>
          <span class="text-brand-400">Toutes sessions</span>
        </div>
      </div>

      <!-- Today's Tokens Card -->
      <div class="bg-darkcard border border-darkborder rounded-2xl p-5 shadow-sm relative overflow-hidden">
        <div class="flex justify-between items-start">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wider text-gray-400">Aujourd'hui</p>
            <h3 id="kpi-today-tokens" class="text-3xl font-extrabold text-white mt-1 font-mono">--</h3>
          </div>
          <span class="p-2.5 rounded-xl bg-cyan-500/10 text-cyan-400 text-lg border border-cyan-500/20">📅</span>
        </div>
        <div class="mt-4 flex items-center justify-between text-xs text-gray-400 border-t border-gray-800/60 pt-3">
          <span>Appels du jour : <strong id="kpi-today-calls" class="text-gray-200 font-mono">--</strong></span>
          <span class="text-cyan-400 font-mono font-medium" id="kpi-today-date">--</span>
        </div>
      </div>

      <!-- Cached / Optimized Tokens -->
      <div class="bg-darkcard border border-darkborder rounded-2xl p-5 shadow-sm relative overflow-hidden">
        <div class="flex justify-between items-start">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wider text-gray-400">Tokens en Cache (Économie)</p>
            <h3 id="kpi-cached-tokens" class="text-3xl font-extrabold text-emerald-400 mt-1 font-mono">--</h3>
          </div>
          <span class="p-2.5 rounded-xl bg-emerald-500/10 text-emerald-400 text-lg border border-emerald-500/20">⚡</span>
        </div>
        <div class="mt-4 flex items-center justify-between text-xs text-gray-400 border-t border-gray-800/60 pt-3">
          <span>Taux de Cache : <strong id="kpi-cache-rate" class="text-emerald-400 font-mono">--%</strong></span>
          <span class="text-xs text-emerald-400/80">Context Caching</span>
        </div>
      </div>

      <!-- Estimated Cost -->
      <div class="bg-darkcard border border-darkborder rounded-2xl p-5 shadow-sm relative overflow-hidden">
        <div class="flex justify-between items-start">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wider text-gray-400">Coût Estimé (USD)</p>
            <h3 id="kpi-cost" class="text-3xl font-extrabold text-amber-400 mt-1 font-mono">--</h3>
          </div>
          <span class="p-2.5 rounded-xl bg-amber-500/10 text-amber-400 text-lg border border-amber-500/20">💰</span>
        </div>
        <div class="mt-4 flex items-center justify-between text-xs text-gray-400 border-t border-gray-800/60 pt-3">
          <span>Aujourd'hui : <strong id="kpi-today-cost" class="text-amber-300 font-mono">--</strong></span>
          <span class="text-amber-400/80 text-xs">Gemini Flash Rates</span>
        </div>
      </div>
    </div>

    <!-- Interactive Filters & Hourly Breakdown Section -->
    <section class="bg-darkcard border border-darkborder rounded-2xl p-6 shadow-sm space-y-6">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 class="text-base font-bold text-white flex items-center gap-2">
            <span>⏱️</span>
            <span>Consommation par Heure (00h - 23h)</span>
          </h2>
          <p class="text-xs text-gray-400 mt-0.5">Visualisez les pics de charge heure par heure pour chaque journée</p>
        </div>

        <div class="flex items-center space-x-3">
          <label for="day-select" class="text-xs text-gray-400 font-medium">Sélectionner un jour :</label>
          <select id="day-select" onchange="renderHourlyChart(this.value)" class="bg-gray-800 border border-gray-700 text-gray-200 text-xs rounded-lg px-3 py-1.5 focus:ring-1 focus:ring-brand-500 outline-none">
            <!-- Populated via JS -->
          </select>
        </div>
      </div>

      <!-- Hourly Chart Canvas / SVG Container -->
      <div class="pt-2">
        <div id="hourly-chart-container" class="w-full h-56 flex items-end gap-1.5 px-2 pb-6 border-b border-gray-800 relative">
          <!-- Bars injected via JS -->
        </div>
        <!-- Hour labels below bars -->
        <div id="hourly-labels" class="flex justify-between text-[11px] text-gray-400 px-2 pt-2 font-mono">
          <!-- 00h, 04h, 08h, 12h, 16h, 20h, 23h labels -->
        </div>
      </div>

      <!-- Hourly Quick Insights -->
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2 text-xs">
        <div class="bg-gray-800/40 border border-gray-800 p-3 rounded-xl">
          <span class="text-gray-400">Heure de pointe :</span>
          <strong id="peak-hour" class="text-brand-400 ml-2 font-mono">--</strong>
        </div>
        <div class="bg-gray-800/40 border border-gray-800 p-3 rounded-xl">
          <span class="text-gray-400">Total sur le jour sélectionné :</span>
          <strong id="selected-day-total" class="text-gray-200 ml-2 font-mono">--</strong>
        </div>
        <div class="bg-gray-800/40 border border-gray-800 p-3 rounded-xl">
          <span class="text-gray-400">Moyenne par heure active :</span>
          <strong id="avg-active-hour" class="text-gray-200 ml-2 font-mono">--</strong>
        </div>
      </div>
    </section>

    <!-- Daily History Chart Section -->
    <section class="bg-darkcard border border-darkborder rounded-2xl p-6 shadow-sm space-y-6">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-base font-bold text-white flex items-center gap-2">
            <span>📅</span>
            <span>Historique par Jour</span>
          </h2>
          <p class="text-xs text-gray-400 mt-0.5">Évolution quotidienne de la consommation de tokens</p>
        </div>
      </div>

      <div id="daily-chart-container" class="w-full h-52 flex items-end gap-3 px-2 pb-6 border-b border-gray-800 relative">
        <!-- Daily bars injected via JS -->
      </div>
    </section>

    <!-- Projects Breakdown Table Section -->
    <section class="bg-darkcard border border-darkborder rounded-2xl p-6 shadow-sm space-y-6">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 class="text-base font-bold text-white flex items-center gap-2">
            <span>📁</span>
            <span>Consommation par Projet / Workspace</span>
          </h2>
          <p class="text-xs text-gray-400 mt-0.5">Détail des tokens consommés dans chaque répertoire de travail</p>
        </div>
        
        <input type="text" id="project-search" oninput="filterProjectTable(this.value)" placeholder="Filtrer un projet..." class="bg-gray-800 border border-gray-700 text-gray-200 text-xs rounded-lg px-3 py-1.5 focus:ring-1 focus:ring-brand-500 outline-none w-64" />
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs">
          <thead>
            <tr class="border-b border-gray-800 text-gray-400 uppercase tracking-wider font-semibold">
              <th class="py-3 px-4">Projet / Workspace</th>
              <th class="py-3 px-4">Part (%)</th>
              <th class="py-3 px-4 text-right">Appels</th>
              <th class="py-3 px-4 text-right">Input (Prompt)</th>
              <th class="py-3 px-4 text-right">Output (Génération)</th>
              <th class="py-3 px-4 text-right">Cache</th>
              <th class="py-3 px-4 text-right font-bold text-gray-300">Total Tokens</th>
              <th class="py-3 px-4 text-right">Coût Est.</th>
            </tr>
          </thead>
          <tbody id="projects-tbody" class="divide-y divide-gray-800/60 font-mono">
            <!-- Injected via JS -->
          </tbody>
        </table>
      </div>
    </section>

  </main>

  <footer class="text-center py-6 border-t border-darkborder text-xs text-gray-400">
    Antigravity Token Tracker · Créé pour Racem-H · Mis à jour en continu
  </footer>

  <script>
    const RAW_DATA = {data_json_str};

    function formatNumber(n) {{
      if (n >= 1000000) return (n / 1000000).toFixed(2) + 'M';
      if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
      return n.toLocaleString();
    }}

    function initDashboard() {{
      // Update Sync Time
      document.getElementById('sync-time').textContent = new Date().toLocaleTimeString('fr-FR', {{ hour: '2-digit', minute: '2-digit', second: '2-digit' }});

      // Populate KPIs
      const sum = RAW_DATA.summary;
      const today = RAW_DATA.today;

      document.getElementById('kpi-total-tokens').textContent = formatNumber(sum.total_tokens);
      document.getElementById('kpi-total-calls').textContent = sum.total_calls.toLocaleString();

      document.getElementById('kpi-today-tokens').textContent = formatNumber(today.total);
      document.getElementById('kpi-today-calls').textContent = today.calls.toLocaleString();
      document.getElementById('kpi-today-date').textContent = RAW_DATA.today_date;

      document.getElementById('kpi-cached-tokens').textContent = formatNumber(sum.total_cached);
      document.getElementById('kpi-cache-rate').textContent = sum.cache_hit_pct + '%';

      document.getElementById('kpi-cost').textContent = '$' + sum.estimated_cost_usd.toFixed(2);
      document.getElementById('kpi-today-cost').textContent = '$' + today.cost_usd.toFixed(2);

      // Populate Day Selector
      const daySelect = document.getElementById('day-select');
      const sortedDays = Object.keys(RAW_DATA.days).sort().reverse();
      
      daySelect.innerHTML = '';
      sortedDays.forEach(d => {{
        const opt = document.createElement('option');
        opt.value = d;
        opt.textContent = d + (d === RAW_DATA.today_date ? ' (Aujourd\\'hui)' : '');
        daySelect.appendChild(opt);
      }});

      if (sortedDays.length > 0) {{
        renderHourlyChart(sortedDays[0]);
      }}

      renderDailyChart();
      renderProjectsTable();
    }}

    function renderHourlyChart(dayKey) {{
      const container = document.getElementById('hourly-chart-container');
      const labels = document.getElementById('hourly-labels');
      container.innerHTML = '';
      labels.innerHTML = '';

      const dayData = RAW_DATA.days[dayKey];
      if (!dayData) return;

      let maxVal = 1;
      let peakHour = '00';
      let peakVal = 0;
      let activeHoursCount = 0;
      let activeHoursTotal = 0;

      for (let h = 0; h < 24; h++) {{
        const hStr = h.toString().padStart(2, '0');
        const hInfo = dayData.hours[hStr] || {{ input: 0, output: 0, cached: 0, calls: 0 }};
        const tot = hInfo.input + hInfo.output + hInfo.cached;
        if (tot > maxVal) maxVal = tot;
        if (tot > peakVal) {{
          peakVal = tot;
          peakHour = hStr;
        }}
        if (tot > 0) {{
          activeHoursCount++;
          activeHoursTotal += tot;
        }}
      }}

      document.getElementById('peak-hour').textContent = peakHour + 'h (' + formatNumber(peakVal) + ')';
      document.getElementById('selected-day-total').textContent = formatNumber(dayData.total) + ' (' + dayData.calls + ' appels)';
      document.getElementById('avg-active-hour').textContent = activeHoursCount > 0 ? formatNumber(Math.round(activeHoursTotal / activeHoursCount)) : '0';

      for (let h = 0; h < 24; h++) {{
        const hStr = h.toString().padStart(2, '0');
        const hInfo = dayData.hours[hStr] || {{ input: 0, output: 0, cached: 0, calls: 0 }};
        const tot = hInfo.input + hInfo.output + hInfo.cached;
        const heightPct = Math.max((tot / maxVal) * 100, 3);

        const col = document.createElement('div');
        col.className = 'flex-1 flex flex-col justify-end items-center h-full group relative';

        const bar = document.createElement('div');
        bar.className = 'w-full rounded-t transition-all duration-300 bar-hover ' + 
          (tot > 0 ? 'bg-gradient-to-t from-brand-600 to-cyan-400' : 'bg-gray-800/40');
        bar.style.height = (tot > 0 ? heightPct : 3) + '%';

        // Tooltip
        const tip = document.createElement('div');
        tip.className = 'absolute bottom-full mb-2 hidden group-hover:flex flex-col bg-gray-900 border border-gray-700 text-[10px] text-gray-200 p-2 rounded-lg shadow-xl z-20 pointer-events-none whitespace-nowrap font-mono';
        tip.innerHTML = `<strong>Heure : ${{hStr}}h00 - ${{hStr}}h59</strong>` +
          `<span>Total: ${{formatNumber(tot)}}</span>` +
          `<span>Input: ${{formatNumber(hInfo.input)}} | Output: ${{formatNumber(hInfo.output)}}</span>` +
          `<span>Cache: ${{formatNumber(hInfo.cached)}}</span>` +
          `<span>Appels: ${{hInfo.calls}}</span>`;

        col.appendChild(tip);
        col.appendChild(bar);
        container.appendChild(col);
      }}

      // Set hour labels (every 3 hours)
      for (let h = 0; h < 24; h += 3) {{
        const span = document.createElement('span');
        span.textContent = h.toString().padStart(2, '0') + 'h';
        labels.appendChild(span);
      }}
      const lastSpan = document.createElement('span');
      lastSpan.textContent = '23h';
      labels.appendChild(lastSpan);
    }}

    function renderDailyChart() {{
      const container = document.getElementById('daily-chart-container');
      container.innerHTML = '';

      const days = Object.keys(RAW_DATA.days).sort();
      let maxVal = 1;
      days.forEach(d => {{
        const tot = RAW_DATA.days[d].total;
        if (tot > maxVal) maxVal = tot;
      }});

      days.forEach(d => {{
        const dInfo = RAW_DATA.days[d];
        const heightPct = Math.max((dInfo.total / maxVal) * 100, 5);

        const col = document.createElement('div');
        col.className = 'flex-1 flex flex-col justify-end items-center h-full group relative';

        const bar = document.createElement('div');
        bar.className = 'w-full rounded-t bg-gradient-to-t from-cyan-600 to-indigo-500 bar-hover transition-all';
        bar.style.height = heightPct + '%';

        const label = document.createElement('div');
        label.className = 'text-[10px] text-gray-400 mt-2 font-mono truncate w-full text-center';
        label.textContent = d.slice(5); // MM-DD

        const tip = document.createElement('div');
        tip.className = 'absolute bottom-full mb-2 hidden group-hover:flex flex-col bg-gray-900 border border-gray-700 text-[10px] text-gray-200 p-2 rounded-lg shadow-xl z-20 pointer-events-none whitespace-nowrap font-mono';
        tip.innerHTML = `<strong>Date : ${{d}}</strong>` +
          `<span>Total: ${{formatNumber(dInfo.total)}}</span>` +
          `<span>Cache Hit: ${{dInfo.cache_hit_pct}}%</span>` +
          `<span>Coût: $${{dInfo.cost_usd.toFixed(2)}}</span>` +
          `<span>Appels: ${{dInfo.calls}}</span>`;

        col.appendChild(tip);
        col.appendChild(bar);
        col.appendChild(label);
        container.appendChild(col);
      }});
    }}

    function renderProjectsTable(filter = '') {{
      const tbody = document.getElementById('projects-tbody');
      tbody.innerHTML = '';

      const projects = Object.values(RAW_DATA.projects).sort((a, b) => b.total - a.total);
      
      projects.forEach(p => {{
        if (filter && !p.workspace_name.toLowerCase().includes(filter.toLowerCase()) && !p.workspace_path.toLowerCase().includes(filter.toLowerCase())) {{
          return;
        }}

        const tr = document.createElement('tr');
        tr.className = 'hover:bg-gray-800/40 transition';

        tr.innerHTML = `
          <td class="py-3 px-4">
            <div class="font-medium text-white">${{p.workspace_name}}</div>
            <div class="text-[10px] text-gray-400 truncate max-w-xs">${{p.workspace_path || 'Emplacement non spécifié'}}</div>
          </td>
          <td class="py-3 px-4">
            <div class="flex items-center space-x-2">
              <div class="w-16 bg-gray-800 rounded-full h-1.5 overflow-hidden">
                <div class="bg-brand-500 h-1.5 rounded-full" style="width: ${{Math.min(p.percent_of_total, 100)}}%"></div>
              </div>
              <span class="text-[11px] text-gray-300">${{p.percent_of_total}}%</span>
            </div>
          </td>
          <td class="py-3 px-4 text-right text-gray-300">${{p.calls.toLocaleString()}}</td>
          <td class="py-3 px-4 text-right text-gray-400">${{formatNumber(p.input)}}</td>
          <td class="py-3 px-4 text-right text-gray-400">${{formatNumber(p.output)}}</td>
          <td class="py-3 px-4 text-right text-emerald-400">${{formatNumber(p.cached)}}</td>
          <td class="py-3 px-4 text-right font-bold text-white">${{formatNumber(p.total)}}</td>
          <td class="py-3 px-4 text-right text-amber-400 font-semibold">$${{p.cost_usd.toFixed(2)}}</td>
        `;

        tbody.appendChild(tr);
      }});
    }}

    function filterProjectTable(val) {{
      renderProjectsTable(val);
    }}

    window.onload = initDashboard;
  </script>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return output_path

class TokenStatsServer(SimpleHTTPRequestHandler):
    """Local HTTP Server to serve dashboard and live JSON API."""
    def do_GET(self):
        if self.path == "/api/stats":
            stats = calculate_token_stats()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(stats).encode("utf-8"))
        else:
            # Serve dashboard.html
            script_dir = os.path.dirname(os.path.abspath(__file__))
            dash_path = os.path.join(os.path.dirname(script_dir), "dashboard.html")
            if os.path.exists(dash_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(dash_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                super().do_GET()

def start_server(port=8765):
    """Starts local server and opens browser."""
    stats = calculate_token_stats()
    dash_path = generate_html_dashboard(stats)
    print(f"⚡ Token Tracker Server démarré sur : http://localhost:{port}")
    server = HTTPServer(("localhost", port), TokenStatsServer)
    webbrowser.open(f"http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du serveur.")
        server.server_close()

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Antigravity Token Tracker CLI")
    parser.add_argument("--json", action="store_true", help="Sortie JSON brute")
    parser.add_argument("--summary", action="store_true", help="Résumé textuel dans le terminal")
    parser.add_argument("--markdown", action="store_true", help="Génère la carte Markdown pour Antigravity")
    parser.add_argument("--html", nargs="?", const="default", help="Génère le dashboard HTML")
    parser.add_argument("--serve", action="store_true", help="Lance le serveur local et ouvre le navigateur")
    parser.add_argument("--port", type=int, default=8765, help="Port pour le serveur HTTP (défaut: 8765)")
    parser.add_argument("--workspace", type=str, default="", help="Chemin du workspace actuel")
    
    args = parser.parse_args()
    stats = calculate_token_stats(target_workspace=args.workspace)
    
    if args.json:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    elif args.markdown:
        print(generate_markdown_banner(stats, current_ws_name=args.workspace))
    elif args.serve:
        start_server(port=args.port)
    elif args.html:
        out_p = None if args.html == "default" else args.html
        path = generate_html_dashboard(stats, out_p)
        print(f"Dashboard généré avec succès : {path}")
    elif args.summary:
        sum_data = stats["summary"]
        today = stats["today"]
        print("=" * 60)
        print("⚡ ANTIGRAVITY TOKEN TRACKER — RÉSUMÉ")
        print("=" * 60)
        print(f"Total Consommé : {format_tokens(sum_data['total_tokens'])} ({sum_data['total_calls']} appels)")
        print(f"Input Tokens   : {format_tokens(sum_data['total_input'])}")
        print(f"Output Tokens  : {format_tokens(sum_data['total_output'])}")
        print(f"Cached Tokens  : {format_tokens(sum_data['total_cached'])} ({sum_data['cache_hit_pct']}% économisé)")
        print(f"Coût Estimé    : {format_cost(sum_data['estimated_cost_usd'])}")
        print("-" * 60)
        print(f"Aujourd'hui    : {format_tokens(today['total'])} ({today['calls']} appels, {format_cost(today['cost_usd'])})")
        print("=" * 60)
    else:
        # Default: generate HTML and output Markdown
        path = generate_html_dashboard(stats)
        print(generate_markdown_banner(stats, current_ws_name=args.workspace))

if __name__ == "__main__":
    main()
