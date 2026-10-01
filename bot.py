import os
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


# =========================================================
# CONFIG
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

PORT = int(os.getenv("PORT", "10000"))
OPENFOOT_BASE = "https://openfootapi.com"
CURRENT_SEASON = "2026/27"


# =========================================================
# RENDER HEALTH SERVER
# =========================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GoalLogic AI is running.")

    def log_message(self, format, *args):
        return


def start_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"GoalLogic AI is running on port {PORT}.")
    server.serve_forever()


# =========================================================
# OPENFOOT REQUEST
# =========================================================

def openfoot_get(endpoint, params=None):

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {OPENFOOT_API_KEY}"
    }

    try:
        response = requests.get(
            OPENFOOT_BASE + endpoint,
            headers=headers,
            params=params,
            timeout=20
        )

        if response.status_code != 200:
            print("OpenFoot error:", response.status_code, response.text)
            return None

        body = response.json()
        return body.get("data")

    except Exception as e:
        print("OpenFoot request error:", e)
        return None


# =========================================================
# SEARCH TEAM
# =========================================================

def search_team(team_name):

    data = openfoot_get(
        "/v1/search",
        {"q": team_name}
    )

    if not data:
        return None

    # OpenFoot normally returns a list of search results.
    if isinstance(data, dict):
        results = data.get("teams") or data.get("results") or data.get("data") or []
    else:
        results = data

    for item in results:

        if not isinstance(item, dict):
            continue

        item_type = str(
            item.get("type") or item.get("entityType") or ""
        ).lower()

        team = item.get("team") if isinstance(item.get("team"), dict) else item

        name = str(
            team.get("name")
            or item.get("name")
            or ""
        )

        if not name:
            continue

        if item_type and "team" not in item_type:
            continue

        if name.lower() == team_name.lower():
            return team

    # Fallback: first result that has an ID and name
    for item in results:

        if not isinstance(item, dict):
            continue

        team = item.get("team") if isinstance(item.get("team"), dict) else item

        if team.get("id") and team.get("name"):
            return team

    return None


# =========================================================
# GET TEAM MATCHES
# =========================================================

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

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        return (
            data.get("matches")
            or data.get("results")
            or data.get("data")
            or []
        )

    return []


# =========================================================
# HELPERS
# =========================================================

def get_team_id(team):
    return team.get("id")


def get_team_name(team):
    return team.get("name", "Unknown")


def get_status(match):
    return str(match.get("status", "")).lower()


def get_home_team(match):
    home = match.get("homeTeam")
    return home if isinstance(home, dict) else {}


def get_away_team(match):
    away = match.get("awayTeam")
    return away if isinstance(away, dict) else {}


def get_score(match):

    score = match.get("score")

    if not isinstance(score, dict):
        return None, None

    # Different providers can use different names.
    home_score = score.get("home")
    away_score = score.get("away")

    if isinstance(home_score, dict):
        home_score = (
            home_score.get("goals")
            or home_score.get("score")
            or home_score.get("current")
        )

    if isinstance(away_score, dict):
        away_score = (
            away_score.get("goals")
            or away_score.get("score")
            or away_score.get("current")
        )

    try:
        return int(home_score), int(away_score)
    except:
        return None, None


def is_finished(match):

    status = get_status(match)

    finished_words = [
        "finished",
        "ft",
        "fulltime",
        "completed",
        "complete"
    ]

    return any(word in status for word in finished_words)


def team_match_result(match, team_id):

    home = get_home_team(match)
    away = get_away_team(match)

    home_id = home.get("id")
    away_id = away.get("id")

    hs, aws = get_score(match)

    if hs is None or aws is None:
        return None

    if team_id == home_id:

        if hs > aws:
            return "W"

        if hs < aws:
            return "L"

        return "D"

    if team_id == away_id:

        if aws > hs:
            return "W"

        if aws < hs:
            return "L"

        return "D"

    return None


# =========================================================
# ANALYZE MATCHES
# =========================================================

def analyze_matches(matches, team_id, limit=5):

    completed = []

    for match in matches:

        if not is_finished(match):
            continue

        result = team_match_result(match, team_id)

        if result is None:
            continue

        home = get_home_team(match)
        away = get_away_team(match)

        hs, aws = get_score(match)

        if hs is None or aws is None:
            continue

        if team_id == home.get("id"):
            gf = hs
            ga = aws
        else:
            gf = aws
            ga = hs

        completed.append({
            "match": match,
            "result": result,
            "gf": gf,
            "ga": ga
        })

    # Most recent first where kickoff date is available.
    completed.sort(
        key=lambda x: x["match"].get("kickoffAt", ""),
        reverse=True
    )

    selected = completed[:limit]

    if not selected:
        return None

    wins = sum(1 for x in selected if x["result"] == "W")
    draws = sum(1 for x in selected if x["result"] == "D")
    losses = sum(1 for x in selected if x["result"] == "L")

    goals_for = sum(x["gf"] for x in selected)
    goals_against = sum(x["ga"] for x in selected)

    over15 = sum(
        1 for x in selected
        if x["gf"] + x["ga"] > 1
    )

    over25 = sum(
        1 for x in selected
        if x["gf"] + x["ga"] > 2
    )

    btts = sum(
        1 for x in selected
        if x["gf"] > 0 and x["ga"] > 0
    )

    clean_sheets = sum(
        1 for x in selected
        if x["ga"] == 0
    )

    scoring = sum(
        1 for x in selected
        if x["gf"] > 0
    )

    n = len(selected)

    return {
        "matches": selected,
        "form": "".join(x["result"] for x in selected),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "gf": goals_for,
        "ga": goals_against,
        "over15": round(over15 / n * 100),
        "over25": round(over25 / n * 100),
        "btts": round(btts / n * 100),
        "clean": round(clean_sheets / n * 100),
        "scoring": round(scoring / n * 100),
        "count": n
    }


# =========================================================
# HOME / AWAY SPLIT
# =========================================================

def analyze_home_away(matches, team_id, venue, limit=5):

    venue_matches = []

    for match in matches:

        home = get_home_team(match)
        away = get_away_team(match)

        if venue == "home":

            if home.get("id") != team_id:
                continue

        elif venue == "away":

            if away.get("id") != team_id:
                continue

        else:
            continue

        if not is_finished(match):
            continue

        venue_matches.append(match)

    return analyze_matches(
        venue_matches,
        team_id,
        limit
    )


# =========================================================
# FORMAT ANALYSIS
# =========================================================

def format_stats(stats, title):

    if not stats:
        return f"""
📍 {title}

No recent matches were available.
"""

    return f"""
📍 {title}

Form: {stats["form"]}
W/D/L: {stats["wins"]}/{stats["draws"]}/{stats["losses"]}
Goals: {stats["gf"]} scored / {stats["ga"]} conceded
Over 1.5: {stats["over15"]}%
Over 2.5: {stats["over25"]}%
BTTS: {stats["btts"]}%
Clean sheets: {stats["clean"]}%
"""


# =========================================================
# MARKET ANALYSIS
# =========================================================

def calculate_markets(home_overall, away_overall, home_split, away_split):

    markets = []

    # -----------------------------------------------------
    # OVER 1.5
    # -----------------------------------------------------

    over15_values = []

    for stats in [
        home_overall,
        away_overall,
        home_split,
        away_split
    ]:
        if stats:
            over15_values.append(stats["over15"])

    if len(over15_values) >= 2:

        confidence = round(sum(over15_values) / len(over15_values))

        if confidence >= 70:

            markets.append({
                "market": "Over 1.5 Goals",
                "confidence": min(confidence, 88),
                "advice": "BET",
                "reason": "Recent overall and venue-specific goal patterns support at least two total goals."
            })

        elif confidence >= 55:

            markets.append({
                "market": "Over 1.5 Goals",
                "confidence": confidence,
                "advice": "CAUTION",
                "reason": "The goal trend is positive but not strong enough for a high-confidence signal."
            })

    # -----------------------------------------------------
    # OVER 2.5
    # -----------------------------------------------------

    over25_values = []

    for stats in [
        home_overall,
        away_overall,
        home_split,
        away_split
    ]:
        if stats:
            over25_values.append(stats["over25"])

    if len(over25_values) >= 2:

        confidence = round(sum(over25_values) / len(over25_values))

        if confidence >= 60:

            markets.append({
                "market": "Over 2.5 Goals",
                "confidence": min(confidence, 82),
                "advice": "BET",
                "reason": "The combined recent overall and home/away samples show a strong Over 2.5 trend."
            })

        elif confidence >= 50:

            markets.append({
                "market": "Over 2.5 Goals",
                "confidence": confidence,
                "advice": "CAUTION",
                "reason": "The Over 2.5 trend exists but is not consistent enough for a strong signal."
            })

    # -----------------------------------------------------
    # BTTS
    # -----------------------------------------------------

    btts_values = []

    for stats in [
        home_overall,
        away_overall,
        home_split,
        away_split
    ]:
        if stats:
            btts_values.append(stats["btts"])

    if len(btts_values) >= 2:

        confidence = round(sum(btts_values) / len(btts_values))

        if confidence >= 60:

            markets.append({
                "market": "BTTS — Yes",
                "confidence": min(confidence, 82),
                "advice": "BET",
                "reason": "Recent scoring patterns indicate a reasonable probability of both teams scoring."
            })

        elif confidence >= 50:

            markets.append({
                "market": "BTTS — Yes",
                "confidence": confidence,
                "advice": "CAUTION",
                "reason": "Both teams have shown some scoring potential, but the pattern is mixed."
            })

    return markets


# =========================================================
# MAIN ANALYSIS
# =========================================================

def analyze_fixture(team1_name, team2_name):

    team1 = search_team(team1_name)
    team2 = search_team(team2_name)

    if not team1:
        return f"❌ I couldn't find {team1_name} in OpenFoot."

    if not team2:
        return f"❌ I couldn't find {team2_name} in OpenFoot."

    team1_id = get_team_id(team1)
    team2_id = get_team_id(team2)

    if not team1_id or not team2_id:
        return "⚠️ Team IDs could not be retrieved."

    team1_matches = get_team_matches(team1_id)
    team2_matches = get_team_matches(team2_id)

    if not team1_matches:
        return f"⚠️ Football data could not be retrieved for {team1_name}."

    if not team2_matches:
        return f"⚠️ Football data could not be retrieved for {team2_name}."

    # Overall form
    team1_overall = analyze_matches(team1_matches, team1_id)
    team2_overall = analyze_matches(team2_matches, team2_id)

    # Venue-specific form
    team1_home = analyze_home_away(
        team1_matches,
        team1_id,
        "home"
    )

    team2_away = analyze_home_away(
        team2_matches,
        team2_id,
        "away"
    )

    if not team1_overall or not team2_overall:
        return "⚠️ Not enough completed matches were found for analysis."

    # Market signals
    markets = calculate_markets(
        team1_overall,
        team2_overall,
        team1_home,
        team2_away
    )

    # Form assessment
    team1_points = (
        team1_overall["wins"] * 3 +
        team1_overall["draws"]
    )

    team2_points = (
        team2_overall["wins"] * 3 +
        team2_overall["draws"]
    )

    if team1_points > team2_points:
        form_assessment = f"{team1_name} has the stronger recent form."

    elif team2_points > team1_points:
        form_assessment = f"{team2_name} has the stronger recent form."

    else:
        form_assessment = "Both teams have similar recent form."

    # -----------------------------------------------------
    # OUTPUT
    # -----------------------------------------------------

    response = f"""
⚽ GOALLOGIC AI — ADVANCED ANALYSIS

{team1_name} vs {team2_name}
Season: {CURRENT_SEASON}

━━━━━━━━━━━━━━━━━━
📊 {team1_name.upper()} — LAST 5
━━━━━━━━━━━━━━━━━━
{format_stats(team1_overall, "Overall")}

━━━━━━━━━━━━━━━━━━
🏠 {team1_name.upper()} — RECENT HOME
━━━━━━━━━━━━━━━━━━
{format_stats(team1_home, "Home matches")}

━━━━━━━━━━━━━━━━━━
📊 {team2_name.upper()} — LAST 5
━━━━━━━━━━━━━━━━━━
{format_stats(team2_overall, "Overall")}

━━━━━━━━━━━━━━━━━━
✈️ {team2_name.upper()} — RECENT AWAY
━━━━━━━━━━━━━━━━━━
{format_stats(team2_away, "Away matches")}

━━━━━━━━━━━━━━━━━━
📈 FORM ASSESSMENT
━━━━━━━━━━━━━━━━━━

{form_assessment}

━━━━━━━━━━━━━━━━━━
🎯 MARKET SIGNALS
━━━━━━━━━━━━━━━━━━
"""

    if markets:

        for market in markets:

            response += f"""
• {market["market"]}
  Confidence: {market["confidence"]}%
  Advice: {market["advice"]}
  Reason: {market["reason"]}
"""

        # Primary signal = highest confidence
        primary = max(
            markets,
            key=lambda x: x["confidence"]
        )

        response += f"""
━━━━━━━━━━━━━━━━━━
⭐ PRIMARY SIGNAL
━━━━━━━━━━━━━━━━━━

{primary["market"]}
Confidence: {primary["confidence"]}%
Advice: {primary["advice"]}
"""

    else:

        response += """
No strong statistical market signal was found.

Advice: AVOID
"""

    response += """
━━━━━━━━━━━━━━━━━━
⚠️ RISK WARNING
━━━━━━━━━━━━━━━━━━

This is statistical analysis, not a guaranteed result.

Home/away trends are based on recent completed matches available from OpenFoot. Injuries, lineups, tactics, schedule changes and late team news can affect the actual match.
"""

    return response


# =========================================================
# TELEGRAM COMMANDS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "⚽ Welcome to GoalLogic AI!\n\n"
        "Send a match like:\n"
        "Chelsea vs Arsenal\n\n"
        "Or use:\n"
        "/analyze Chelsea vs Arsenal\n\n"
        "Use /apitest to test the OpenFoot connection."
    )


async def apitest(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not OPENFOOT_API_KEY:

        await update.message.reply_text(
            "❌ OPENFOOT_API_KEY is missing from Render."
        )
        return

    data = openfoot_get("/v1/health")

    if data is not None:

        await update.message.reply_text(
            "✅ OPENFOOT TEST PASSED\n\n"
            "OpenFoot API is connected successfully."
        )

    else:

        await update.message.reply_text(
            "❌ OPENFOOT TEST FAILED\n\n"
            "OpenFoot could not be reached."
        )


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = " ".join(context.args).strip()

    if not text:

        await update.message.reply_text(
            "Send a match like:\n\n"
            "/analyze Chelsea vs Arsenal"
        )
        return

    await update.message.reply_text(
        "🔎 Analyzing the match...\n"
        "Checking overall form + home/away trends..."
    )

    match = re.split(
        r"\s+(?:vs?|v)\s+|\s+-\s+",
        text,
        flags=re.IGNORECASE
    )

    if len(match) != 2:

        await update.message.reply_text(
            "❌ Please use this format:\n\n"
            "Chelsea vs Arsenal"
        )
        return

    team1 = match[0].strip()
    team2 = match[1].strip()

    result = analyze_fixture(team1, team2)

    await update.message.reply_text(result)


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text.strip()

    match = re.split(
        r"\s+(?:vs?|v)\s+|\s+-\s+",
        text,
        flags=re.IGNORECASE
    )

    if len(match) != 2:
        await update.message.reply_text(
            "⚽ Send a match like:\n\n"
            "Chelsea vs Arsenal"
        )
        return

    team1 = match[0].strip()
    team2 = match[1].strip()

    await update.message.reply_text(
        "🔎 Analyzing...\n"
        "Checking overall form + home/away trends..."
    )

    result = analyze_fixture(team1, team2)

    await update.message.reply_text(result)


# =========================================================
# MAIN
# =========================================================

def main():

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    if not OPENFOOT_API_KEY:
        raise RuntimeError("OPENFOOT_API_KEY is missing")

    # Start Render health server
    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

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
        CommandHandler("apitest", apitest)
    )

    application.add_handler(
        CommandHandler("analyze", analyze_command)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_message
        )
    )

    print("GoalLogic AI is ready.")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
