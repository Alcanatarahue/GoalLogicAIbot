import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from statistics import mean

import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


# ============================================================
# CONFIGURATION
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

PORT = int(os.getenv("PORT", "10000"))
OPENFOOT_BASE = "https://openfootapi.com"
CURRENT_SEASON = "2026/27"


# ============================================================
# HEALTH SERVER FOR RENDER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GoalLogic AI is running.")

    def log_message(self, format, *args):
        return


def start_health_server():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"GoalLogic AI is running on port {PORT}.")
    server.serve_forever()


# ============================================================
# OPENFOOT API
# ============================================================

def openfoot_headers():
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {OPENFOOT_API_KEY}"
    }


def openfoot_get(endpoint, params=None):
    url = f"{OPENFOOT_BASE}{endpoint}"

    try:
        response = requests.get(
            url,
            headers=openfoot_headers(),
            params=params,
            timeout=20
        )

        if response.status_code != 200:
            print("OpenFoot error:", response.status_code, response.text)
            return None

        payload = response.json()

        if "error" in payload:
            print("OpenFoot API error:", payload["error"])
            return None

        return payload.get("data", [])

    except Exception as e:
        print("OpenFoot request error:", e)
        return None


# ============================================================
# SEARCH TEAM
# ============================================================

def search_team(team_name):
    data = openfoot_get(
        "/v1/search",
        {"q": team_name}
    )

    if not data:
        return None

    if isinstance(data, dict):
        results = data.get("teams", [])
    else:
        results = data

    if not isinstance(results, list):
        return None

    team_name_lower = team_name.lower().strip()

    # Exact name first
    for team in results:
        name = str(team.get("name", "")).lower().strip()

        if name == team_name_lower:
            return team

    # Partial match
    for team in results:
        name = str(team.get("name", "")).lower()

        if team_name_lower in name or name in team_name_lower:
            return team

    return results[0] if results else None


# ============================================================
# GET TEAM MATCHES
# ============================================================

def get_team_matches(team_id):
    data = openfoot_get(
        "/v1/matches",
        {
            "team": team_id,
            "season": CURRENT_SEASON
        }
    )

    if not data:
        return []

    if isinstance(data, dict):
        matches = data.get("matches", [])
    else:
        matches = data

    if not isinstance(matches, list):
        return []

    finished = []

    for match in matches:
        status = str(match.get("status", "")).lower()

        if status in ["finished", "completed", "ft"]:
            finished.append(match)

    # Newest first
    finished.sort(
        key=lambda x: str(x.get("kickoffAt", "")),
        reverse=True
    )

    return finished


# ============================================================
# EXTRACT MATCH INFORMATION
# ============================================================

def get_team_id(team):
    return team.get("id")


def get_team_name(team):
    return team.get("name", "Unknown")


def extract_score(match):
    home = match.get("homeTeam", {})
    away = match.get("awayTeam", {})

    home_score = None
    away_score = None

    # Common score formats
    score = match.get("score")

    if isinstance(score, dict):
        home_score = score.get("home")
        away_score = score.get("away")

        if isinstance(home_score, dict):
            home_score = (
                home_score.get("current")
                or home_score.get("display")
                or home_score.get("goals")
            )

        if isinstance(away_score, dict):
            away_score = (
                away_score.get("current")
                or away_score.get("display")
                or away_score.get("goals")
            )

    # Alternative formats
    if home_score is None:
        home_score = match.get("homeScore")

    if away_score is None:
        away_score = match.get("awayScore")

    try:
        home_score = int(home_score)
        away_score = int(away_score)
    except Exception:
        return None, None

    return home_score, away_score


# ============================================================
# BUILD TEAM RECORD
# ============================================================

def build_team_records(matches, team_id):
    records = []

    for match in matches:
        home_team = match.get("homeTeam", {})
        away_team = match.get("awayTeam", {})

        home_id = home_team.get("id")
        away_id = away_team.get("id")

        home_score, away_score = extract_score(match)

        if home_score is None or away_score is None:
            continue

        if str(home_id) == str(team_id):
            goals_for = home_score
            goals_against = away_score
            venue = "home"

        elif str(away_id) == str(team_id):
            goals_for = away_score
            goals_against = home_score
            venue = "away"

        else:
            continue

        total_goals = goals_for + goals_against

        if goals_for > goals_against:
            result = "W"
        elif goals_for == goals_against:
            result = "D"
        else:
            result = "L"

        records.append({
            "goals_for": goals_for,
            "goals_against": goals_against,
            "total_goals": total_goals,
            "result": result,
            "venue": venue
        })

    return records


# ============================================================
# STATISTICS
# ============================================================

def calculate_stats(records):
    if not records:
        return None

    total = len(records)

    wins = sum(1 for r in records if r["result"] == "W")
    draws = sum(1 for r in records if r["result"] == "D")
    losses = sum(1 for r in records if r["result"] == "L")

    goals_for = sum(r["goals_for"] for r in records)
    goals_against = sum(r["goals_against"] for r in records)

    over_15 = sum(
        1 for r in records
        if r["total_goals"] >= 2
    )

    over_25 = sum(
        1 for r in records
        if r["total_goals"] >= 3
    )

    btts = sum(
        1 for r in records
        if r["goals_for"] >= 1 and r["goals_against"] >= 1
    )

    clean_sheets = sum(
        1 for r in records
        if r["goals_against"] == 0
    )

    scoring = sum(
        1 for r in records
        if r["goals_for"] >= 1
    )

    conceding = sum(
        1 for r in records
        if r["goals_against"] >= 1
    )

    return {
        "sample": total,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "avg_for": goals_for / total,
        "avg_against": goals_against / total,
        "avg_total": (goals_for + goals_against) / total,
        "over15": over_15 / total * 100,
        "over25": over_25 / total * 100,
        "btts": btts / total * 100,
        "clean": clean_sheets / total * 100,
        "scoring": scoring / total * 100,
        "conceding": conceding / total * 100
    }


# ============================================================
# FORM STRING
# ============================================================

def form_string(records):
    return "".join(r["result"] for r in records)


# ============================================================
# FORMATTING
# ============================================================

def pct(value):
    return f"{value:.0f}%"


def stat_block(name, stats, label="LAST 5"):
    if not stats:
        return f"{name.upper()} — {label}\nNo usable match data."

    return (
        f"{name.upper()} — {label}\n"
        f"Form: {form_string([]) if False else ''}\n"
        f"W/D/L: {stats['wins']}/{stats['draws']}/{stats['losses']}\n"
        f"Goals scored: {stats['goals_for']}\n"
        f"Goals conceded: {stats['goals_against']}\n"
        f"Avg scored: {stats['avg_for']:.1f}\n"
        f"Avg conceded: {stats['avg_against']:.1f}\n"
        f"Avg total goals: {stats['avg_total']:.1f}\n"
        f"Over 1.5: {pct(stats['over15'])}\n"
        f"Over 2.5: {pct(stats['over25'])}\n"
        f"BTTS: {pct(stats['btts'])}\n"
        f"Scoring consistency: {pct(stats['scoring'])}\n"
        f"Clean sheets: {pct(stats['clean'])}\n"
        f"Sample: {stats['sample']} matches"
    )


# ============================================================
# TEAM PROFILE
# ============================================================

def attacking_profile(name, overall, venue):
    if not overall:
        return ""

    attack_level = (
        "🔥 STRONG"
        if overall["avg_for"] >= 1.8
        else "🟢 GOOD"
        if overall["avg_for"] >= 1.3
        else "🟡 MODERATE"
        if overall["avg_for"] >= 1.0
        else "🔴 LOW"
    )

    vulnerability = (
        "⚠️ HIGH"
        if overall["avg_against"] >= 1.7
        else "🟡 MODERATE"
        if overall["avg_against"] >= 1.2
        else "🟢 LOW"
    )

    text = (
        f"🔥 {name.upper()} — ATTACKING PROFILE\n"
        f"Attack level: {attack_level}\n"
        f"Avg goals scored: {overall['avg_for']:.2f}\n"
        f"Scoring consistency: {pct(overall['scoring'])}\n"
    )

    if venue:
        text += (
            f"Recent venue avg scored: {venue['avg_for']:.2f}\n"
            f"Recent venue scoring: {pct(venue['scoring'])}\n"
        )

    text += (
        f"Defensive vulnerability: {vulnerability}\n"
        f"Avg goals conceded: {overall['avg_against']:.2f}"
    )

    return text


def defensive_profile(name, overall, venue):
    if not overall:
        return ""

    defense_level = (
        "🛡️ STRONG"
        if overall["avg_against"] <= 0.8
        else "🟢 GOOD"
        if overall["avg_against"] <= 1.2
        else "🟡 MODERATE"
        if overall["avg_against"] <= 1.7
        else "🔴 VULNERABLE"
    )

    text = (
        f"🛡️ {name.upper()} — DEFENSIVE PROFILE\n"
        f"Defensive level: {defense_level}\n"
        f"Avg conceded: {overall['avg_against']:.2f}\n"
        f"Clean sheets: {pct(overall['clean'])}\n"
        f"Conceding rate: {pct(overall['conceding'])}\n"
    )

    if venue:
        text += (
            f"Recent venue avg conceded: {venue['avg_against']:.2f}\n"
            f"Recent venue clean sheets: {pct(venue['clean'])}"
        )

    return text


# ============================================================
# GOAL ENVIRONMENT
# ============================================================

def goal_environment(stats1, stats2):
    avg_attack = mean([
        stats1["avg_for"],
        stats2["avg_for"]
    ])

    avg_conceded = mean([
        stats1["avg_against"],
        stats2["avg_against"]
    ])

    combined = avg_attack + avg_conceded

    if combined >= 3.0:
        level = "🔥 HIGH"
    elif combined >= 2.5:
        level = "🟢 GOOD"
    elif combined >= 2.0:
        level = "🟡 MODERATE"
    else:
        level = "🔴 LOW"

    return avg_attack, avg_conceded, combined, level


# ============================================================
# CONFIDENCE ENGINE
# ============================================================

def confidence_score(overall, venue, market):
    if not overall:
        return 0

    if market == "over15":
        overall_signal = overall["over15"]

        venue_signal = (
            venue["over15"]
            if venue
            else overall_signal
        )

    elif market == "over25":
        overall_signal = overall["over25"]

        venue_signal = (
            venue["over25"]
            if venue
            else overall_signal
        )

    elif market == "btts":
        overall_signal = overall["btts"]

        venue_signal = (
            venue["btts"]
            if venue
            else overall_signal
        )

    else:
        return 0

    reliability = min(
        100,
        (venue["sample"] / 7) * 100
        if venue
        else 50
    )

    confidence = (
        overall_signal * 0.50
        + venue_signal * 0.30
        + reliability * 0.20
    )

    # Conservative caps for small venue samples
    if venue:
        if venue["sample"] < 3:
            confidence = min(confidence, 75)
        elif venue["sample"] < 5:
            confidence = min(confidence, 82)
        elif venue["sample"] < 7:
            confidence = min(confidence, 86)
        else:
            confidence = min(confidence, 90)
    else:
        confidence = min(confidence, 80)

    return round(confidence)


def grade(confidence):
    if confidence >= 80:
        return "🔥 STRONG"
    elif confidence >= 70:
        return "🟢 GOOD"
    elif confidence >= 60:
        return "🟡 MODERATE"
    return "🔴 AVOID"


def advice(confidence):
    if confidence >= 70:
        return "BET"
    elif confidence >= 60:
        return "CAUTION"
    return "AVOID"


# ============================================================
# MARKET REASONS
# ============================================================

def market_reason(
    market,
    stats1,
    stats2,
    venue1,
    venue2,
    confidence
):
    reasons = []

    if market == "Over 1.5 Goals":
        if stats1["over15"] >= 80:
            reasons.append(
                f"Team 1 has a {stats1['over15']:.0f}% "
                f"recent Over 1.5 rate"
            )

        if stats2["over15"] >= 80:
            reasons.append(
                f"Team 2 has a {stats2['over15']:.0f}% "
                f"recent Over 1.5 rate"
            )

        combined = (
            stats1["avg_total"] +
            stats2["avg_total"]
        ) / 2

        if combined >= 2.5:
            reasons.append(
                f"combined recent goal average is {combined:.1f}"
            )

        if venue1 and venue1["over15"] >= 80:
            reasons.append(
                f"recent home Over 1.5 rate is "
                f"{venue1['over15']:.0f}%"
            )

        if venue2 and venue2["over15"] >= 80:
            reasons.append(
                f"recent away Over 1.5 rate is "
                f"{venue2['over15']:.0f}%"
            )

    elif market == "Over 2.5 Goals":
        if stats1["over25"] >= 70:
            reasons.append(
                f"Team 1 has a {stats1['over25']:.0f}% "
                f"recent Over 2.5 rate"
            )

        if stats2["over25"] >= 70:
            reasons.append(
                f"Team 2 has a {stats2['over25']:.0f}% "
                f"recent Over 2.5 rate"
            )

        combined = (
            stats1["avg_total"] +
            stats2["avg_total"]
        ) / 2

        if combined >= 2.8:
            reasons.append(
                f"combined recent goal average is {combined:.1f}"
            )

        if venue1 and venue1["over25"] < 50:
            reasons.append(
                f"recent home Over 2.5 rate is only "
                f"{venue1['over25']:.0f}% — counter-signal"
            )

        if venue2 and venue2["over25"] < 50:
            reasons.append(
                f"recent away Over 2.5 rate is only "
                f"{venue2['over25']:.0f}% — counter-signal"
            )

    elif market == "BTTS — Yes":
        if stats1["scoring"] >= 80:
            reasons.append(
                f"Team 1 scores in {stats1['scoring']:.0f}% "
                f"of recent matches"
            )

        if stats2["scoring"] >= 80:
            reasons.append(
                f"Team 2 scores in {stats2['scoring']:.0f}% "
                f"of recent matches"
            )

        if venue1 and venue1["btts"] >= 70:
            reasons.append(
                f"recent home BTTS rate is "
                f"{venue1['btts']:.0f}%"
            )

        if venue2 and venue2["btts"] >= 70:
            reasons.append(
                f"recent away BTTS rate is "
                f"{venue2['btts']:.0f}%"
            )

        if venue1 and venue1["clean"] >= 50:
            reasons.append(
                f"Team 1 recent home clean-sheet rate is "
                f"{venue1['clean']:.0f}% — counter-signal"
            )

        if venue2 and venue2["clean"] >= 50:
            reasons.append(
                f"Team 2 recent away clean-sheet rate is "
                f"{venue2['clean']:.0f}% — counter-signal"
            )

    if not reasons:
        reasons.append(
            "Recent statistics provide a mixed signal for this market"
        )

    return "; ".join(reasons)
    


# ============================================================
# ANALYSIS
# ============================================================

def analyze_match(team1_name, team2_name):
    team1 = search_team(team1_name)
    team2 = search_team(team2_name)

    if not team1:
        return f"❌ I couldn't find {team1_name} in OpenFoot."

    if not team2:
        return f"❌ I couldn't find {team2_name} in OpenFoot."

    team1_id = get_team_id(team1)
    team2_id = get_team_id(team2)

    if not team1_id or not team2_id:
        return "❌ Team information could not be resolved."

    matches1 = get_team_matches(team1_id)
    matches2 = get_team_matches(team2_id)

    records1 = build_team_records(matches1, team1_id)
    records2 = build_team_records(matches2, team2_id)

    records1 = records1[:5]
    records2 = records2[:5]

    stats1 = calculate_stats(records1)
    stats2 = calculate_stats(records2)

    if not stats1 or not stats2:
        return (
            "⚠️ Football data could not be retrieved for both teams.\n"
            "Please try again."
        )

    # Recent venue records
    home_records = [
        r for r in records1
        if r["venue"] == "home"
    ]

    away_records = [
        r for r in records2
        if r["venue"] == "away"
    ]

    home_stats = calculate_stats(home_records)
    away_stats = calculate_stats(away_records)

    # Goal environment
    avg_attack, avg_conceded, combined, environment = (
        goal_environment(stats1, stats2)
    )

    # Confidence
    over15_1 = confidence_score(
        stats1,
        home_stats,
        "over15"
    )

    over15_2 = confidence_score(
        stats2,
        away_stats,
        "over15"
    )

    over25_1 = confidence_score(
        stats1,
        home_stats,
        "over25"
    )

    over25_2 = confidence_score(
        stats2,
        away_stats,
        "over25"
    )

    btts_1 = confidence_score(
        stats1,
        home_stats,
        "btts"
    )

    btts_2 = confidence_score(
        stats2,
        away_stats,
        "btts"
    )

    over15_conf = round((over15_1 + over15_2) / 2)
    over25_conf = round((over25_1 + over25_2) / 2)

    # BTTS needs both teams to contribute to the signal
    btts_conf = round((btts_1 + btts_2) / 2)

    # Small adjustment based on goal environment
    if combined >= 3.0:
        over15_conf = min(90, over15_conf + 4)
        over25_conf = min(90, over25_conf + 3)

    if combined < 2.0:
        over15_conf = max(0, over15_conf - 5)
        over25_conf = max(0, over25_conf - 7)

    markets = {
        "Over 1.5 Goals": over15_conf,
        "Over 2.5 Goals": over25_conf,
        "BTTS — Yes": btts_conf
    }

    primary_market = max(
        markets,
        key=markets.get
    )

    primary_conf = markets[primary_market]

    # Form
    form1 = form_string(records1)
    form2 = form_string(records2)

    if stats1["wins"] > stats2["wins"]:
        form_assessment = (
            f"{get_team_name(team1)} has the stronger recent form."
        )
    elif stats2["wins"] > stats1["wins"]:
        form_assessment = (
            f"{get_team_name(team2)} has the stronger recent form."
        )
    else:
        form_assessment = (
            "Both teams have similar recent win totals."
        )

    # ========================================================
    # BUILD RESPONSE
    # ========================================================

    output = (
        "⚽ GOALLOGIC AI — ADVANCED ANALYSIS\n\n"
        f"{get_team_name(team1)} vs {get_team_name(team2)}\n"
        f"Season: {CURRENT_SEASON}\n\n"
    )

    # Team 1
    output += (
        f"📊 {get_team_name(team1).upper()} — LAST 5\n"
        f"Form: {form1}\n"
        f"W/D/L: {stats1['wins']}/{stats1['draws']}/{stats1['losses']}\n"
        f"Goals scored: {stats1['goals_for']}\n"
        f"Goals conceded: {stats1['goals_against']}\n"
        f"Avg scored: {stats1['avg_for']:.1f}\n"
        f"Avg conceded: {stats1['avg_against']:.1f}\n"
        f"Avg total goals: {stats1['avg_total']:.1f}\n"
        f"Over 1.5: {pct(stats1['over15'])}\n"
        f"Over 2.5: {pct(stats1['over25'])}\n"
        f"BTTS: {pct(stats1['btts'])}\n"
        f"Scoring consistency: {pct(stats1['scoring'])}\n"
        f"Clean sheets: {pct(stats1['clean'])}\n"
        f"Sample: {stats1['sample']} matches\n\n"
    )

    if home_stats:
        output += (
            f"🏠 {get_team_name(team1).upper()} — RECENT HOME\n"
            f"Form: {form_string(home_records)}\n"
            f"W/D/L: {home_stats['wins']}/{home_stats['draws']}/{home_stats['losses']}\n"
            f"Avg scored: {home_stats['avg_for']:.1f}\n"
            f"Avg conceded: {home_stats['avg_against']:.1f}\n"
            f"Over 1.5: {pct(home_stats['over15'])}\n"
            f"Over 2.5: {pct(home_stats['over25'])}\n"
            f"BTTS: {pct(home_stats['btts'])}\n"
            f"Clean sheets: {pct(home_stats['clean'])}\n"
            f"Sample: {home_stats['sample']} matches\n"
        )

        if home_stats["sample"] < 3:
            output += "⚠️ Very small sample.\n"
        elif home_stats["sample"] < 5:
            output += "⚠️ Limited sample.\n"

        output += "\n"

    # Team 2
    output += (
        f"📊 {get_team_name(team2).upper()} — LAST 5\n"
        f"Form: {form2}\n"
        f"W/D/L: {stats2['wins']}/{stats2['draws']}/{stats2['losses']}\n"
        f"Goals scored: {stats2['goals_for']}\n"
        f"Goals conceded: {stats2['goals_against']}\n"
        f"Avg scored: {stats2['avg_for']:.1f}\n"
        f"Avg conceded: {stats2['avg_against']:.1f}\n"
        f"Avg total goals: {stats2['avg_total']:.1f}\n"
        f"Over 1.5: {pct(stats2['over15'])}\n"
        f"Over 2.5: {pct(stats2['over25'])}\n"
        f"BTTS: {pct(stats2['btts'])}\n"
        f"Scoring consistency: {pct(stats2['scoring'])}\n"
        f"Clean sheets: {pct(stats2['clean'])}\n"
        f"Sample: {stats2['sample']} matches\n\n"
    )

    if away_stats:
        output += (
            f"✈️ {get_team_name(team2).upper()} — RECENT AWAY\n"
            f"Form: {form_string(away_records)}\n"
            f"W/D/L: {away_stats['wins']}/{away_stats['draws']}/{away_stats['losses']}\n"
            f"Avg scored: {away_stats['avg_for']:.1f}\n"
            f"Avg conceded: {away_stats['avg_against']:.1f}\n"
            f"Over 1.5: {pct(away_stats['over15'])}\n"
            f"Over 2.5: {pct(away_stats['over25'])}\n"
            f"BTTS: {pct(away_stats['btts'])}\n"
            f"Clean sheets: {pct(away_stats['clean'])}\n"
            f"Sample: {away_stats['sample']} matches\n"
        )

        if away_stats["sample"] < 3:
            output += "⚠️ Very small sample.\n"
        elif away_stats["sample"] < 5:
            output += "⚠️ Limited sample.\n"

        output += "\n"

    # Profiles
    output += (
        attacking_profile(
            get_team_name(team1),
            stats1,
            home_stats
        )
        + "\n\n"
    )

    output += (
        defensive_profile(
            get_team_name(team2),
            stats2,
            away_stats
        )
        + "\n\n"
    )

    # Goal environment
    output += (
        "🎯 GOAL & DEFENSIVE INTELLIGENCE\n"
        f"Average attacking output: {avg_attack:.2f} goals\n"
        f"Average goals conceded: {avg_conceded:.2f} goals\n"
        f"Combined goal environment: {combined:.2f}\n"
        f"Goal environment: {environment}\n\n"
    )

    # Form assessment
    output += (
        "📈 FORM ASSESSMENT\n"
        f"{form_assessment}\n\n"
    )

    # Market signals
    output += "📊 MARKET SIGNALS\n\n"

    for market, conf in markets.items():
        output += (
            f"{market} — Confidence {conf}%\n"
            f"Grade: {grade(conf)}\n"
            f"Advice: {advice(conf)}\n"
            f"Reason: "
            f"{market_reason(market, stats1, stats2, home_stats, away_stats, conf)}\n\n"
        )

    # Primary signal
    output += (
        "⭐ PRIMARY STATISTICAL SIGNAL\n"
        f"{primary_market} — Confidence {primary_conf}%\n"
        f"Grade: {grade(primary_conf)}\n"
        f"Advice: {advice(primary_conf)}\n\n"
        "⚠️ Statistical analysis is not a guarantee of the match outcome. "
        "Use confidence figures as indicators, not certainty."
    )

    return output


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "⚽ GOALLOGIC AI\n\n"
        "Advanced football statistical analysis.\n\n"
        "Send a match like:\n"
        "Chelsea vs Arsenal\n\n"
        "Or use:\n"
        "/analyze Chelsea vs Arsenal\n\n"
        "Use /apitest to check the OpenFoot connection."
    )

    await update.message.reply_text(message)


async def api_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = openfoot_get(
        "/v1/search",
        {"q": "Chelsea"}
    )

    if data is not None:
        await update.message.reply_text(
            "✅ OPENFOOT TEST PASSED\n\n"
            "OpenFoot API is connected successfully."
        )
    else:
        await update.message.reply_text(
            "❌ OPENFOOT TEST FAILED\n\n"
            "The API could not be reached or the API key was rejected."
        )


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args).strip()

    if not text:
        await update.message.reply_text(
            "Use:\n/analyze Chelsea vs Arsenal"
        )
        return

    result = process_match_text(text)

    await update.message.reply_text(
        result,
        disable_web_page_preview=True
    )


async def normal_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if " vs " not in text.lower():
        await update.message.reply_text(
            "Send a match like:\nChelsea vs Arsenal"
        )
        return

    result = process_match_text(text)

    await update.message.reply_text(
        result,
        disable_web_page_preview=True
    )


# ============================================================
# MATCH TEXT PROCESSOR
# ============================================================

def process_match_text(text):
    parts = re.split(
        r"\s+vs\.?\s+|\s+v\.?\s+",
        text,
        flags=re.IGNORECASE
    )

    if len(parts) != 2:
        return (
            "❌ Please use this format:\n"
            "Chelsea vs Arsenal"
        )

    team1 = parts[0].strip()
    team2 = parts[1].strip()

    if not team1 or not team2:
        return (
            "❌ Please provide two teams.\n\n"
            "Example:\n"
            "Chelsea vs Arsenal"
        )

    return analyze_match(team1, team2)


# ============================================================
# MAIN
# ============================================================

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not OPENFOOT_API_KEY:
        raise RuntimeError(
            "OPENFOOT_API_KEY is missing."
        )

    # Start Render health server first
    health_thread = threading.Thread(
        target=start_health_server,
        daemon=True
    )

    health_thread.start()

    print("Starting GoalLogic AI...")

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("apitest", api_test)
    )

    application.add_handler(
        CommandHandler("analyze", analyze_command)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            normal_message
        )
    )

    print("GoalLogic AI is ready.")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
