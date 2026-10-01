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
# OPENFOOT
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

    if isinstance(data, dict):
        results = (
            data.get("teams")
            or data.get("results")
            or data.get("data")
            or []
        )
    else:
        results = data

    for item in results:

        if not isinstance(item, dict):
            continue

        team = item.get("team")

        if not isinstance(team, dict):
            team = item

        name = str(team.get("name") or "")

        if name.lower() == team_name.lower():
            return team

    for item in results:

        if not isinstance(item, dict):
            continue

        team = item.get("team")

        if not isinstance(team, dict):
            team = item

        if team.get("id") and team.get("name"):
            return team

    return None


# =========================================================
# TEAM MATCHES
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
# MATCH HELPERS
# =========================================================

def get_home_team(match):
    value = match.get("homeTeam")
    return value if isinstance(value, dict) else {}


def get_away_team(match):
    value = match.get("awayTeam")
    return value if isinstance(value, dict) else {}


def get_status(match):
    return str(match.get("status", "")).lower()


def get_score(match):

    score = match.get("score")

    if not isinstance(score, dict):
        return None, None

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

    gf = sum(x["gf"] for x in selected)
    ga = sum(x["ga"] for x in selected)

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

    clean = sum(
        1 for x in selected
        if x["ga"] == 0
    )

    scoring = sum(
        1 for x in selected
        if x["gf"] > 0
    )

    n = len(selected)

    return {
        "form": "".join(x["result"] for x in selected),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "gf": gf,
        "ga": ga,
        "over15": round(over15 / n * 100),
        "over25": round(over25 / n * 100),
        "btts": round(btts / n * 100),
        "clean": round(clean / n * 100),
        "scoring": round(scoring / n * 100),
        "count": n
    }


# =========================================================
# HOME / AWAY ANALYSIS
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

        if not is_finished(match):
            continue

        venue_matches.append(match)

    return analyze_matches(
        venue_matches,
        team_id,
        limit
    )


# =========================================================
# FORMAT STATS
# =========================================================

def format_stats(stats, title):

    if not stats:
        return f"""
📍 {title}

No recent matches available.
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
Sample: {stats["count"]} matches
"""


# =========================================================
# CONFIDENCE ENGINE
# =========================================================

def calculate_weighted_confidence(
    overall1,
    overall2,
    venue1,
    venue2,
    market
):

    values = []

    if market == "over15":

        if overall1:
            values.append(overall1["over15"])

        if overall2:
            values.append(overall2["over15"])

        if venue1:
            values.append(venue1["over15"])

        if venue2:
            values.append(venue2["over15"])

    elif market == "over25":

        if overall1:
            values.append(overall1["over25"])

        if overall2:
            values.append(overall2["over25"])

        if venue1:
            values.append(venue1["over25"])

        if venue2:
            values.append(venue2["over25"])

    elif market == "btts":

        if overall1:
            values.append(overall1["btts"])

        if overall2:
            values.append(overall2["btts"])

        if venue1:
            values.append(venue1["btts"])

        if venue2:
            values.append(venue2["btts"])

    if len(values) < 2:
        return None

    # Overall data receives slightly more importance
    overall_values = []

    if market == "over15":

        overall_values = [
            overall1["over15"] if overall1 else None,
            overall2["over15"] if overall2 else None
        ]

    elif market == "over25":

        overall_values = [
            overall1["over25"] if overall1 else None,
            overall2["over25"] if overall2 else None
        ]

    elif market == "btts":

        overall_values = [
            overall1["btts"] if overall1 else None,
            overall2["btts"] if overall2 else None
        ]

    overall_values = [
        x for x in overall_values
        if x is not None
    ]

    venue_values = []

    if market == "over15":

        venue_values = [
            venue1["over15"] if venue1 else None,
            venue2["over15"] if venue2 else None
        ]

    elif market == "over25":

        venue_values = [
            venue1["over25"] if venue1 else None,
            venue2["over25"] if venue2 else None
        ]

    elif market == "btts":

        venue_values = [
            venue1["btts"] if venue1 else None,
            venue2["btts"] if venue2 else None
        ]

    venue_values = [
        x for x in venue_values
        if x is not None
    ]

    overall_avg = (
        sum(overall_values) / len(overall_values)
        if overall_values else 0
    )

    venue_avg = (
        sum(venue_values) / len(venue_values)
        if venue_values else overall_avg
    )

    # 40% overall + 40% venue
    weighted = (
        overall_avg * 0.40 +
        venue_avg * 0.40
    )

    # Sample reliability
    venue_samples = 0

    if venue1:
        venue_samples += venue1["count"]

    if venue2:
        venue_samples += venue2["count"]

    if venue_samples >= 8:
        reliability = 20

    elif venue_samples >= 6:
        reliability = 15

    elif venue_samples >= 4:
        reliability = 10

    elif venue_samples >= 2:
        reliability = 5

    else:
        reliability = 0

    confidence = round(weighted + reliability)

    # Never allow tiny samples to produce exaggerated confidence.
    if venue_samples <= 2:
        confidence = min(confidence, 78)

    elif venue_samples <= 4:
        confidence = min(confidence, 82)

    elif venue_samples <= 6:
        confidence = min(confidence, 85)

    else:
        confidence = min(confidence, 88)

    return confidence


# =========================================================
# MARKET GRADE
# =========================================================

def grade_market(confidence, venue_samples):

    if confidence >= 80 and venue_samples >= 4:
        return "🔥 STRONG"

    if confidence >= 70:
        return "🟢 GOOD"

    if confidence >= 60:
        return "🟡 MODERATE"

    return "🔴 AVOID"


# =========================================================
# MARKET ENGINE
# =========================================================

def calculate_markets(
    team1_overall,
    team2_overall,
    team1_home,
    team2_away
):

    markets = []

    venue_samples = 0

    if team1_home:
        venue_samples += team1_home["count"]

    if team2_away:
        venue_samples += team2_away["count"]

    # -----------------------------------------------------
    # OVER 1.5
    # -----------------------------------------------------

    confidence = calculate_weighted_confidence(
        team1_overall,
        team2_overall,
        team1_home,
        team2_away,
        "over15"
    )

    if confidence is not None:

        if confidence >= 70:
            advice = "BET"

        elif confidence >= 60:
            advice = "CAUTION"

        else:
            advice = "AVOID"

        markets.append({
            "market": "Over 1.5 Goals",
            "confidence": confidence,
            "grade": grade_market(confidence, venue_samples),
            "advice": advice,
            "reason": "Overall form and relevant home/away goal trends were combined with a sample-size adjustment."
        })

    # -----------------------------------------------------
    # OVER 2.5
    # -----------------------------------------------------

    confidence = calculate_weighted_confidence(
        team1_overall,
        team2_overall,
        team1_home,
        team2_away,
        "over25"
    )

    if confidence is not None:

        if confidence >= 70:
            advice = "BET"

        elif confidence >= 60:
            advice = "CAUTION"

        else:
            advice = "AVOID"

        markets.append({
            "market": "Over 2.5 Goals",
            "confidence": confidence,
            "grade": grade_market(confidence, venue_samples),
            "advice": advice,
            "reason": "Overall and venue-specific Over 2.5 trends were weighted together rather than simply averaged."
        })

    # -----------------------------------------------------
    # BTTS
    # -----------------------------------------------------

    confidence = calculate_weighted_confidence(
        team1_overall,
        team2_overall,
        team1_home,
        team2_away,
        "btts"
    )

    if confidence is not None:

        if confidence >= 70:
            advice = "BET"

        elif confidence >= 60:
            advice = "CAUTION"

        else:
            advice = "AVOID"

        markets.append({
            "market": "BTTS — Yes",
            "confidence": confidence,
            "grade": grade_market(confidence, venue_samples),
            "advice": advice,
            "reason": "Recent scoring and conceding patterns were combined with home/away performance."
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

    team1_id = team1.get("id")
    team2_id = team2.get("id")

    if not team1_id or not team2_id:
        return "⚠️ Team IDs could not be retrieved."

    team1_matches = get_team_matches(team1_id)
    team2_matches = get_team_matches(team2_id)

    if not team1_matches:
        return f"⚠️ Football data could not be retrieved for {team1_name}."

    if not team2_matches:
        return f"⚠️ Football data could not be retrieved for {team2_name}."

    # Overall
    team1_overall = analyze_matches(
        team1_matches,
        team1_id
    )

    team2_overall = analyze_matches(
        team2_matches,
        team2_id
    )

    # Relevant venue
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
        return "⚠️ Not enough completed matches were found."

    markets = calculate_markets(
        team1_overall,
        team2_overall,
        team1_home,
        team2_away
    )

    # -----------------------------------------------------
    # FORM
    # -----------------------------------------------------

    team1_points = (
        team1_overall["wins"] * 3
        + team1_overall["draws"]
    )

    team2_points = (
        team2_overall["wins"] * 3
        + team2_overall["draws"]
    )

    if team1_points > team2_points:

        form_assessment = (
            f"{team1_name} has the stronger recent form."
        )

    elif team2_points > team1_points:

        form_assessment = (
            f"{team2_name} has the stronger recent form."
        )

    else:

        form_assessment = (
            "Both teams have similar recent form."
        )

    # -----------------------------------------------------
    # RESPONSE
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
  Grade: {market["grade"]}
  Advice: {market["advice"]}
  Reason: {market["reason"]}
"""

        # Highest confidence only
        primary = max(
            markets,
            key=lambda x: x["confidence"]
        )

        response += f"""
━━━━━━━━━━━━━━━━━━
⭐ PRIMARY STATISTICAL SIGNAL
━━━━━━━━━━━━━━━━━━

{primary["market"]}

Confidence: {primary["confidence"]}%
Grade: {primary["grade"]}
Advice: {primary["advice"]}

This is the strongest statistical signal from the available data, not a guaranteed outcome.
"""

    else:

        response += """
No sufficiently strong statistical signal was found.

Advice: AVOID
"""

    response += """
━━━━━━━━━━━━━━━━━━
⚠️ RISK WARNING
━━━━━━━━━━━━━━━━━━

Confidence is based on recent statistical data and sample size.

It is not a guarantee of the match result.

Lineups, injuries, tactics, schedule changes and late team news can change the match.
"""

    return response


# =========================================================
# TELEGRAM
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "⚽ Welcome to GoalLogic AI!\n\n"
        "Send a match like:\n"
        "Chelsea vs Arsenal\n\n"
        "Or:\n"
        "/analyze Chelsea vs Arsenal\n\n"
        "Use /apitest to test OpenFoot."
    )


async def apitest(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not OPENFOOT_API_KEY:

        await update.message.reply_text(
            "❌ OPENFOOT_API_KEY is missing."
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
            "❌ OPENFOOT TEST FAILED."
        )


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = " ".join(context.args).strip()

    if not text:

        await update.message.reply_text(
            "Send:\n/analyze Chelsea vs Arsenal"
        )
        return

    match = re.split(
        r"\s+(?:vs?|v)\s+|\s+-\s+",
        text,
        flags=re.IGNORECASE
    )

    if len(match) != 2:

        await update.message.reply_text(
            "❌ Use:\n\nChelsea vs Arsenal"
        )
        return

    await update.message.reply_text(
        "🔎 Analyzing...\n"
        "Checking overall + home/away form..."
    )

    result = analyze_fixture(
        match[0].strip(),
        match[1].strip()
    )

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

    await update.message.reply_text(
        "🔎 Analyzing...\n"
        "Checking overall + home/away form..."
    )

    result = analyze_fixture(
        match[0].strip(),
        match[1].strip()
    )

    await update.message.reply_text(result)


# =========================================================
# START
# =========================================================

def main():

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing"
        )

    if not OPENFOOT_API_KEY:
        raise RuntimeError(
            "OPENFOOT_API_KEY is missing"
        )

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
