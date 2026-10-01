import os
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
# GOALLOGIC AI
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

PORT = int(os.getenv("PORT", "10000"))
OPENFOOT_BASE = "https://openfootapi.com"
CURRENT_SEASON = "2026/27"

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

if not OPENFOOT_API_KEY:
    raise RuntimeError("OPENFOOT_API_KEY is missing")


# ============================================================
# RENDER HEALTH SERVER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GoalLogic AI is running.")

    def log_message(self, format, *args):
        pass


def start_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


# ============================================================
# OPENFOOT API
# ============================================================

async def openfoot_get(endpoint, params=None):

    url = f"{OPENFOOT_BASE}{endpoint}"

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {OPENFOOT_API_KEY}",
    }

    try:

        async with httpx.AsyncClient(timeout=20.0) as client:

            response = await client.get(
                url,
                headers=headers,
                params=params or {},
            )

            try:
                data = response.json()
            except Exception:
                return None

            if response.status_code != 200:

                print(
                    "OPENFOOT ERROR:",
                    response.status_code,
                    data
                )

                return {
                    "_error": True,
                    "status": response.status_code,
                    "body": data,
                }

            return data

    except Exception as e:

        print("OPENFOOT CONNECTION ERROR:", repr(e))

        return {
            "_error": True,
            "status": 0,
            "body": {"message": str(e)},
        }


# ============================================================
# TEAM SEARCH
# ============================================================

async def search_team(team_name):

    result = await openfoot_get(
        "/v1/search",
        {"q": team_name}
    )

    if not result or result.get("_error"):
        return None

    data = result.get("data", [])

    if isinstance(data, dict):

        data = (
            data.get("teams")
            or data.get("results")
            or []
        )

    if not isinstance(data, list):
        return None

    wanted = team_name.lower().strip()

    # Exact match
    for item in data:

        if not isinstance(item, dict):
            continue

        name = str(
            item.get("name")
            or item.get("team", {}).get("name", "")
        )

        if name.lower().strip() == wanted:
            return item

    # Partial match
    for item in data:

        if not isinstance(item, dict):
            continue

        name = str(
            item.get("name")
            or item.get("team", {}).get("name", "")
        )

        if wanted in name.lower():
            return item

    # First result
    for item in data:

        if isinstance(item, dict):
            return item

    return None


def get_team_id(team):

    if not team:
        return None

    if team.get("id"):
        return team["id"]

    nested = team.get("team")

    if isinstance(nested, dict):
        return nested.get("id")

    return None


def get_team_name(team, fallback):

    if not team:
        return fallback

    if team.get("name"):
        return str(team["name"])

    nested = team.get("team")

    if isinstance(nested, dict):

        if nested.get("name"):
            return str(nested["name"])

    return fallback


# ============================================================
# SCORE EXTRACTION
# ============================================================

def to_number(value):

    try:

        if value is None:
            return None

        return int(value)

    except Exception:

        return None


def extract_score(match):

    home_score = None
    away_score = None

    score = match.get("score")

    if isinstance(score, dict):

        fulltime = (
            score.get("fullTime")
            or score.get("fulltime")
        )

        if isinstance(fulltime, dict):

            home_score = to_number(
                fulltime.get("home")
            )

            away_score = to_number(
                fulltime.get("away")
            )

        if home_score is None:
            home_score = to_number(
                score.get("home")
            )

        if away_score is None:
            away_score = to_number(
                score.get("away")
            )

    if home_score is None:
        home_score = to_number(
            match.get("homeScore")
        )

    if away_score is None:
        away_score = to_number(
            match.get("awayScore")
        )

    return home_score, away_score


def extract_team_ids(match):

    home = (
        match.get("homeTeam")
        or match.get("home")
        or {}
    )

    away = (
        match.get("awayTeam")
        or match.get("away")
        or {}
    )

    if not isinstance(home, dict):
        home = {}

    if not isinstance(away, dict):
        away = {}

    return (
        home.get("id"),
        away.get("id"),
    )


def extract_date(match):

    return (
        match.get("kickoffAt")
        or match.get("kickoff")
        or match.get("date")
        or ""
    )


# ============================================================
# TEAM MATCHES
# ============================================================

async def get_team_matches(team_id):

    result = await openfoot_get(
        "/v1/matches",
        {
            "team": team_id,
            "season": CURRENT_SEASON,
        }
    )

    if not result or result.get("_error"):
        return []

    data = result.get("data", [])

    if isinstance(data, dict):

        data = (
            data.get("matches")
            or data.get("results")
            or []
        )

    if not isinstance(data, list):
        return []

    matches = []

    for match in data:

        if not isinstance(match, dict):
            continue

        status = str(
            match.get("status", "")
        ).lower()

        if status not in [
            "finished",
            "complete",
            "completed",
            "ft",
        ]:
            continue

        home_score, away_score = extract_score(match)

        if home_score is None or away_score is None:
            continue

        home_id, away_id = extract_team_ids(match)

        matches.append({
            "match": match,
            "home_id": home_id,
            "away_id": away_id,
            "home_score": home_score,
            "away_score": away_score,
            "date": extract_date(match),
        })

    matches.sort(
        key=lambda x: str(x["date"]),
        reverse=True
    )

    return matches


# ============================================================
# TEAM STATISTICS
# ============================================================

def calculate_stats(matches, team_id):

    recent = matches[:5]

    stats = {
        "played": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "goals_for": 0,
        "goals_against": 0,
        "over15": 0,
        "over25": 0,
        "btts": 0,
        "clean_sheets": 0,
        "scored": 0,
        "points": 0,
        "form": [],
    }

    for item in recent:

        hs = item["home_score"]
        aws = item["away_score"]

        is_home = item["home_id"] == team_id

        if is_home:

            gf = hs
            ga = aws

        else:

            gf = aws
            ga = hs

        stats["played"] += 1
        stats["goals_for"] += gf
        stats["goals_against"] += ga

        total = hs + aws

        if total >= 2:
            stats["over15"] += 1

        if total >= 3:
            stats["over25"] += 1

        if hs > 0 and aws > 0:
            stats["btts"] += 1

        if ga == 0:
            stats["clean_sheets"] += 1

        if gf > 0:
            stats["scored"] += 1

        if gf > ga:

            stats["wins"] += 1
            stats["points"] += 3
            stats["form"].append("W")

        elif gf == ga:

            stats["draws"] += 1
            stats["points"] += 1
            stats["form"].append("D")

        else:

            stats["losses"] += 1
            stats["form"].append("L")

    played = max(stats["played"], 1)

    stats["over15_pct"] = round(
        stats["over15"] / played * 100
    )

    stats["over25_pct"] = round(
        stats["over25"] / played * 100
    )

    stats["btts_pct"] = round(
        stats["btts"] / played * 100
    )

    stats["clean_pct"] = round(
        stats["clean_sheets"] / played * 100
    )

    stats["scored_pct"] = round(
        stats["scored"] / played * 100
    )

    stats["avg_for"] = round(
        stats["goals_for"] / played,
        2
    )

    stats["avg_against"] = round(
        stats["goals_against"] / played,
        2
    )

    return stats


# ============================================================
# H2H
# ============================================================

async def get_h2h(team1_id, team2_id):

    result = await openfoot_get(
        f"/v1/teams/{team1_id}/h2h",
        {
            "opponent": team2_id
        }
    )

    if not result or result.get("_error"):
        return []

    data = result.get("data", [])

    if isinstance(data, dict):

        data = (
            data.get("matches")
            or data.get("h2h")
            or data.get("results")
            or []
        )

    if not isinstance(data, list):
        return []

    return data[:5]


def calculate_h2h(team1_id, matches):

    if not matches:
        return None

    result = {
        "played": 0,
        "team1": 0,
        "draws": 0,
        "team2": 0,
        "goals": 0,
    }

    for match in matches:

        if not isinstance(match, dict):
            continue

        hs, aws = extract_score(match)

        if hs is None or aws is None:
            continue

        home_id, away_id = extract_team_ids(match)

        result["played"] += 1
        result["goals"] += hs + aws

        if home_id == team1_id:

            if hs > aws:
                result["team1"] += 1

            elif hs == aws:
                result["draws"] += 1

            else:
                result["team2"] += 1

        elif away_id == team1_id:

            if aws > hs:
                result["team1"] += 1

            elif hs == aws:
                result["draws"] += 1

            else:
                result["team2"] += 1

    if result["played"] == 0:
        return None

    result["avg_goals"] = round(
        result["goals"] / result["played"],
        2
    )

    return result


# ============================================================
# MARKET ENGINE
# ============================================================

def get_markets(stats1, stats2):

    markets = []

    over15 = (
        stats1["over15_pct"]
        + stats2["over15_pct"]
    ) / 2

    over25 = (
        stats1["over25_pct"]
        + stats2["over25_pct"]
    ) / 2

    btts = (
        stats1["btts_pct"]
        + stats2["btts_pct"]
    ) / 2

    # Over 1.5
    if (
        stats1["over15_pct"] >= 80
        and stats2["over15_pct"] >= 80
    ):

        confidence = round(
            55 + (over15 - 70) * 0.5
        )

        confidence = min(
            max(confidence, 50),
            90
        )

        markets.append({
            "market": "Over 1.5 Goals",
            "confidence": confidence,
            "advice": "BET",
            "reason": (
                f"Both teams have strong recent Over 1.5 "
                f"rates: {stats1['over15_pct']}% and "
                f"{stats2['over15_pct']}%."
            ),
        })

    # Over 2.5
    if (
        stats1["over25_pct"] >= 60
        and stats2["over25_pct"] >= 60
    ):

        confidence = round(
            50 + (over25 - 50) * 0.6
        )

        confidence = min(
            max(confidence, 50),
            85
        )

        markets.append({
            "market": "Over 2.5 Goals",
            "confidence": confidence,
            "advice": "BET",
            "reason": (
                f"Both teams have recorded Over 2.5 "
                f"in at least 60% of their last five."
            ),
        })

    # BTTS
    if (
        stats1["btts_pct"] >= 60
        and stats2["btts_pct"] >= 60
    ):

        confidence = round(
            50 + (btts - 50) * 0.6
        )

        confidence = min(
            max(confidence, 50),
            85
        )

        markets.append({
            "market": "BTTS — Yes",
            "confidence": confidence,
            "advice": "BET",
            "reason": (
                f"Both teams have a strong recent BTTS "
                f"profile: {stats1['btts_pct']}% and "
                f"{stats2['btts_pct']}%."
            ),
        })

    # No strong market
    if not markets:

        markets.append({
            "market": "No Strong Market",
            "confidence": 45,
            "advice": "AVOID",
            "reason": (
                "The available recent statistics do not "
                "produce a strong enough signal."
            ),
        })

    markets.sort(
        key=lambda x: x["confidence"],
        reverse=True
    )

    return markets


# ============================================================
# MATCH PARSER
# ============================================================

def parse_match(text):

    text = text.strip()

    patterns = [
        r"(.+?)\s+vs\.?\s+(.+)",
        r"(.+?)\s+v\.?\s+(.+)",
        r"(.+?)\s+-\s+(.+)",
    ]

    for pattern in patterns:

        match = re.match(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            team1 = match.group(1).strip()
            team2 = match.group(2).strip()

            if team1 and team2:
                return team1, team2

    return None, None


# ============================================================
# ANALYSIS
# ============================================================

async def analyze_match(team1_query, team2_query):

    team1 = await search_team(team1_query)
    team2 = await search_team(team2_query)

    if not team1:
        return f"❌ I couldn't find {team1_query}."

    if not team2:
        return f"❌ I couldn't find {team2_query}."

    team1_id = get_team_id(team1)
    team2_id = get_team_id(team2)

    if not team1_id or not team2_id:

        return (
            "⚠️ I found the teams but couldn't retrieve "
            "their OpenFoot IDs."
        )

    name1 = get_team_name(
        team1,
        team1_query
    )

    name2 = get_team_name(
        team2,
        team2_query
    )

    matches1 = await get_team_matches(team1_id)
    matches2 = await get_team_matches(team2_id)

    if not matches1 or not matches2:

        return (
            "⚠️ I couldn't retrieve enough recent "
            "2026/27 data for this match."
        )

    stats1 = calculate_stats(
        matches1,
        team1_id
    )

    stats2 = calculate_stats(
        matches2,
        team2_id
    )

    markets = get_markets(
        stats1,
        stats2
    )

    top = markets[0]

    form1 = " ".join(stats1["form"])
    form2 = " ".join(stats2["form"])

    if stats1["points"] > stats2["points"]:

        form_edge = (
            f"{name1} has the stronger recent form."
        )

    elif stats2["points"] > stats1["points"]:

        form_edge = (
            f"{name2} has the stronger recent form."
        )

    else:

        form_edge = (
            "Both teams have similar recent form."
        )

    # H2H is optional
    h2h_matches = await get_h2h(
        team1_id,
        team2_id
    )

    h2h = calculate_h2h(
        team1_id,
        h2h_matches
    )

    h2h_text = ""

    if h2h:

        h2h_text = (
            "\n🤝 HEAD-TO-HEAD\n"
            f"Meetings: {h2h['played']}\n"
            f"{name1} wins: {h2h['team1']}\n"
            f"Draws: {h2h['draws']}\n"
            f"{name2} wins: {h2h['team2']}\n"
            f"Average goals: {h2h['avg_goals']}\n"
        )

    market_text = "\n🎯 MARKET SIGNALS\n"

    for item in markets[:3]:

        market_text += (
            f"\n• {item['market']}\n"
            f"  Confidence: {item['confidence']}%\n"
            f"  Advice: {item['advice']}\n"
            f"  {item['reason']}\n"
        )

    response = (
        "⚽ GOALLOGIC AI — ADVANCED ANALYSIS\n\n"

        f"{name1} vs {name2}\n"
        f"Season: {CURRENT_SEASON}\n\n"

        f"📊 {name1} — LAST 5\n"
        f"Form: {form1}\n"
        f"W/D/L: "
        f"{stats1['wins']}/"
        f"{stats1['draws']}/"
        f"{stats1['losses']}\n"
        f"Goals: "
        f"{stats1['goals_for']} scored / "
        f"{stats1['goals_against']} conceded\n"
        f"Over 1.5: {stats1['over15_pct']}%\n"
        f"Over 2.5: {stats1['over25_pct']}%\n"
        f"BTTS: {stats1['btts_pct']}%\n"
        f"Clean sheets: {stats1['clean_pct']}%\n\n"

        f"📊 {name2} — LAST 5\n"
        f"Form: {form2}\n"
        f"W/D/L: "
        f"{stats2['wins']}/"
        f"{stats2['draws']}/"
        f"{stats2['losses']}\n"
        f"Goals: "
        f"{stats2['goals_for']} scored / "
        f"{stats2['goals_against']} conceded\n"
        f"Over 1.5: {stats2['over15_pct']}%\n"
        f"Over 2.5: {stats2['over25_pct']}%\n"
        f"BTTS: {stats2['btts_pct']}%\n"
        f"Clean sheets: {stats2['clean_pct']}%\n"

        + h2h_text

        + "\n📈 FORM ASSESSMENT\n"
        + form_edge

        + market_text

        + "\n⭐ PRIMARY SIGNAL\n"
        f"{top['market']}\n"
        f"Confidence: {top['confidence']}%\n"
        f"Advice: {top['advice']}\n\n"

        "⚠️ RISK WARNING\n"
        "This is statistical analysis, not a guaranteed "
        "match result. Injuries, lineups, tactics and "
        "late team news can change the outcome."
    )

    return response


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "⚽ GOALLOGIC AI\n\n"
        "Send a match like:\n\n"
        "Chelsea vs Arsenal\n\n"
        "I will analyse recent form, goals, "
        "Over 1.5, Over 2.5, BTTS and available H2H."
    )


async def apitest_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    result = await openfoot_get("/v1/health")

    if result and not result.get("_error"):

        await update.message.reply_text(
            "✅ OPENFOOT TEST PASSED\n\n"
            "OpenFoot API is connected successfully."
        )

    else:

        await update.message.reply_text(
            "❌ OPENFOOT TEST FAILED."
        )


async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text or ""

    if text.startswith("/analyze"):

        text = text[
            len("/analyze"):
        ].strip()

    team1, team2 = parse_match(text)

    if not team1 or not team2:

        await update.message.reply_text(
            "❌ Use this format:\n\n"
            "Chelsea vs Arsenal"
        )

        return

    await update.message.reply_text(
        "🔎 Analysing match...\n\n"
        "Please wait."
    )

    try:

        result = await analyze_match(
            team1,
            team2
        )

        await update.message.reply_text(
            result
        )

    except Exception as e:

        print(
            "ANALYSIS ERROR:",
            repr(e)
        )

        await update.message.reply_text(
            "⚠️ Analysis failed.\n\n"
            "Please try another match."
        )


# ============================================================
# MAIN
# ============================================================

def main():

    # Start Render health server
    health_thread = threading.Thread(
        target=start_health_server,
        daemon=True
    )

    health_thread.start()

    print(
        f"GoalLogic AI is running on port {PORT}."
    )

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
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
            filters.TEXT & ~filters.COMMAND,
            analyze_command
        )
    )

    print(
        "GoalLogic AI Telegram bot is starting..."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
