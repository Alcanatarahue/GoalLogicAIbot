import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================================================
# CONFIGURATION
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
        body = b"GoalLogic AI is running."

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header(
            "Content-Length",
            str(len(body))
        )
        self.end_headers()

        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()

    def log_message(self, format, *args):
        return


def start_health_server():

    try:
        server = ThreadingHTTPServer(
            ("0.0.0.0", PORT),
            HealthHandler
        )

        print(
            f"✅ Health server listening on "
            f"0.0.0.0:{PORT}",
            flush=True
        )

        server.serve_forever()

    except Exception as error:

        print(
            f"❌ Health server error: {error}",
            flush=True
        )


# =========================================================
# OPENFOOT API
# =========================================================

def openfoot_get(endpoint, params=None):

    if not OPENFOOT_API_KEY:
        print(
            "❌ OPENFOOT_API_KEY is missing",
            flush=True
        )
        return None

    headers = {
        "Accept": "application/json",
        "Authorization": (
            f"Bearer {OPENFOOT_API_KEY}"
        ),
    }

    try:

        response = requests.get(
            OPENFOOT_BASE + endpoint,
            headers=headers,
            params=params,
            timeout=20,
        )

        print(
            f"OpenFoot {endpoint}: "
            f"HTTP {response.status_code}",
            flush=True
        )

        if response.status_code != 200:

            print(
                response.text[:1000],
                flush=True
            )

            return None

        result = response.json()

        return result.get("data")

    except Exception as error:

        print(
            f"❌ OpenFoot request error: {error}",
            flush=True
        )

        return None


# =========================================================
# OPENFOOT TEST
# =========================================================

def test_openfoot():

    if not OPENFOOT_API_KEY:
        return False

    try:

        headers = {
            "Accept": "application/json",
            "Authorization": (
                f"Bearer {OPENFOOT_API_KEY}"
            ),
        }

        response = requests.get(
            OPENFOOT_BASE + "/v1/health",
            headers=headers,
            timeout=15,
        )

        return response.status_code == 200

    except Exception as error:

        print(
            f"OpenFoot health error: {error}",
            flush=True
        )

        return False


# =========================================================
# TEAM SEARCH
# =========================================================

def search_team(team_name):

    data = openfoot_get(
        "/v1/search",
        {"q": team_name}
    )

    if not data:
        return None

    if isinstance(data, list):

        results = data

    elif isinstance(data, dict):

        results = (
            data.get("teams")
            or data.get("results")
            or data.get("data")
            or []
        )

    else:

        results = []

    # Exact match
    for item in results:

        if not isinstance(item, dict):
            continue

        team = item.get("team", item)

        if not isinstance(team, dict):
            continue

        name = str(
            team.get("name") or ""
        ).strip()

        if name.lower() == team_name.lower():

            return team

    # Partial match
    for item in results:

        if not isinstance(item, dict):
            continue

        team = item.get("team", item)

        if not isinstance(team, dict):
            continue

        name = str(
            team.get("name") or ""
        ).strip()

        if (
            team_name.lower() in name.lower()
            or name.lower() in team_name.lower()
        ):

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
            "season": CURRENT_SEASON,
        },
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

    home = match.get("homeTeam")

    if isinstance(home, dict):
        return home

    return {}


def get_away_team(match):

    away = match.get("awayTeam")

    if isinstance(away, dict):
        return away

    return {}


def get_score(match):

    score = match.get("score")

    if not isinstance(score, dict):
        return None, None

    home_score = score.get("home")
    away_score = score.get("away")

    if isinstance(home_score, dict):

        home_score = (
            home_score.get("goals")
            or home_score.get("current")
            or home_score.get("score")
        )

    if isinstance(away_score, dict):

        away_score = (
            away_score.get("goals")
            or away_score.get("current")
            or away_score.get("score")
        )

    try:

        return int(home_score), int(away_score)

    except (TypeError, ValueError):

        return None, None


def get_status(match):

    return str(
        match.get("status") or ""
    ).lower()


def is_finished(match):

    status = get_status(match)

    finished = [
        "finished",
        "ft",
        "fulltime",
        "completed",
        "complete",
    ]

    return any(
        word in status
        for word in finished
    )


# =========================================================
# BASIC MATCH ANALYSIS
# =========================================================

def analyze_matches(
    matches,
    team_id,
    limit=5
):

    completed = []

    for match in matches:

        if not is_finished(match):
            continue

        home = get_home_team(match)
        away = get_away_team(match)

        home_id = home.get("id")
        away_id = away.get("id")

        home_score, away_score = get_score(match)

        if home_score is None:
            continue

        if away_score is None:
            continue

        if team_id == home_id:

            gf = home_score
            ga = away_score
            result = (
                "W"
                if gf > ga
                else "L"
                if gf < ga
                else "D"
            )

        elif team_id == away_id:

            gf = away_score
            ga = home_score
            result = (
                "W"
                if gf > ga
                else "L"
                if gf < ga
                else "D"
            )

        else:

            continue

        completed.append(
            {
                "match": match,
                "gf": gf,
                "ga": ga,
                "result": result,
            }
        )

    # Newest first
    completed.sort(
        key=lambda item: str(
            item["match"].get(
                "kickoffAt",
                item["match"].get(
                    "date",
                    ""
                )
            )
        ),
        reverse=True,
    )

    selected = completed[:limit]

    if not selected:
        return None

    n = len(selected)

    wins = sum(
        1
        for x in selected
        if x["result"] == "W"
    )

    draws = sum(
        1
        for x in selected
        if x["result"] == "D"
    )

    losses = sum(
        1
        for x in selected
        if x["result"] == "L"
    )

    gf = sum(
        x["gf"]
        for x in selected
    )

    ga = sum(
        x["ga"]
        for x in selected
    )

    over15 = sum(
        1
        for x in selected
        if x["gf"] + x["ga"] >= 2
    )

    over25 = sum(
        1
        for x in selected
        if x["gf"] + x["ga"] >= 3
    )

    btts = sum(
        1
        for x in selected
        if x["gf"] > 0
        and x["ga"] > 0
    )

    clean = sum(
        1
        for x in selected
        if x["ga"] == 0
    )

    scored = sum(
        1
        for x in selected
        if x["gf"] > 0
    )

    conceded = sum(
        1
        for x in selected
        if x["ga"] > 0
    )

    return {
        "form": "".join(
            x["result"]
            for x in selected
        ),

        "wins": wins,
        "draws": draws,
        "losses": losses,

        "gf": gf,
        "ga": ga,

        "avg_gf": round(
            gf / n,
            2
        ),

        "avg_ga": round(
            ga / n,
            2
        ),

        "avg_total": round(
            (gf + ga) / n,
            2
        ),

        "over15": round(
            over15 / n * 100
        ),

        "over25": round(
            over25 / n * 100
        ),

        "btts": round(
            btts / n * 100
        ),

        "clean": round(
            clean / n * 100
        ),

        "scoring": round(
            scored / n * 100
        ),

        "conceding": round(
            conceded / n * 100
        ),

        "count": n,
    }


# =========================================================
# HOME / AWAY ANALYSIS
# =========================================================

def analyze_venue(
    matches,
    team_id,
    venue
):

    venue_matches = []

    for match in matches:

        home = get_home_team(match)
        away = get_away_team(match)

        if venue == "home":

            if home.get("id") != team_id:
                continue

        if venue == "away":

            if away.get("id") != team_id:
                continue

        venue_matches.append(match)

    return analyze_matches(
        venue_matches,
        team_id,
        limit=5
    )


# =========================================================
# FORMAT TEAM STATS
# =========================================================

def format_stats(
    stats,
    label
):

    if not stats:

        return (
            f"{label}\n"
            "No data available."
        )

    warning = ""

    if stats["count"] < 3:

        warning = (
            "\n⚠️ Very small sample."
        )

    elif stats["count"] < 5:

        warning = (
            "\n⚠️ Limited sample."
        )

    return f"""
{label}

Form: {stats["form"]}
W/D/L: {stats["wins"]}/{stats["draws"]}/{stats["losses"]}

⚽ Goals scored: {stats["gf"]}
🛡️ Goals conceded: {stats["ga"]}

📊 Avg scored: {stats["avg_gf"]}
📊 Avg conceded: {stats["avg_ga"]}
🎯 Avg total goals: {stats["avg_total"]}

Over 1.5: {stats["over15"]}%
Over 2.5: {stats["over25"]}%
BTTS: {stats["btts"]}%

Scoring consistency: {stats["scoring"]}%
Clean sheets: {stats["clean"]}%

Sample: {stats["count"]} matches{warning}
"""


# =========================================================
# GOAL INTELLIGENCE
# =========================================================

def goal_intelligence(
    team1,
    team2,
    team1_home,
    team2_away
):

    attack_values = [
        team1["avg_gf"],
        team2["avg_gf"],
    ]

    defence_values = [
        team1["avg_ga"],
        team2["avg_ga"],
    ]

    if team1_home:

        attack_values.append(
            team1_home["avg_gf"]
        )

        defence_values.append(
            team1_home["avg_ga"]
        )

    if team2_away:

        attack_values.append(
            team2_away["avg_gf"]
        )

        defence_values.append(
            team2_away["avg_ga"]
        )

    attack = sum(
        attack_values
    ) / len(attack_values)

    defence = sum(
        defence_values
    ) / len(defence_values)

    environment = attack + defence

    if environment >= 3.0:

        level = "🔥 HIGH"

    elif environment >= 2.5:

        level = "🟢 GOOD"

    elif environment >= 2.0:

        level = "🟡 MODERATE"

    else:

        level = "🔴 LOW"

    return {
        "attack": round(
            attack,
            2
        ),

        "defence": round(
            defence,
            2
        ),

        "environment": round(
            environment,
            2
        ),

        "level": level,
    }


# =========================================================
# CONFIDENCE ENGINE
# =========================================================

def market_confidence(
    team1,
    team2,
    team1_venue,
    team2_venue,
    market
):

    if market == "over15":
        key = "over15"

    elif market == "over25":
        key = "over25"

    elif market == "btts":
        key = "btts"

    else:
        return 0

    overall = (
        team1[key] + team2[key]
    ) / 2

    venue_values = []

    if team1_venue:
        venue_values.append(
            team1_venue[key]
        )

    if team2_venue:
        venue_values.append(
            team2_venue[key]
        )

    if venue_values:

        venue = (
            sum(venue_values)
            / len(venue_values)
        )

    else:

        venue = overall

    # Overall form = 50%
    # Venue data = 30%
    confidence = (
        overall * 0.50
        + venue * 0.30
    )

    venue_sample = sum(
        [
            team1_venue["count"]
            if team1_venue
            else 0,

            team2_venue["count"]
            if team2_venue
            else 0,
        ]
    )

    # Reliability = 20%
    if venue_sample >= 8:

        confidence += 20

    elif venue_sample >= 6:

        confidence += 15

    elif venue_sample >= 4:

        confidence += 10

    elif venue_sample >= 2:

        confidence += 5

    confidence = round(
        confidence
    )

    # Conservative maximums
    if venue_sample < 3:

        confidence = min(
            confidence,
            75
        )

    elif venue_sample < 5:

        confidence = min(
            confidence,
            82
        )

    elif venue_sample < 7:

        confidence = min(
            confidence,
            86
        )

    else:

        confidence = min(
            confidence,
            90
        )

    return confidence


def market_grade(
    confidence
):

    if confidence >= 80:
        return "🔥 STRONG"

    if confidence >= 70:
        return "🟢 GOOD"

    if confidence >= 60:
        return "🟡 MODERATE"

    return "🔴 AVOID"


# =========================================================
# MARKET ANALYSIS
# =========================================================

def build_markets(
    team1,
    team2,
    team1_home,
    team2_away,
    goals
):

    markets = []

    # -------------------------
    # OVER 1.5
    # -------------------------

    confidence = market_confidence(
        team1,
        team2,
        team1_home,
        team2_away,
        "over15"
    )

    if goals["environment"] >= 2.5:

        confidence = min(
            confidence + 3,
            90
        )

    if confidence >= 70:

        advice = "BET"

    elif confidence >= 60:

        advice = "CAUTION"

    else:

        advice = "AVOID"

    markets.append(
        {
            "market":
                "Over 1.5 Goals",

            "confidence":
                confidence,

            "grade":
                market_grade(
                    confidence
                ),

            "advice":
                advice,

            "reason":
                (
                    "Recent goal frequency, "
                    "attacking averages and "
                    "home/away data were combined."
                ),
        }
    )

    # -------------------------
    # OVER 2.5
    # -------------------------

    confidence = market_confidence(
        team1,
        team2,
        team1_home,
        team2_away,
        "over25"
    )

    if goals["environment"] >= 3.0:

        confidence = min(
            confidence + 5,
            90
        )

    elif goals["environment"] < 2.2:

        confidence = max(
            confidence - 5,
            0
        )

    if confidence >= 70:

        advice = "BET"

    elif confidence >= 60:

        advice = "CAUTION"

    else:

        advice = "AVOID"

    markets.append(
        {
            "market":
                "Over 2.5 Goals",

            "confidence":
                confidence,

            "grade":
                market_grade(
                    confidence
                ),

            "advice":
                advice,

            "reason":
                (
                    "Over 2.5 frequency was combined "
                    "with attacking output and "
                    "goals conceded."
                ),
        }
    )

    # -------------------------
    # BTTS
    # -------------------------

    confidence = market_confidence(
        team1,
        team2,
        team1_home,
        team2_away,
        "btts"
    )

    if confidence >= 70:

        advice = "BET"

    elif confidence >= 60:

        advice = "CAUTION"

    else:

        advice = "AVOID"

    markets.append(
        {
            "market":
                "BTTS — Yes",

            "confidence":
                confidence,

            "grade":
                market_grade(
                    confidence
                ),

            "advice":
                advice,

            "reason":
                (
                    "Scoring consistency and "
                    "defensive concession trends "
                    "were combined."
                ),
        }
    )

    return markets


# =========================================================
# COMPLETE FIXTURE ANALYSIS
# =========================================================

def analyze_fixture(
    team1_name,
    team2_name
):

    print(
        f"Analyzing {team1_name} "
        f"vs {team2_name}",
        flush=True
    )

    team1 = search_team(
        team1_name
    )

    team2 = search_team(
        team2_name
    )

    if not team1:

        return (
            f"❌ I couldn't find "
            f"{team1_name} in OpenFoot."
        )

    if not team2:

        return (
            f"❌ I couldn't find "
            f"{team2_name} in OpenFoot."
        )

    team1_id = team1.get("id")
    team2_id = team2.get("id")

    if not team1_id or not team2_id:

        return (
            "❌ Team information is incomplete."
        )

    team1_matches = get_team_matches(
        team1_id
    )

    team2_matches = get_team_matches(
        team2_id
    )

    if not team1_matches:

        return (
            f"⚠️ No recent data found for "
            f"{team1_name}."
        )

    if not team2_matches:

        return (
            f"⚠️ No recent data found for "
            f"{team2_name}."
        )

    team1_stats = analyze_matches(
        team1_matches,
        team1_id
    )

    team2_stats = analyze_matches(
        team2_matches,
        team2_id
    )

    team1_home = analyze_venue(
        team1_matches,
        team1_id,
        "home"
    )

    team2_away = analyze_venue(
        team2_matches,
        team2_id,
        "away"
    )

    if not team1_stats or not team2_stats:

        return (
            "⚠️ Not enough completed "
            "matches for analysis."
        )

    goals = goal_intelligence(
        team1_stats,
        team2_stats,
        team1_home,
        team2_away
    )

    markets = build_markets(
        team1_stats,
        team2_stats,
        team1_home,
        team2_away,
        goals
    )

    team1_points = (
        team1_stats["wins"] * 3
        + team1_stats["draws"]
    )

    team2_points = (
        team2_stats["wins"] * 3
        + team2_stats["draws"]
    )

    if team1_points > team2_points:

        form_text = (
            f"{team1_name} has the stronger "
            "recent form."
        )

    elif team2_points > team1_points:

        form_text = (
            f"{team2_name} has the stronger "
            "recent form."
        )

    else:

        form_text = (
            "The teams have similar "
            "recent form."
        )

    # Highest statistical signal
    primary = max(
        markets,
        key=lambda item: item["confidence"]
    )

    response = f"""
⚽ GOALLOGIC AI — ADVANCED ANALYSIS

{team1_name} vs {team2_name}
Season: {CURRENT_SEASON}

━━━━━━━━━━━━━━━━━━
📊 {team1_name.upper()} — LAST 5
━━━━━━━━━━━━━━━━━━
{format_stats(
    team1_stats,
    "Overall"
)}

━━━━━━━━━━━━━━━━━━
🏠 {team1_name.upper()} — RECENT HOME
━━━━━━━━━━━━━━━━━━
{format_stats(
    team1_home,
    "Home matches"
)}

━━━━━━━━━━━━━━━━━━
📊 {team2_name.upper()} — LAST 5
━━━━━━━━━━━━━━━━━━
{format_stats(
    team2_stats,
    "Overall"
)}

━━━━━━━━━━━━━━━━━━
✈️ {team2_name.upper()} — RECENT AWAY
━━━━━━━━━━━━━━━━━━
{format_stats(
    team2_away,
    "Away matches"
)}

━━━━━━━━━━━━━━━━━━
⚽ GOAL & DEFENSIVE INTELLIGENCE
━━━━━━━━━━━━━━━━━━

Average attacking output:
{goals["attack"]} goals

Average goals conceded:
{goals["defence"]} goals

Combined goal environment:
{goals["environment"]}

Goal environment:
{goals["level"]}

━━━━━━━━━━━━━━━━━━
📈 FORM ASSESSMENT
━━━━━━━━━━━━━━━━━━

{form_text}

━━━━━━━━━━━━━━━━━━
🎯 MARKET SIGNALS
━━━━━━━━━━━━━━━━━━
"""

    for market in markets:

        response += f"""
• {market["market"]}

Confidence: {market["confidence"]}%
Grade: {market["grade"]}
Advice: {market["advice"]}

Reason:
{market["reason"]}

"""

    response += f"""
━━━━━━━━━━━━━━━━━━
⭐ PRIMARY STATISTICAL SIGNAL
━━━━━━━━━━━━━━━━━━

{primary["market"]}

Confidence: {primary["confidence"]}%
Grade: {primary["grade"]}
Advice: {primary["advice"]}

This is the strongest statistical signal from the available data.

━━━━━━━━━━━━━━━━━━
⚠️ RISK WARNING
━━━━━━━━━━━━━━━━━━

The confidence score is based on recent statistical data and sample size.

It is not a guarantee of the match result.

Lineups, injuries, tactics, schedule changes and late team news can change the analysis.
"""

    return response


# =========================================================
# TELEGRAM COMMANDS
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "⚽ Welcome to GoalLogic AI!\n\n"
        "Send a match like:\n\n"
        "Chelsea vs Arsenal\n\n"
        "Or use:\n"
        "/analyze Chelsea vs Arsenal\n\n"
        "Use /apitest to test OpenFoot."
    )


async def apitest_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if test_openfoot():

        await update.message.reply_text(
            "✅ OPENFOOT TEST PASSED\n\n"
            "OpenFoot API is connected successfully."
        )

    else:

        await update.message.reply_text(
            "❌ OPENFOOT TEST FAILED\n\n"
            "The API connection could not be verified."
        )


def split_match(text):

    parts = re.split(
        r"\s+(?:vs?|v)\s+|\s+-\s+",
        text.strip(),
        flags=re.IGNORECASE
    )

    if len(parts) != 2:
        return None

    return (
        parts[0].strip(),
        parts[1].strip()
    )


async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = " ".join(
        context.args
    ).strip()

    match = split_match(text)

    if not match:

        await update.message.reply_text(
            "❌ Use this format:\n\n"
            "/analyze Chelsea vs Arsenal"
        )

        return

    await update.message.reply_text(
        "🔎 Analyzing...\n\n"
        "Checking recent form, goals, "
        "defence and home/away trends..."
    )

    result = analyze_fixture(
        match[0],
        match[1]
    )

    await update.message.reply_text(
        result
    )


async def normal_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = (
        update.message.text
        or ""
    ).strip()

    match = split_match(text)

    if not match:

        await update.message.reply_text(
            "⚽ Send a match like:\n\n"
            "Chelsea vs Arsenal"
        )

        return

    await update.message.reply_text(
        "🔎 Analyzing...\n\n"
        "Checking recent form, goals, "
        "defence and home/away trends..."
    )

    result = analyze_fixture(
        match[0],
        match[1]
    )

    await update.message.reply_text(
        result
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print(
        "🚀 Starting GoalLogic AI...",
        flush=True
    )

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing"
        )

    if not OPENFOOT_API_KEY:

        raise RuntimeError(
            "OPENFOOT_API_KEY is missing"
        )

    # IMPORTANT:
    # Start Render's HTTP server BEFORE Telegram.
    health_thread = threading.Thread(
        target=start_health_server,
        daemon=True
    )

    health_thread.start()

    # Give the server a moment to bind.
    import time
    time.sleep(1)

    print(
        "✅ Render health server started.",
        flush=True
    )

    print(
        "🤖 Starting Telegram bot...",
        flush=True
    )

    application = (
        Application.builder()
        .token(
            TELEGRAM_BOT_TOKEN
        )
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "apitest",
            apitest_command
        )
    )

    application.add_handler(
        CommandHandler(
            "analyze",
            analyze_command
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            normal_message
        )
    )

    print(
        "✅ GoalLogic AI is ready.",
        flush=True
    )

    application.run_polling(
        drop_pending_updates=True
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
