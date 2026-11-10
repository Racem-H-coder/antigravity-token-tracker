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
from datetime import datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
import webbrowser
import threading

def get_config_path():
    """Returns the absolute path to config.json."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(script_dir), "config.json")

def load_config():
    """Loads quota and subscription configuration from config.json."""
    cfg_path = get_config_path()
    default_config = {
        "active_plan": "Google AI Pro",
        "rolling_5h_token_quota": 75_000_000,
        "daily_token_quota": 100_000_000,
        "weekly_token_quota": 500_000_000,
        "plans": {
            "Google AI Starter": {
                "rolling_5h_token_quota": 15_000_000,
                "daily_token_quota": 20_000_000,
                "weekly_token_quota": 100_000_000,
                "description": "Formule Gratuite / Starter (Limite hebdomadaire 100M)"
            },
            "Google AI Pro": {
                "rolling_5h_token_quota": 75_000_000,
                "daily_token_quota": 100_000_000,
                "weekly_token_quota": 500_000_000,
                "description": "Abonnement Google AI Pro ($19.99/mois, Fenêtre 5h: 75M, Hebdo: 500M)"
            },
            "Google AI Ultra": {
                "rolling_5h_token_quota": 250_000_000,
                "daily_token_quota": 300_000_000,
                "weekly_token_quota": 1_500_000_000,
                "description": "Abonnement Google AI Ultra (Fenêtre 5h: 250M, Hebdo: 1.5B)"
            },
            "Custom": {
                "rolling_5h_token_quota": 75_000_000,
                "daily_token_quota": 100_000_000,
                "weekly_token_quota": 500_000_000,
                "description": "Limites personnalisées"
            }
        }
    }
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                default_config.update(data)
        except Exception:
            pass
    return default_config

def save_config(cfg):
    """Saves quota and subscription configuration to config.json."""
    cfg_path = get_config_path()
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False

def parse_token_input(val_str):
    """Parses token strings like '100M', '500k', '1.5B' or raw numbers into integers."""
    if isinstance(val_str, (int, float)):
        return int(val_str)
    s = str(val_str).strip().upper()
    try:
        if s.endswith("B"):
            return int(float(s[:-1]) * 1_000_000_000)
        elif s.endswith("M"):
            return int(float(s[:-1]) * 1_000_000)
        elif s.endswith("K"):
            return int(float(s[:-1]) * 1_000)
        return int(float(s))
    except Exception:
        return 0

def make_progress_bar(pct, length=10):
    """Creates a text progress bar (e.g. [█████░░░░░])."""
    pct = min(max(pct, 0.0), 100.0)
    filled = int(round(length * pct / 100.0))
    return "█" * filled + "░" * (length - filled)

def get_antigravity_paths():
    """Detects Antigravity directory, SQLite database, and brain directory."""
    home = os.path.expanduser("~")
    base_dir = os.path.join(home, ".gemini", "antigravity")
    db_path = os.path.join(base_dir, "conversation_summaries.db")
    brain_dir = os.path.join(base_dir, "brain")
    return base_dir, db_path, brain_dir

def format_tokens(n):
    """Formats token numbers in human-readable string (e.g. 1.2M, 450k, 120)."""
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    elif n >= 1_000_000:
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
    
    now_dt = datetime.now().astimezone()
    cutoff_5h = now_dt - timedelta(hours=5)
    tokens_5h_input = 0
    tokens_5h_output = 0
    tokens_5h_cached = 0
    tokens_5h_calls = 0
    
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
                            try:
                                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone()
                                day_str = dt.strftime("%Y-%m-%d")
                                hour_str = dt.strftime("%H")
                            except Exception:
                                day_str = created_at[:10]
                                hour_str = created_at[11:13]
                                dt = None
                            
                            # 5-hour rolling window check
                            if dt and dt >= cutoff_5h:
                                tokens_5h_input += inp
                                tokens_5h_output += out
                                tokens_5h_cached += cached
                                tokens_5h_calls += 1
                            
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

    # Load subscription and quota configuration
    cfg = load_config()
    daily_quota = cfg.get("daily_token_quota", 100_000_000)
    weekly_quota = cfg.get("weekly_token_quota", 500_000_000)
    quota_5h = cfg.get("rolling_5h_token_quota", 75_000_000)
    active_plan = cfg.get("active_plan", "Google AI Pro")

    # 5-hour rolling window stats
    tokens_5h_total = tokens_5h_input + tokens_5h_output + tokens_5h_cached
    remaining_5h = max(0, quota_5h - tokens_5h_total)
    used_pct_5h = round((tokens_5h_total / quota_5h * 100), 1) if quota_5h > 0 else 0.0
    remaining_pct_5h = max(0.0, round(100.0 - used_pct_5h, 1))
    rolling_5h_stats = {
        "quota": quota_5h,
        "used": tokens_5h_total,
        "remaining": remaining_5h,
        "used_pct": used_pct_5h,
        "remaining_pct": remaining_pct_5h,
        "calls": tokens_5h_calls,
        "input": tokens_5h_input,
        "output": tokens_5h_output,
        "cached": tokens_5h_cached,
        "cost_usd": calc_cost(tokens_5h_input, tokens_5h_output, tokens_5h_cached),
        "is_exceeded": tokens_5h_total > quota_5h,
        "exceeded_by": tokens_5h_total - quota_5h if tokens_5h_total > quota_5h else 0,
        "window_start": cutoff_5h.strftime("%H:%M"),
        "window_end": now_dt.strftime("%H:%M"),
        "label": f"Fenêtre 5h ({cutoff_5h.strftime('%H:%M')} → {now_dt.strftime('%H:%M')})"
    }

    # Group ALL days into weeks with weekly percentage breakdown
    weeks_data = {}
    for day_k, d_stat in sorted(stats_by_day.items()):
        try:
            d_obj = datetime.strptime(day_k, "%Y-%m-%d").date()
        except Exception:
            continue
        w_start = d_obj - timedelta(days=d_obj.weekday())
        w_end = w_start + timedelta(days=6)
        w_key = w_start.strftime("%Y-%m-%d")
        w_lbl = f"Semaine du {w_start.strftime('%d/%m')} au {w_end.strftime('%d/%m/%Y')}"
        
        if w_key not in weeks_data:
            weeks_data[w_key] = {
                "start_date": w_key,
                "end_date": w_end.strftime("%Y-%m-%d"),
                "label": w_lbl,
                "total": 0,
                "input": 0,
                "output": 0,
                "cached": 0,
                "calls": 0,
                "cost_usd": 0.0,
                "quota": weekly_quota,
                "days": []
            }
        
        weeks_data[w_key]["total"] += d_stat["total"]
        weeks_data[w_key]["input"] += d_stat["input"]
        weeks_data[w_key]["output"] += d_stat["output"]
        weeks_data[w_key]["cached"] += d_stat["cached"]
        weeks_data[w_key]["calls"] += d_stat["calls"]
        weeks_data[w_key]["cost_usd"] += d_stat["cost_usd"]
        
        day_pct_of_weekly_limit = round((d_stat["total"] / weekly_quota * 100), 2) if weekly_quota > 0 else 0.0
        day_pct_of_daily_limit = round((d_stat["total"] / daily_quota * 100), 1) if daily_quota > 0 else 0.0
        
        weeks_data[w_key]["days"].append({
            "date": day_k,
            "total": d_stat["total"],
            "input": d_stat["input"],
            "output": d_stat["output"],
            "cached": d_stat["cached"],
            "calls": d_stat["calls"],
            "cost_usd": d_stat["cost_usd"],
            "cache_hit_pct": d_stat.get("cache_hit_pct", 0.0),
            "pct_of_weekly_limit": day_pct_of_weekly_limit,
            "pct_of_daily_limit": day_pct_of_daily_limit
        })

    # Enrich each week with % of weekly limit and remaining
    for w_k, w_val in weeks_data.items():
        w_used_pct = round((w_val["total"] / weekly_quota * 100), 1) if weekly_quota > 0 else 0.0
        w_rem_tokens = max(0, weekly_quota - w_val["total"])
        w_rem_pct = max(0.0, round(100.0 - w_used_pct, 1))
        w_val["used_pct_of_weekly_limit"] = w_used_pct
        w_val["remaining"] = w_rem_tokens
        w_val["remaining_pct"] = w_rem_pct
        w_val["is_exceeded"] = w_val["total"] > weekly_quota
        w_val["exceeded_by"] = w_val["total"] - weekly_quota if w_val["total"] > weekly_quota else 0

    # Today stats & Quotas
    today_stats = stats_by_day.get(today_str, {
        "input": 0, "output": 0, "cached": 0, "total": 0, "calls": 0, "cost_usd": 0.0, "cache_hit_pct": 0.0,
        "hours": {f"{h:02d}": {"input": 0, "output": 0, "cached": 0, "calls": 0} for h in range(24)}
    })
    
    today_total = today_stats.get("total", 0)
    today_remaining = max(0, daily_quota - today_total)
    today_used_pct = round((today_total / daily_quota * 100), 1) if daily_quota > 0 else 0.0
    today_remaining_pct = max(0.0, round(100.0 - today_used_pct, 1))
    today_pct_of_weekly = round((today_total / weekly_quota * 100), 2) if weekly_quota > 0 else 0.0

    today_quota_stats = {
        "quota": daily_quota,
        "used": today_total,
        "remaining": today_remaining,
        "used_pct": today_used_pct,
        "remaining_pct": today_remaining_pct,
        "pct_of_weekly_limit": today_pct_of_weekly,
        "is_exceeded": today_total > daily_quota,
        "exceeded_by": today_total - daily_quota if today_total > daily_quota else 0
    }

    # Current week stats (for header and quick access)
    today_dt = datetime.now().date()
    start_of_week = today_dt - timedelta(days=today_dt.weekday())
    curr_week_key = start_of_week.strftime("%Y-%m-%d")
    current_week_stats = weeks_data.get(curr_week_key, {
        "start_date": curr_week_key,
        "end_date": (start_of_week + timedelta(days=6)).strftime("%Y-%m-%d"),
        "label": f"Semaine du {start_of_week.strftime('%d/%m')} au {(start_of_week + timedelta(days=6)).strftime('%d/%m/%Y')}",
        "total": 0,
        "input": 0,
        "output": 0,
        "cached": 0,
        "calls": 0,
        "cost_usd": 0.0,
        "quota": weekly_quota,
        "remaining": weekly_quota,
        "used_pct_of_weekly_limit": 0.0,
        "remaining_pct": 100.0,
        "days": []
    })
    
    # Current hour stats
    current_hour_str = datetime.now().strftime("%H")
    current_hour_stats = today_stats.get("hours", {}).get(current_hour_str, {"input": 0, "output": 0, "cached": 0, "calls": 0})
    current_hour_total = current_hour_stats["input"] + current_hour_stats["output"] + current_hour_stats["cached"]

    # Match target workspace if provided, or fallback to current working directory
    matched_workspace_stats = None
    if not target_workspace:
        try:
            target_workspace = os.getcwd()
        except Exception:
            target_workspace = None

    if target_workspace:
        norm_target = target_workspace.replace("/", "\\").rstrip("\\").lower()
        for p, st in stats_by_project.items():
            norm_p_path = st["workspace_path"].replace("/", "\\").rstrip("\\").lower()
            norm_p_name = st["workspace_name"].lower()
            if (norm_p_path and (norm_target in norm_p_path or norm_p_path in norm_target)) or (norm_p_name and norm_p_name in norm_target):
                matched_workspace_stats = st
                break

    return {
        "timestamp": datetime.now().isoformat(),
        "today_date": today_str,
        "current_hour": current_hour_str,
        "quota_config": cfg,
        "rolling_5h_quota": rolling_5h_stats,
        "today_quota": today_quota_stats,
        "week_quota": current_week_stats,
        "weeks": weeks_data,
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
    
    r5 = stats.get("rolling_5h_quota", {})
    w_quota = stats.get("week_quota", {})
    t_quota = stats.get("today_quota", {})
    plan = stats.get("quota_config", {}).get("active_plan", "Google AI Pro")
    
    r5_rem = format_tokens(r5.get("remaining", 0))
    r5_max = format_tokens(r5.get("quota", 75_000_000))
    r5_rem_pct = r5.get("remaining_pct", 0.0)
    r5_bar = make_progress_bar(r5_rem_pct, length=8)
    
    w_rem = format_tokens(w_quota.get("remaining", 0))
    w_max = format_tokens(w_quota.get("quota", 500_000_000))
    w_rem_pct = w_quota.get("remaining_pct", 0.0)
    w_used_pct = w_quota.get("used_pct_of_weekly_limit", 0.0)
    w_bar = make_progress_bar(w_rem_pct, length=8)
    
    today_total = format_tokens(today["total"])
    today_pct_weekly = t_quota.get("pct_of_weekly_limit", 0.0)
    
    today_input = format_tokens(today["input"])
    today_output = format_tokens(today["output"])
    today_cached = format_tokens(today["cached"])
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    plugin_dir = os.path.dirname(script_dir)
    dashboard_html_path = os.path.join(plugin_dir, "dashboard.html").replace("\\", "/")
    
    md = f"""### 📊 Antigravity Token Tracker — Vue Quotas 5h & Semaine

| ⏱️ Reste Instantané (5h) | 🗓️ Reste Semaine (Weekly) | 📊 Utilisé Semaine | 📅 Conso Jour (Part Hebdo) |
| :--- | :--- | :--- | :--- |
| **{r5_rem}** / {r5_max} (`{r5_rem_pct}%` dispo)<br>`[{r5_bar}]` | **{w_rem}** / {w_max} (`{w_rem_pct}%` dispo)<br>`[{w_bar}]` | **{format_tokens(w_quota['total'])}** (**{w_used_pct}%** du quota) | **{today_total}** (**{today_pct_weekly}%** du quota) |

> 💎 **Abonnement** : `{plan}` (Fenêtre 5h : `{r5_max}` · Plafond Hebdo : `{w_max}`)  
> ⚡ **Activité 5h glissante** : `{format_tokens(r5['used'])}` consommés (**{r5['used_pct']}%** utilisé) entre {r5['window_start']} et {r5['window_end']} ({r5['calls']} appels)  
> 📁 **Projet Actif** : `{proj_name}` ({proj_tokens} tokens) · 📈 **Total Historique** : **{format_tokens(summary['total_tokens'])}** tokens ({format_cost(summary['estimated_cost_usd'])})  
> 💾 **Économie Cache Jour** : **{today['cache_hit_pct']}%** économisé via cache ({today_cached} tokens cache)

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
          <span class="text-xs px-2 py-0.5 rounded-full bg-brand-500/20 text-brand-400 border border-brand-500/30">v1.1</span>
        </h1>
        <p class="text-xs text-gray-400">Suivi Quotas 5h, Hebdo & Journalier en Temps Réel</p>
      </div>
    </div>
    
    <div class="flex items-center space-x-3">
      <button id="config-btn" onclick="openConfigModal()" class="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-brand-600/30 hover:bg-brand-600/50 text-xs font-medium text-brand-200 border border-brand-500/40 transition">
        <span>⚙️</span>
        <span>Abonnement & Quotas</span>
      </button>
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
    
    <!-- Quotas & Limites d'Abonnement (5h & Hebdo) -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
      <!-- Quota 5h Glissante (Sprint) -->
      <div class="bg-gradient-to-br from-darkcard via-darkcard to-brand-950/40 border border-brand-500/30 rounded-2xl p-6 shadow-lg shadow-brand-500/5 relative overflow-hidden">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center space-x-3">
            <div class="w-10 h-10 rounded-xl bg-brand-500/20 text-brand-400 border border-brand-500/30 flex items-center justify-center text-xl">
              ⏱️
            </div>
            <div>
              <h3 class="text-sm font-bold uppercase tracking-wider text-gray-200">Reste Instantané (Fenêtre 5 Heures)</h3>
              <p id="quota-5h-window-label" class="text-xs text-gray-400 font-mono">Fenêtre glissante de sprint</p>
            </div>
          </div>
          <span id="plan-badge-5h" class="px-2.5 py-1 rounded-full text-xs font-semibold bg-brand-500/20 text-brand-300 border border-brand-500/30">Google AI Pro</span>
        </div>
        
        <div class="flex items-baseline space-x-3 mt-1">
          <span id="quota-5h-rem" class="text-4xl font-black text-white font-mono">--</span>
          <span class="text-xs font-medium text-gray-400">tokens disponibles</span>
        </div>

        <div class="mt-4 space-y-2">
          <div class="flex justify-between text-xs text-gray-300">
            <span>Consommé 5h : <strong id="quota-5h-used" class="font-mono text-white">--</strong> / <span id="quota-5h-max" class="font-mono text-gray-400">--</span></span>
            <span id="quota-5h-used-pct" class="font-mono font-bold text-brand-300">--% utilisé</span>
          </div>
          <div class="w-full h-3 rounded-full bg-gray-800/80 overflow-hidden p-0.5 border border-gray-700/50">
            <div id="quota-5h-bar" class="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-400 transition-all duration-500" style="width: 0%"></div>
          </div>
          <div class="flex justify-between items-center text-[11px] text-gray-400 pt-1">
            <span id="quota-5h-rem-pct" class="text-emerald-400 font-semibold">--% restant disponible</span>
            <span id="quota-5h-calls" class="font-mono text-gray-400">-- appels</span>
          </div>
        </div>
      </div>

      <!-- Quota Hebdomadaire (Weekly Cap) -->
      <div class="bg-gradient-to-br from-darkcard via-darkcard to-cyan-950/40 border border-cyan-500/30 rounded-2xl p-6 shadow-lg shadow-cyan-500/5 relative overflow-hidden">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center space-x-3">
            <div class="w-10 h-10 rounded-xl bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 flex items-center justify-center text-xl">
              🗓️
            </div>
            <div>
              <h3 class="text-sm font-bold uppercase tracking-wider text-gray-200">Reste Hebdomadaire (Weekly Cap)</h3>
              <p id="quota-week-window-label" class="text-xs text-gray-400">Semaine en cours (Lun → Dim)</p>
            </div>
          </div>
          <span id="plan-badge-week" class="px-2.5 py-1 rounded-full text-xs font-semibold bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">Plafond Hebdo</span>
        </div>
        
        <div class="flex items-baseline space-x-3 mt-1">
          <span id="quota-week-rem" class="text-4xl font-black text-white font-mono">--</span>
          <span class="text-xs font-medium text-gray-400">tokens disponibles</span>
        </div>

        <div class="mt-4 space-y-2">
          <div class="flex justify-between text-xs text-gray-300">
            <span>Consommé Semaine : <strong id="quota-week-used" class="font-mono text-white">--</strong> / <span id="quota-week-max" class="font-mono text-gray-400">--</span></span>
            <span id="quota-week-used-pct" class="font-mono font-bold text-cyan-300">--% utilisé</span>
          </div>
          <div class="w-full h-3 rounded-full bg-gray-800/80 overflow-hidden p-0.5 border border-gray-700/50">
            <div id="quota-week-bar" class="h-full rounded-full bg-gradient-to-r from-cyan-500 to-blue-500 transition-all duration-500" style="width: 0%"></div>
          </div>
          <div class="flex justify-between items-center text-[11px] text-gray-400 pt-1">
            <span id="quota-week-rem-pct" class="text-cyan-400 font-semibold">--% restant disponible</span>
            <span>Aujourd'hui a pris <strong id="today-pct-of-weekly-badge" class="text-white font-mono">--%</strong> du quota weekly</span>
          </div>
        </div>
      </div>
    </div>
    
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

    <!-- Consommation par Semaine & Répartition Quota Hebdomadaire Section -->
    <section class="bg-darkcard border border-darkborder rounded-2xl p-6 shadow-sm space-y-6">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 class="text-base font-bold text-white flex items-center gap-2">
            <span>🗓️</span>
            <span>Consommation par Semaine & Répartition du Quota Hebdomadaire</span>
          </h2>
          <p class="text-xs text-gray-400 mt-0.5">Pourcentage exact de la limite weekly consommé par chaque semaine et chaque jour</p>
        </div>
        <div class="flex items-center space-x-2 text-xs text-gray-400 bg-gray-800/60 px-3 py-1.5 rounded-lg border border-gray-700/60">
          <span class="w-2.5 h-2.5 rounded-full bg-cyan-400 inline-block"></span>
          <span>Plafond Hebdo Actif : <strong id="ref-weekly-quota-label" class="text-white font-mono">--</strong></span>
        </div>
      </div>

      <!-- Table des Semaines avec sous-lignes par Jour -->
      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs">
          <thead>
            <tr class="border-b border-gray-800 text-gray-400 uppercase tracking-wider font-semibold">
              <th class="py-3 px-4">Période (Semaine / Jour)</th>
              <th class="py-3 px-4 text-right">Tokens Consommés</th>
              <th class="py-3 px-4 text-right">% Limite Weekly</th>
              <th class="py-3 px-4">Progression Quota</th>
              <th class="py-3 px-4 text-right">Appels</th>
              <th class="py-3 px-4 text-right">Tokens Restants</th>
              <th class="py-3 px-4 text-right">Coût Est.</th>
            </tr>
          </thead>
          <tbody id="weeks-tbody" class="divide-y divide-gray-800/60 font-mono">
            <!-- Populated via JS -->
          </tbody>
        </table>
      </div>
    </section>

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

  <!-- Modal Configuration Quotas & Abonnement -->
  <div id="config-modal" class="fixed inset-0 bg-black/75 backdrop-blur-sm z-50 flex items-center justify-center hidden p-4">
    <div class="bg-darkcard border border-darkborder rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-5">
      <div class="flex items-center justify-between border-b border-gray-800 pb-3">
        <div class="flex items-center space-x-2.5">
          <span class="text-xl">⚙️</span>
          <h3 class="font-bold text-base text-white">Mon Abonnement & Quotas</h3>
        </div>
        <button onclick="closeConfigModal()" class="text-gray-400 hover:text-white text-lg">✕</button>
      </div>

      <div class="space-y-4 text-xs">
        <div>
          <label class="block text-gray-300 font-semibold mb-1.5">Formule d'Abonnement Antigravity :</label>
          <select id="plan-select" onchange="onPlanSelectChange()" class="w-full bg-gray-800 border border-gray-700 text-white rounded-lg p-2.5 outline-none focus:ring-1 focus:ring-brand-500">
            <option value="Google AI Pro">Google AI Pro ($19.99/mois · 75M 5h / 500M hebdo)</option>
            <option value="Google AI Ultra">Google AI Ultra (Capacité x5 · 250M 5h / 1.5B hebdo)</option>
            <option value="Google AI Starter">Google AI Starter (Gratuit · 15M 5h / 100M hebdo)</option>
            <option value="Custom">Personnalisé (Saisie manuelle)</option>
          </select>
        </div>

        <div>
          <label class="block text-gray-300 font-semibold mb-1.5">Quota Fenêtre 5 Heures (en Millions de tokens) :</label>
          <input type="number" id="input-5h-quota" step="1" class="w-full bg-gray-800 border border-gray-700 text-white rounded-lg p-2.5 outline-none focus:ring-1 focus:ring-brand-500 font-mono" />
          <p class="text-[11px] text-gray-400 mt-1">Capacité de sprint glissante rafraîchie toutes les 5 heures.</p>
        </div>

        <div>
          <label class="block text-gray-300 font-semibold mb-1.5">Quota Hebdomadaire (en Millions de tokens) :</label>
          <input type="number" id="input-weekly-quota" step="10" class="w-full bg-gray-800 border border-gray-700 text-white rounded-lg p-2.5 outline-none focus:ring-1 focus:ring-brand-500 font-mono" />
          <p class="text-[11px] text-gray-400 mt-1">Plafond global par cycle de 7 jours (Lundi → Dimanche).</p>
        </div>
      </div>

      <div class="flex items-center justify-end space-x-3 pt-3 border-t border-gray-800">
        <button onclick="closeConfigModal()" class="px-4 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs font-semibold transition">Annuler</button>
        <button onclick="saveQuotaConfig()" class="px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold shadow-lg shadow-brand-500/20 transition">Enregistrer</button>
      </div>
    </div>
  </div>

  <footer class="text-center py-6 border-t border-darkborder text-xs text-gray-400">
    Antigravity Token Tracker · Open Source & Communauté · Mis à jour en continu
  </footer>

  <script>
    const RAW_DATA = {data_json_str};

    function formatNumber(n) {{
      if (n >= 1000000000) return (n / 1000000000).toFixed(2) + 'B';
      if (n >= 1000000) return (n / 1000000).toFixed(2) + 'M';
      if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
      return (n || 0).toLocaleString();
    }}

    function initDashboard() {{
      // Update Sync Time
      document.getElementById('sync-time').textContent = new Date().toLocaleTimeString('fr-FR', {{ hour: '2-digit', minute: '2-digit', second: '2-digit' }});

      // Populate Quotas (5h Rolling & Weekly Cap)
      const qConfig = RAW_DATA.quota_config || {{}};
      const r5 = RAW_DATA.rolling_5h_quota || {{}};
      const wQuota = RAW_DATA.week_quota || {{}};
      const tQuota = RAW_DATA.today_quota || {{}};
      const planName = qConfig.active_plan || 'Google AI Pro';

      // 5-Hour Rolling Card
      document.getElementById('plan-badge-5h').textContent = planName;
      document.getElementById('quota-5h-window-label').textContent = r5.label || 'Fenêtre 5h glissante';
      document.getElementById('quota-5h-rem').textContent = formatNumber(r5.remaining || 0);
      document.getElementById('quota-5h-used').textContent = formatNumber(r5.used || 0);
      document.getElementById('quota-5h-max').textContent = formatNumber(r5.quota || 75000000);
      document.getElementById('quota-5h-used-pct').textContent = (r5.used_pct || 0) + '% utilisé';
      document.getElementById('quota-5h-rem-pct').textContent = (r5.remaining_pct || 0) + '% restant disponible';
      document.getElementById('quota-5h-calls').textContent = (r5.calls || 0) + ' appels (5h)';

      const bar5h = document.getElementById('quota-5h-bar');
      const pct5h = Math.min(r5.used_pct || 0, 100);
      bar5h.style.width = pct5h + '%';
      if (pct5h > 90) {{
        bar5h.className = 'h-full rounded-full bg-gradient-to-r from-amber-500 to-rose-500 transition-all duration-500';
      }} else if (pct5h > 70) {{
        bar5h.className = 'h-full rounded-full bg-gradient-to-r from-emerald-500 to-amber-400 transition-all duration-500';
      }} else {{
        bar5h.className = 'h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-400 transition-all duration-500';
      }}

      // Weekly Quota Card
      document.getElementById('plan-badge-week').textContent = 'Plafond ' + formatNumber(wQuota.quota || 500000000);
      document.getElementById('quota-week-window-label').textContent = wQuota.label || 'Semaine en cours (Lun → Dim)';
      document.getElementById('quota-week-rem').textContent = formatNumber(wQuota.remaining || 0);
      document.getElementById('quota-week-used').textContent = formatNumber(wQuota.total || 0);
      document.getElementById('quota-week-max').textContent = formatNumber(wQuota.quota || 500000000);
      document.getElementById('quota-week-used-pct').textContent = (wQuota.used_pct_of_weekly_limit || 0) + '% de toute la limite weekly';
      document.getElementById('quota-week-rem-pct').textContent = (wQuota.remaining_pct || 0) + '% restant disponible';
      document.getElementById('today-pct-of-weekly-badge').textContent = (tQuota.pct_of_weekly_limit || 0) + '%';
      document.getElementById('ref-weekly-quota-label').textContent = formatNumber(wQuota.quota || 500000000) + ' tokens';

      const barWeek = document.getElementById('quota-week-bar');
      const pctWeek = Math.min(wQuota.used_pct_of_weekly_limit || 0, 100);
      barWeek.style.width = pctWeek + '%';
      if (pctWeek > 90) {{
        barWeek.className = 'h-full rounded-full bg-gradient-to-r from-amber-500 to-rose-500 transition-all duration-500';
      }} else if (pctWeek > 70) {{
        barWeek.className = 'h-full rounded-full bg-gradient-to-r from-cyan-500 to-amber-400 transition-all duration-500';
      }} else {{
        barWeek.className = 'h-full rounded-full bg-gradient-to-r from-cyan-500 to-blue-500 transition-all duration-500';
      }}

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

      // Render Tables and Charts
      renderWeeksTable();

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

    function renderWeeksTable() {{
      const tbody = document.getElementById('weeks-tbody');
      if (!tbody) return;
      tbody.innerHTML = '';

      const weeksObj = RAW_DATA.weeks || {{}};
      const weekKeys = Object.keys(weeksObj).sort().reverse();

      weekKeys.forEach(wKey => {{
        const w = weeksObj[wKey];
        const isCurrentWeek = (wKey === (RAW_DATA.week_quota && RAW_DATA.week_quota.start_date));
        
        // Main week row
        const trWeek = document.createElement('tr');
        trWeek.className = 'bg-gray-800/50 hover:bg-gray-800/70 border-b border-gray-700/60 font-semibold text-white';
        
        const badgeColor = w.used_pct_of_weekly_limit > 80 ? 'bg-rose-500/20 text-rose-300 border-rose-500/30' :
          (w.used_pct_of_weekly_limit > 50 ? 'bg-amber-500/20 text-amber-300 border-amber-500/30' : 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30');

        trWeek.innerHTML = `
          <td class="py-3 px-4">
            <div class="flex items-center space-x-2">
              <span class="text-sm">🗓️</span>
              <div>
                <span class="font-bold">${{w.label}}</span>
                ${{isCurrentWeek ? '<span class="ml-2 text-[10px] px-2 py-0.5 rounded-full bg-brand-500/20 text-brand-300 border border-brand-500/30">Semaine Actuelle</span>' : ''}}
              </div>
            </div>
          </td>
          <td class="py-3 px-4 text-right font-black text-white text-sm">${{formatNumber(w.total)}}</td>
          <td class="py-3 px-4 text-right">
            <span class="px-2.5 py-1 rounded-full text-xs font-bold border ${{badgeColor}}">
              ${{w.used_pct_of_weekly_limit}}%
            </span>
          </td>
          <td class="py-3 px-4 w-40">
            <div class="w-full bg-gray-900 rounded-full h-2 overflow-hidden border border-gray-700/50">
              <div class="bg-gradient-to-r from-cyan-500 to-indigo-500 h-2 rounded-full" style="width: ${{Math.min(w.used_pct_of_weekly_limit, 100)}}%"></div>
            </div>
          </td>
          <td class="py-3 px-4 text-right text-gray-300">${{w.calls.toLocaleString()}}</td>
          <td class="py-3 px-4 text-right font-bold text-emerald-400">${{formatNumber(w.remaining)}}</td>
          <td class="py-3 px-4 text-right text-amber-400 font-bold">$${{w.cost_usd.toFixed(2)}}</td>
        `;
        tbody.appendChild(trWeek);

        // Daily sub-rows
        if (w.days && w.days.length > 0) {{
          w.days.forEach(d => {{
            const isToday = (d.date === RAW_DATA.today_date);
            const trDay = document.createElement('tr');
            trDay.className = isToday ? 'bg-brand-950/20 hover:bg-brand-950/30 text-gray-200' : 'hover:bg-gray-800/30 text-gray-300';
            
            trDay.innerHTML = `
              <td class="py-2.5 px-4 pl-10 text-gray-400 flex items-center space-x-2">
                <span class="text-xs text-gray-500">↳</span>
                <span class="${{isToday ? 'text-brand-300 font-bold' : ''}}">Jour : ${{d.date}}</span>
                ${{isToday ? '<span class="text-[10px] px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">Aujourd\\'hui</span>' : ''}}
              </td>
              <td class="py-2.5 px-4 text-right font-mono ${{isToday ? 'text-white font-bold' : 'text-gray-200'}}">${{formatNumber(d.total)}}</td>
              <td class="py-2.5 px-4 text-right font-mono text-cyan-300 font-semibold">${{d.pct_of_weekly_limit}}% du weekly</td>
              <td class="py-2.5 px-4 w-40">
                <div class="w-full bg-gray-900/60 rounded-full h-1.5 overflow-hidden">
                  <div class="bg-cyan-500/70 h-1.5 rounded-full" style="width: ${{Math.min(d.pct_of_weekly_limit * 3, 100)}}%"></div>
                </div>
              </td>
              <td class="py-2.5 px-4 text-right text-gray-400 font-mono">${{d.calls.toLocaleString()}}</td>
              <td class="py-2.5 px-4 text-right text-gray-400 font-mono text-[11px]">${{d.cache_hit_pct}}% cache</td>
              <td class="py-2.5 px-4 text-right text-amber-300/90 font-mono">$${{d.cost_usd.toFixed(2)}}</td>
            `;
            tbody.appendChild(trDay);
          }});
        }}
      }});
    }}

    function openConfigModal() {{
      const qConfig = RAW_DATA.quota_config || {{}};
      const currentPlan = qConfig.active_plan || 'Google AI Pro';
      document.getElementById('plan-select').value = currentPlan;
      document.getElementById('input-5h-quota').value = (qConfig.rolling_5h_token_quota || 75000000) / 1000000;
      document.getElementById('input-weekly-quota').value = (qConfig.weekly_token_quota || 500000000) / 1000000;
      document.getElementById('config-modal').classList.remove('hidden');
    }}

    function closeConfigModal() {{
      document.getElementById('config-modal').classList.add('hidden');
    }}

    function onPlanSelectChange() {{
      const sel = document.getElementById('plan-select').value;
      const plans = (RAW_DATA.quota_config && RAW_DATA.quota_config.plans) || {{
        'Google AI Starter': {{ rolling_5h_token_quota: 15000000, weekly_token_quota: 100000000 }},
        'Google AI Pro': {{ rolling_5h_token_quota: 75000000, weekly_token_quota: 500000000 }},
        'Google AI Ultra': {{ rolling_5h_token_quota: 250000000, weekly_token_quota: 1500000000 }}
      }};
      if (plans[sel]) {{
        document.getElementById('input-5h-quota').value = plans[sel].rolling_5h_token_quota / 1000000;
        document.getElementById('input-weekly-quota').value = plans[sel].weekly_token_quota / 1000000;
      }}
    }}

    async function saveQuotaConfig() {{
      const plan = document.getElementById('plan-select').value;
      const q5hM = parseFloat(document.getElementById('input-5h-quota').value) || 75;
      const weeklyM = parseFloat(document.getElementById('input-weekly-quota').value) || 500;
      const payload = {{
        active_plan: plan,
        rolling_5h_token_quota: Math.round(q5hM * 1000000),
        weekly_token_quota: Math.round(weeklyM * 1000000)
      }};

      try {{
        const res = await fetch('/api/config', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(payload)
        }});
        if (res.ok) {{
          location.reload();
          return;
        }}
      }} catch (e) {{}}

      // Fallback for file mode: update in memory and recalculate
      if (!RAW_DATA.quota_config) RAW_DATA.quota_config = {{}};
      RAW_DATA.quota_config.active_plan = payload.active_plan;
      RAW_DATA.quota_config.rolling_5h_token_quota = payload.rolling_5h_token_quota;
      RAW_DATA.quota_config.weekly_token_quota = payload.weekly_token_quota;
      
      if (RAW_DATA.rolling_5h_quota) {{
        RAW_DATA.rolling_5h_quota.quota = payload.rolling_5h_token_quota;
        RAW_DATA.rolling_5h_quota.remaining = Math.max(0, payload.rolling_5h_token_quota - RAW_DATA.rolling_5h_quota.used);
        RAW_DATA.rolling_5h_quota.used_pct = Math.round((RAW_DATA.rolling_5h_quota.used / payload.rolling_5h_token_quota) * 1000) / 10;
        RAW_DATA.rolling_5h_quota.remaining_pct = Math.max(0, Math.round((100 - RAW_DATA.rolling_5h_quota.used_pct) * 10) / 10);
      }}

      if (RAW_DATA.week_quota) {{
        RAW_DATA.week_quota.quota = payload.weekly_token_quota;
        RAW_DATA.week_quota.remaining = Math.max(0, payload.weekly_token_quota - RAW_DATA.week_quota.total);
        RAW_DATA.week_quota.used_pct_of_weekly_limit = Math.round((RAW_DATA.week_quota.total / payload.weekly_token_quota) * 1000) / 10;
        RAW_DATA.week_quota.remaining_pct = Math.max(0, Math.round((100 - RAW_DATA.week_quota.used_pct_of_weekly_limit) * 10) / 10);
      }}

      if (RAW_DATA.weeks) {{
        Object.values(RAW_DATA.weeks).forEach(w => {{
          w.quota = payload.weekly_token_quota;
          w.used_pct_of_weekly_limit = Math.round((w.total / payload.weekly_token_quota) * 1000) / 10;
          w.remaining = Math.max(0, payload.weekly_token_quota - w.total);
          w.remaining_pct = Math.max(0, Math.round((100 - w.used_pct_of_weekly_limit) * 10) / 10);
          if (w.days) {{
            w.days.forEach(d => {{
              d.pct_of_weekly_limit = Math.round((d.total / payload.weekly_token_quota) * 10000) / 100;
            }});
          }}
        }});
      }}

      closeConfigModal();
      initDashboard();
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
        elif self.path == "/api/config":
            cfg = load_config()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(cfg).encode("utf-8"))
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

    def do_POST(self):
        if self.path == "/api/config":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                cfg = load_config()
                if "active_plan" in data:
                    cfg["active_plan"] = str(data["active_plan"])
                    plan_name = data["active_plan"]
                    if plan_name in cfg.get("plans", {}):
                        if "rolling_5h_token_quota" not in data:
                            cfg["rolling_5h_token_quota"] = cfg["plans"][plan_name].get("rolling_5h_token_quota", cfg.get("rolling_5h_token_quota", 75_000_000))
                        if "daily_token_quota" not in data:
                            cfg["daily_token_quota"] = cfg["plans"][plan_name].get("daily_token_quota", cfg.get("daily_token_quota", 100_000_000))
                        if "weekly_token_quota" not in data:
                            cfg["weekly_token_quota"] = cfg["plans"][plan_name].get("weekly_token_quota", cfg.get("weekly_token_quota", 500_000_000))
                if "rolling_5h_token_quota" in data:
                    cfg["rolling_5h_token_quota"] = parse_token_input(data["rolling_5h_token_quota"])
                if "daily_token_quota" in data:
                    cfg["daily_token_quota"] = parse_token_input(data["daily_token_quota"])
                if "weekly_token_quota" in data:
                    cfg["weekly_token_quota"] = parse_token_input(data["weekly_token_quota"])
                save_config(cfg)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "config": cfg}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

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

def generate_demo_stats():
    """Generates clean, realistic mock data for public demo without exposing personal files."""
    return {
        "timestamp": "2026-11-10T15:00:00",
        "today_date": "2026-11-10",
        "current_hour": "15",
        "quota_config": {
            "active_plan": "Google AI Pro",
            "rolling_5h_token_quota": 75000000,
            "daily_token_quota": 100000000,
            "weekly_token_quota": 500000000,
            "plans": {
                "Google AI Starter": { "rolling_5h_token_quota": 15000000, "daily_token_quota": 20000000, "weekly_token_quota": 100000000 },
                "Google AI Pro": { "rolling_5h_token_quota": 75000000, "daily_token_quota": 100000000, "weekly_token_quota": 500000000 },
                "Google AI Ultra": { "rolling_5h_token_quota": 250000000, "daily_token_quota": 300000000, "weekly_token_quota": 1500000000 }
            }
        },
        "rolling_5h_quota": {
            "quota": 75000000,
            "used": 42350000,
            "remaining": 32650000,
            "used_pct": 56.5,
            "remaining_pct": 43.5,
            "calls": 280,
            "input": 3200000,
            "output": 450000,
            "cached": 38700000,
            "cost_usd": 1.10,
            "is_exceeded": False,
            "exceeded_by": 0,
            "window_start": "10:00",
            "window_end": "15:00",
            "label": "Fenêtre 5h (10:00 → 15:00)"
        },
        "today_quota": {
            "quota": 100000000,
            "used": 68420000,
            "remaining": 31580000,
            "used_pct": 68.4,
            "remaining_pct": 31.6,
            "pct_of_weekly_limit": 13.68,
            "is_exceeded": False,
            "exceeded_by": 0
        },
        "week_quota": {
            "start_date": "2026-11-09",
            "end_date": "2026-11-15",
            "label": "Semaine du 09/11 au 15/11/2026",
            "total": 145820000,
            "input": 8200000,
            "output": 1150000,
            "cached": 136470000,
            "calls": 1240,
            "cost_usd": 3.51,
            "quota": 500000000,
            "used_pct_of_weekly_limit": 29.2,
            "remaining": 354180000,
            "remaining_pct": 70.8,
            "is_exceeded": False,
            "exceeded_by": 0,
            "days": [
                { "date": "2026-11-09", "total": 77400000, "input": 4500000, "output": 620000, "cached": 72280000, "calls": 680, "cost_usd": 1.88, "cache_hit_pct": 94.1, "pct_of_weekly_limit": 15.48, "pct_of_daily_limit": 77.4 },
                { "date": "2026-11-10", "total": 68420000, "input": 3700000, "output": 530000, "cached": 64190000, "calls": 560, "cost_usd": 1.63, "cache_hit_pct": 94.5, "pct_of_weekly_limit": 13.68, "pct_of_daily_limit": 68.4 }
            ]
        },
        "weeks": {
            "2026-11-09": {
                "start_date": "2026-11-09",
                "end_date": "2026-11-15",
                "label": "Semaine du 09/11 au 15/11/2026",
                "total": 145820000,
                "input": 8200000,
                "output": 1150000,
                "cached": 136470000,
                "calls": 1240,
                "cost_usd": 3.51,
                "quota": 500000000,
                "used_pct_of_weekly_limit": 29.2,
                "remaining": 354180000,
                "remaining_pct": 70.8,
                "is_exceeded": False,
                "exceeded_by": 0,
                "days": [
                    { "date": "2026-11-09", "total": 77400000, "input": 4500000, "output": 620000, "cached": 72280000, "calls": 680, "cost_usd": 1.88, "cache_hit_pct": 94.1, "pct_of_weekly_limit": 15.48, "pct_of_daily_limit": 77.4 },
                    { "date": "2026-11-10", "total": 68420000, "input": 3700000, "output": 530000, "cached": 64190000, "calls": 560, "cost_usd": 1.63, "cache_hit_pct": 94.5, "pct_of_weekly_limit": 13.68, "pct_of_daily_limit": 68.4 }
                ]
            },
            "2026-11-02": {
                "start_date": "2026-11-02",
                "end_date": "2026-11-08",
                "label": "Semaine du 02/11 au 08/11/2026",
                "total": 78900000,
                "input": 4800000,
                "output": 690000,
                "cached": 73410000,
                "calls": 690,
                "cost_usd": 1.94,
                "quota": 500000000,
                "used_pct_of_weekly_limit": 15.8,
                "remaining": 421100000,
                "remaining_pct": 84.2,
                "is_exceeded": False,
                "exceeded_by": 0,
                "days": [
                    { "date": "2026-11-03", "total": 52100000, "input": 3100000, "output": 440000, "cached": 48560000, "calls": 450, "cost_usd": 1.28, "cache_hit_pct": 94.0, "pct_of_weekly_limit": 10.42, "pct_of_daily_limit": 52.1 },
                    { "date": "2026-11-04", "total": 21800000, "input": 1400000, "output": 210000, "cached": 20190000, "calls": 190, "cost_usd": 0.54, "cache_hit_pct": 93.5, "pct_of_weekly_limit": 4.36, "pct_of_daily_limit": 21.8 },
                    { "date": "2026-11-05", "total": 5000000, "input": 300000, "output": 40000, "cached": 4660000, "calls": 50, "cost_usd": 0.12, "cache_hit_pct": 93.9, "pct_of_weekly_limit": 1.00, "pct_of_daily_limit": 5.0 }
                ]
            }
        },
        "summary": {
            "total_input": 13000000,
            "total_output": 1840000,
            "total_cached": 209880000,
            "total_tokens": 224720000,
            "total_calls": 1930,
            "estimated_cost_usd": 5.45,
            "cache_hit_pct": 94.2
        },
        "today": {
            "input": 3700000,
            "output": 530000,
            "cached": 64190000,
            "total": 68420000,
            "calls": 560,
            "cost_usd": 1.63,
            "cache_hit_pct": 94.5,
            "hours": { f"{h:02d}": { "input": 150000 if 9 <= h <= 15 else 0, "output": 22000 if 9 <= h <= 15 else 0, "cached": 2600000 if 9 <= h <= 15 else 0, "calls": 25 if 9 <= h <= 15 else 0 } for h in range(24) }
        },
        "current_hour_stats": {
            "hour": "15",
            "total": 2772000,
            "calls": 25,
            "input": 150000,
            "output": 22000,
            "cached": 2600000
        },
        "matched_project": {
            "workspace_name": "antigravity-token-tracker",
            "workspace_path": "c:\\Users\\developer\\projects\\antigravity-token-tracker",
            "input": 1200000,
            "output": 180000,
            "cached": 15600000,
            "calls": 140,
            "last_activity": "2026-11-10T14:45:00Z",
            "total": 16980000,
            "cost_usd": 0.43,
            "percent_of_total": 7.5,
            "cache_hit_pct": 92.8
        },
        "days": {
            "2026-11-09": { "input": 4500000, "output": 620000, "cached": 72280000, "total": 77400000, "calls": 680, "cost_usd": 1.88, "cache_hit_pct": 94.1, "hours": { f"{h:02d}": { "input": 200000 if 10 <= h <= 19 else 0, "output": 30000 if 10 <= h <= 19 else 0, "cached": 3500000 if 10 <= h <= 19 else 0, "calls": 30 if 10 <= h <= 19 else 0 } for h in range(24) } },
            "2026-11-10": { "input": 3700000, "output": 530000, "cached": 64190000, "total": 68420000, "calls": 560, "cost_usd": 1.63, "cache_hit_pct": 94.5, "hours": { f"{h:02d}": { "input": 150000 if 9 <= h <= 15 else 0, "output": 22000 if 9 <= h <= 15 else 0, "cached": 2600000 if 9 <= h <= 15 else 0, "calls": 25 if 9 <= h <= 15 else 0 } for h in range(24) } }
        },
        "hours": {},
        "projects": {
            "web-app-frontend": { "workspace_name": "web-app-frontend", "workspace_path": "/projects/web-app-frontend", "input": 4500000, "output": 680000, "cached": 75000000, "calls": 690, "total": 80180000, "cost_usd": 1.95, "percent_of_total": 35.7, "cache_hit_pct": 94.3, "last_activity": "2026-11-10T14:30:00Z" },
            "api-backend-python": { "workspace_name": "api-backend-python", "workspace_path": "/projects/api-backend-python", "input": 3800000, "output": 540000, "cached": 62000000, "calls": 560, "total": 66340000, "cost_usd": 1.61, "percent_of_total": 29.5, "cache_hit_pct": 94.2, "last_activity": "2026-11-10T13:20:00Z" },
            "antigravity-token-tracker": { "workspace_name": "antigravity-token-tracker", "workspace_path": "/projects/antigravity-token-tracker", "input": 2100000, "output": 310000, "cached": 35000000, "calls": 320, "total": 37410000, "cost_usd": 0.91, "percent_of_total": 16.6, "cache_hit_pct": 94.3, "last_activity": "2026-11-10T14:50:00Z" },
            "documentation-portal": { "workspace_name": "documentation-portal", "workspace_path": "/projects/documentation-portal", "input": 1500000, "output": 210000, "cached": 24000000, "calls": 210, "total": 25710000, "cost_usd": 0.63, "percent_of_total": 11.4, "cache_hit_pct": 94.1, "last_activity": "2026-11-09T18:00:00Z" }
        },
        "conversations": []
    }

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Antigravity Token Tracker CLI")
    parser.add_argument("--json", action="store_true", help="Sortie JSON brute")
    parser.add_argument("--summary", action="store_true", help="Résumé textuel dans le terminal")
    parser.add_argument("--markdown", action="store_true", help="Génère la carte Markdown pour Antigravity")
    parser.add_argument("--html", nargs="?", const="default", help="Génère le dashboard HTML")
    parser.add_argument("--demo", action="store_true", help="Génère un dashboard de démonstration propre et anonymisé pour publication Git")
    parser.add_argument("--serve", action="store_true", help="Lance le serveur local et ouvre le navigateur")
    parser.add_argument("--port", type=int, default=8765, help="Port pour le serveur HTTP (défaut: 8765)")
    parser.add_argument("--workspace", type=str, default="", help="Chemin du workspace actuel")
    parser.add_argument("--set-plan", type=str, default="", help="Définit le plan actif (Google AI Starter, Google AI Pro, Google AI Ultra, Custom)")
    parser.add_argument("--set-5h-quota", type=str, default="", help="Définit le quota 5h glissant (ex: 75M, 25000000)")
    parser.add_argument("--set-daily-quota", type=str, default="", help="Définit le quota journalier (ex: 100M, 50000000)")
    parser.add_argument("--set-weekly-quota", type=str, default="", help="Définit le quota hebdomadaire (ex: 500M, 1.5B)")
    
    args = parser.parse_args()

    # Handle demo generation
    if args.demo:
        demo_stats = generate_demo_stats()
        out_path = generate_html_dashboard(demo_stats)
        print(f"✅ Dashboard de démo anonymisé généré avec succès pour Git : {out_path}")
        return

    # Handle quota configuration updates if requested
    if args.set_plan or args.set_5h_quota or args.set_daily_quota or args.set_weekly_quota:
        cfg = load_config()
        if args.set_plan:
            cfg["active_plan"] = args.set_plan
            if args.set_plan in cfg.get("plans", {}) and not args.set_5h_quota and not args.set_daily_quota and not args.set_weekly_quota:
                cfg["rolling_5h_token_quota"] = cfg["plans"][args.set_plan].get("rolling_5h_token_quota", cfg.get("rolling_5h_token_quota", 75_000_000))
                cfg["daily_token_quota"] = cfg["plans"][args.set_plan].get("daily_token_quota", cfg.get("daily_token_quota", 100_000_000))
                cfg["weekly_token_quota"] = cfg["plans"][args.set_plan].get("weekly_token_quota", cfg.get("weekly_token_quota", 500_000_000))
        if args.set_5h_quota:
            cfg["rolling_5h_token_quota"] = parse_token_input(args.set_5h_quota)
        if args.set_daily_quota:
            cfg["daily_token_quota"] = parse_token_input(args.set_daily_quota)
        if args.set_weekly_quota:
            cfg["weekly_token_quota"] = parse_token_input(args.set_weekly_quota)
        save_config(cfg)
        print(f"✅ Configuration mise à jour : Plan={cfg['active_plan']} | Quota 5h={format_tokens(cfg['rolling_5h_token_quota'])} | Quota Semaine={format_tokens(cfg['weekly_token_quota'])}")
        return

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
        r5 = stats.get("rolling_5h_quota", {})
        w_quota = stats.get("week_quota", {})
        t_quota = stats.get("today_quota", {})
        plan = stats.get("quota_config", {}).get("active_plan", "Google AI Pro")
        r5_bar = make_progress_bar(r5.get("remaining_pct", 0), length=10)
        w_bar = make_progress_bar(w_quota.get("remaining_pct", 0), length=10)

        print("=" * 66)
        print("⚡ ANTIGRAVITY TOKEN TRACKER — QUOTAS 5H & HEBDOMADAIRES")
        print("=" * 66)
        print(f"💎 Formule Abonnement : {plan}")
        print(f"⏱️ Reste Instantané 5h  : {format_tokens(r5.get('remaining', 0))} / {format_tokens(r5.get('quota', 0))} ({r5.get('remaining_pct', 0)}% disponible) [{r5_bar}]")
        print(f"   ↳ Consommé 5h       : {format_tokens(r5.get('used', 0))} ({r5.get('used_pct', 0)}% de la limite 5h)")
        print(f"🗓️ Reste Cette Semaine : {format_tokens(w_quota.get('remaining', 0))} / {format_tokens(w_quota.get('quota', 0))} ({w_quota.get('remaining_pct', 0)}% disponible) [{w_bar}]")
        print(f"   ↳ Consommé Semaine  : {format_tokens(w_quota.get('total', 0))} ({w_quota.get('used_pct_of_weekly_limit', 0)}% de toute la limite weekly)")
        print(f"   ↳ Consommé Jour     : {format_tokens(today['total'])} ({t_quota.get('pct_of_weekly_limit', 0)}% de la limite weekly)")
        print("-" * 66)
        print(f"Total Consommé : {format_tokens(sum_data['total_tokens'])} ({sum_data['total_calls']} appels)")
        print(f"Input Tokens   : {format_tokens(sum_data['total_input'])}")
        print(f"Output Tokens  : {format_tokens(sum_data['total_output'])}")
        print(f"Cached Tokens  : {format_tokens(sum_data['total_cached'])} ({sum_data['cache_hit_pct']}% économisé)")
        print(f"Coût Estimé    : {format_cost(sum_data['estimated_cost_usd'])}")
        print("=" * 66)
    else:
        # Default: generate HTML and output Markdown
        path = generate_html_dashboard(stats)
        print(generate_markdown_banner(stats, current_ws_name=args.workspace))

if __name__ == "__main__":
    main()
