import os
import re
import asyncio
from datetime import datetime, timezone
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
# GOALLOGIC AI — ADVANCED FOOTBALL ANALYSIS
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
        return


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
                return {
                    "_error": True,
                    "status": response.status_code,
                    "body": data,
                }

            return data

    except Exception as e:
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
        data = data.get("teams", data.get("results", []))

    if not isinstance(data, list):
        return None

    team_name_lower = team_name.lower().strip()

    # Exact match first
    for item in data:
        if not isinstance(item, dict):
            continue

        name = str(
            item.get("name")
            or item.get("team", {}).get("name", "")
        )

        if name.lower().strip() == team_name_lower:
            return item

    # Partial match
    for item in data:
        if not isinstance(item, dict):
            continue

        name = str(
            item.get("name")
            or item.get("team", {}).get("name", "")
        )

        if team_name_lower in name.lower():
            return item

    # First usable result
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

    if isinstance(nested, dict) and nested.get("name"):
        return str(nested["name"])

    return fallback


# ============================================================
# SCORE HELPERS
# ============================================================

def number(value):

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

        fulltime = score.get("fullTime") or score.get("fulltime")

        if isinstance(fulltime, dict):
            home_score = number(
                fulltime.get("home")
                if fulltime.get("home") is not None
                else fulltime.get("homeScore")
            )

            away_score = number(
                fulltime.get("away")
                if fulltime.get("away") is not None
                else fulltime.get("awayScore")
            )

        if home_score is None:
            home_score = number(score.get("home"))

        if away_score is None:
            away_score = number(score.get("away"))

    # Alternative structures
    if home_score is None:
        home_score = number(match.get("homeScore"))

    if away_score is None:
        away_score = number(match.get("awayScore"))

    if home_score is None:
        home_score = number(match.get("homeGoals"))

    if away_score is None:
        away_score = number(match.get("awayGoals"))

    return home_score, away_score


def extract_team_ids(match):

    home = match.get("homeTeam") or match.get("home") or {}
    away = match.get("awayTeam") or match.get("away") or {}

    if not isinstance(home, dict):
        home = {}

    if not isinstance(away, dict):
        away = {}

    return (
        home.get("id"),
        away.get("id"),
    )


def extract_kickoff(match):

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
        data = data.get("matches", data.get("results", []))

    if not isinstance(data, list):
        return []

    finished = []

    for match in data:

        if not isinstance(match, dict):
            continue

        status = str(match.get("status", "")).lower()

        # Only completed games
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

        finished.append({
            "match": match,
            "home_id": home_id,
            "away_id": away_id,
            "home_score": home_score,
            "away_score": away_score,
            "kickoff": extract_kickoff(match),
        })

    # Newest first
    finished.sort(
        key=lambda x: str(x.get("kickoff", "")),
        reverse=True
    )

    return finished


# ============================================================
# TEAM STATISTICS
# ============================================================

def calculate_team_stats(matches, team_id):

    last_matches = matches[:5]

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
        "form_points": 0,
        "home_played": 0,
        "home_wins": 0,
        "home_draws": 0,
        "home_losses": 0,
        "away_played": 0,
        "away_wins": 0,
        "away_draws": 0,
        "away_losses": 0,
        "form": [],
        "results": [],
    }

    for item in last_matches:

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

        total_goals = hs + aws

        if total_goals >= 2:
            stats["over15"] += 1

        if total_goals >= 3:
            stats["over25"] += 1

        if hs > 0 and aws > 0:
            stats["btts"] += 1

        if ga == 0:
            stats["clean_sheets"] += 1

        if gf > 0:
            stats["scored"] += 1

        if gf > ga:
            result = "W"
            stats["wins"] += 1
            stats["form_points"] += 3

        elif gf == ga:
            result = "D"
            stats["draws"] += 1
            stats["form_points"] += 1

        else:
            result = "L"
            stats["losses"] += 1

        stats["form"].append(result)

        stats["results"].append({
            "result": result,
            "gf": gf,
            "ga": ga,
            "total": total_goals,
            "home": is_home,
        })

        if is_home:

            stats["home_played"] += 1

            if result == "W":
                stats["home_wins"] += 1
            elif result == "D":
                stats["home_draws"] += 1
            else:
                stats["home_losses"] += 1

        else:

            stats["away_played"] += 1

            if result == "W":
                stats["away_wins"] += 1
            elif result == "D":
                stats["away_draws"] += 1
            else:
                stats["away_losses"] += 1

    played = stats["played"] or 1

    stats["over15_pct"] = round(
        stats["over15"] / played * 100
    )

    stats["over25_pct"] = round(
        stats["over25"] / played * 100
    )

    stats["btts_pct"] = round(
        stats["btts"] / played * 100
    )

    stats["clean_sheet_pct"] = round(
        stats["clean_sheets"] / played * 100
    )

    stats["scored_pct"] = round(
        stats["scored"] / played * 100
    )

    stats["avg_goals_for"] = round(
        stats["goals_for"] / played,
        2
    )

    stats["avg_goals_against"] = round(
        stats["goals_against"] / played,
        2
    )

    return stats


# ============================================================
# STANDINGS
# ============================================================

async def get_standings(competition_id):

    if not competition_id:
        return None

    result = await openfoot_get(
        "/v1/standings",
        {
            "competition": competition_id,
            "season": CURRENT_SEASON,
        }
    )

    if not result or result.get("_error"):
        return None

    data = result.get("data")

    if isinstance(data, dict):
        rows = (
            data.get("standings")
            or data.get("table")
            or data.get("rows")
            or []
        )
    elif isinstance(data, list):
        rows = data
    else:
        return None

    if not isinstance(rows, list):
        return None

    return rows


def find_standing(rows, team_id, team_name):

    if not rows:
        return None

    target = team_name.lower()

    for row in rows:

        if not isinstance(row, dict):
            continue

        team = row.get("team")

        if not isinstance(team, dict):
            team = {}

        rid = row.get("teamId") or team.get("id")
        rname = str(
            row.get("teamName")
            or team.get("name")
            or ""
        )

        if rid == team_id:
            return row

        if rname.lower() == target:
            return row

    return None


def standing_position(row):

    if not row:
        return None

    return (
        row.get("position")
        or row.get("rank")
        or row.get("place")
    )


def standing_points(row):

    if not row:
        return None

    return row.get("points")


# ============================================================
# H2H
# ============================================================

async def get_h2h(team1_id, team2_id):

    if not team1_id or not team2_id:
        return None

    result = await openfoot_get(
        f"/v1/teams/{team1_id}/h2h",
        {"opponent": team2_id}
    )

    # Some OpenFoot tiers restrict H2H.
    # If restricted, simply continue without it.
    if not result or result.get("_error"):
        return None

    data = result.get("data", [])

    if isinstance(data, dict):
        data = (
            data.get("matches")
            or data.get("h2h")
            or data.get("results")
            or []
        )

    if not isinstance(data, list):
        return None

    return data[:5]


def calculate_h2h(team1_id, h2h):

    if not h2h:
        return None

    result = {
        "played": 0,
        "team1_wins": 0,
        "draws": 0,
        "team2_wins": 0,
        "goals": 0,
    }

    for match in h2h:

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
                result["team1_wins"] += 1
            elif hs == aws:
                result["draws"] += 1
            else:
                result["team2_wins"] += 1

        elif away_id == team1_id:

            if aws > hs:
                result["team1_wins"] += 1
            elif hs == aws:
                result["draws"] += 1
            else:
                result["team2_wins"] += 1

    if result["played"] == 0:
        return None

    result["avg_goals"] = round(
        result["goals"] / result["played"],
        2
    )

    return result


# ============================================================
# CONFIDENCE ENGINE
# ============================================================

def calculate_confidence(
    team1_stats,
    team2_stats,
    market
):

    score = 50

    if market == "Over 1.5 Goals":

        average = (
            team1_stats["over15_pct"]
            + team2_stats["over15_pct"]
        ) / 2

        score += (average - 70) * 0.35

    elif market == "Over 2.5 Goals":

        average = (
            team1_stats["over25_pct"]
            + team2_stats["over25_pct"]
        ) / 2

        score += (average - 50) * 0.40

    elif market == "BTTS":

        average = (
            team1_stats["btts_pct"]
            + team2_stats["btts_pct"]
        ) / 2

        score += (average - 50) * 0.40

    elif market == "Under 4.5 Goals":

        average_clean = (
            team1_stats["clean_sheet_pct"]
            + team2_stats["clean_sheet_pct"]
        ) / 2

        score += (average_clean - 20) * 0.30

    return max(45, min(88, round(score)))


# ============================================================
# MARKET ANALYSIS
# ============================================================

def market_analysis(team1_stats, team2_stats):

    markets = []

    over15_average = (
        team1_stats["over15_pct"]
        + team2_stats["over15_pct"]
    ) / 2

    over25_average = (
        team1_stats["over25_pct"]
        + team2_stats["over25_pct"]
    ) / 2

    btts_average = (
        team1_stats["btts_pct"]
        + team2_stats["btts_pct"]
    ) / 2

    clean_average = (
        team1_stats["clean_sheet_pct"]
        + team2_stats["clean_sheet_pct"]
    ) / 2

    # Over 1.5
    if (
        team1_stats["over15_pct"] >= 80
        and team2_stats["over15_pct"] >= 80
    ):
        confidence = calculate_confidence(
            team1_stats,
            team2_stats,
            "Over 1.5 Goals"
        )

        markets.append({
            "name": "Over 1.5 Goals",
            "confidence": confidence,
            "advice": "BET",
            "reason": (
                f"Both teams have strong recent Over 1.5 rates "
                f"({team1_stats['over15_pct']}% and "
                f"{team2_stats['over15_pct']}%)."
            )
        })

    # Over 2.5
    if (
        team1_stats["over25_pct"] >= 60
        and team2_stats["over25_pct"] >= 60
    ):
        confidence = calculate_confidence(
            team1_stats,
            team2_stats,
            "Over 2.5 Goals"
        )

        markets.append({
            "name": "Over 2.5 Goals",
            "confidence": confidence,
            "advice": "BET",
            "reason": (
                f"Both teams have recorded Over 2.5 in "
                f"{team1_stats['over25_pct']}% and "
                f"{team2_stats['over25_pct']}% of their last five."
            )
        })

    # BTTS
    if (
        team1_stats["btts_pct"] >= 60
        and team2_stats["btts_pct"] >= 60
    ):
        confidence = calculate_confidence(
            team1_stats,
            team2_stats,
            "BTTS"
        )

        markets.append({
            "name": "BTTS — Yes",
            "confidence": confidence,
            "advice": "BET",
            "reason": (
                f"Both teams have scored and conceded in a high "
                f"percentage of their recent matches."
            )
        })

    # Under 4.5
    if clean_average >= 30:

        confidence = calculate_confidence(
            team1_stats,
            team2_stats,
            "Under 4.5 Goals"
        )

        markets.append({
            "name": "Under 4.5 Goals",
            "confidence": confidence,
            "advice": "ALTERNATIVE",
            "reason": (
                "Recent results show relatively limited "
                "high-scoring frequency."
            )
        })

    # If nothing strong
    if not markets:

        markets.append({
            "name": "No Strong Market",
            "confidence": 45,
            "advice": "AVOID",
            "reason": (
                "The recent statistics do not produce a strong "
                "enough signal for the main goal markets."
            )
        })

    markets.sort(
        key=lambda x: x["confidence"],
        reverse=True
    )

    return markets


# ============================================================
# FORM ASSESSMENT
# ============================================================

def form_assessment(stats1, stats2):

    p1 = stats1["form_points"]
    p2 = stats2["form_points"]

    if p1 > p2:
        return "Team 1 has the stronger recent form."

    if p2 > p1:
        return "Team 2 has the stronger recent form."

    return "Recent form is relatively even."


# ============================================================
# FORMAT TEAM BLOCK
# ============================================================

def team_block(name, stats):

    form = " ".join(stats["form"]) if stats["form"] else "N/A"

    return (
        f"📊 {name} — LAST 5\n"
        f"Form: {form}\n"
        f"W/D/L: {stats['wins']}/{stats['draws']}/{stats['losses']}\n"
        f"Goals: {stats['goals_for']} scored / "
        f"{stats['goals_against']} conceded\n"
        f"Avg goals scored: {stats['avg_goals_for']}\n"
        f"Avg goals conceded: {stats['avg_goals_against']}\n"
        f"Over 1.5: {stats['over15_pct']}%\n"
        f"Over 2.5: {stats['over25_pct']}%\n"
        f"BTTS: {stats['btts_pct']}%\n"
        f"Clean sheets: {stats['clean_sheet_pct']}%\n"
        f"Scored in: {stats['scored_pct']}%\n"
    )


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
# MAIN ANALYSIS
# ============================================================

async def analyze_match(team1_query, team2_query):

    team1 = await search_team(team1_query)
    team2 = await search_team(team2_query)

    if not team1:
        return f"❌ I couldn't find **{team1_query}**."

    if not team2:
        return f"❌ I couldn't find **{team2_query}**."

    team1_id = get_team_id(team1)
    team2_id = get_team_id(team2)

    if not team1_id:
        return f"❌ I couldn't get the OpenFoot ID for {team1_query}."

    if not team2_id:
        return f"❌ I couldn't get the OpenFoot ID for {team2_query}."

    name1 = get_team_name(team1, team1_query)
    name2 = get_team_name(team2, team2_query)

    matches1 = await get_team_matches(team1_id)
    matches2 = await get_team_matches(team2_id)

    if len(matches1) == 0:
        return (
            f"⚠️ I couldn't retrieve recent {CURRENT_SEASON} "
            f"matches for {name1}."
        )

    if len(matches2) == 0:
        return (
            f"⚠️ I couldn't retrieve recent {CURRENT_SEASON} "
            f"matches for {name2}."
        )

    stats1 = calculate_team_stats(
        matches1,
        team1_id
    )

    stats2 = calculate_team_stats(
        matches2,
        team2_id
    )

    # Competition ID from recent match
    competition_id = None

    for item in matches1:

        match = item["match"]

        competition_id = (
            match.get("competitionId")
            or match.get("competition", {}).get("id")
            if isinstance(match.get("competition"), dict)
            else match.get("competitionId")
        )

        if competition_id:
            break

    standings = None

    if competition_id:
        standings = await get_standings(
            competition_id
        )

    standing1 = find_standing(
        standings,
        team1_id,
        name1
    )

    standing2 = find_standing(
        standings,
        team2_id,
        name2
    )

    # H2H is optional. If the plan blocks it,
    # the rest of the analysis still works.
    h2h_data = await get_h2h(
        team1_id,
        team2_id
    )

    h2h = calculate_h2h(
        team1_id,
        h2h_data
    )

    markets = market_analysis(
        stats1,
        stats2
    )

    top_market = markets[0]

    form_text = form_assessment(
        stats1,
        stats2
    )

    # --------------------------------------------------------
    # STANDINGS
    # --------------------------------------------------------

    standings_text = ""

    if standing1 or standing2:

        pos1 = standing_position(standing1)
        pos2 = standing_position(standing2)

        pts1 = standing_points(standing1)
        pts2 = standing_points(standing2)

        standings_text = (
            "\n🏆 LEAGUE TABLE\n"
            f"{name1}: "
            f"{pos1 if pos1 is not None else 'N/A'}"
            f" — {pts1 if pts1 is not None else 'N/A'} pts\n"
            f"{name2}: "
            f"{pos2 if pos2 is not None else 'N/A'}"
            f" — {pts2 if pts2 is not None else 'N/A'} pts\n"
        )

    # --------------------------------------------------------
    # H2H
    # --------------------------------------------------------

    h2h_text = ""

    if h2h:

        h2h_text = (
            "\n🤝 HEAD-TO-HEAD\n"
            f"Meetings analysed: {h2h['played']}\n"
            f"{name1} wins: {h2h['team1_wins']}\n"
            f"Draws: {h2h['draws']}\n"
            f"{name2} wins: {h2h['team2_wins']}\n"
            f"Average goals: {h2h['avg_goals']}\n"
        )

    # --------------------------------------------------------
    # MARKET LIST
    # --------------------------------------------------------

    market_text = "\n🎯 MARKET SIGNALS\n"

    for market in markets[:4]:

        market_text += (
            f"\n• {market['name']}\n"
            f"  Confidence: {market['confidence']}%\n"
            f"  Advice: {market['advice']}\n"
            f"  Reason: {market['reason']}\n"
        )

    # --------------------------------------------------------
    # FINAL OUTPUT
    # --------------------------------------------------------

    response = (
        "⚽ *GOALLOGIC AI — ADVANCED ANALYSIS*\n\n"
        f"*{name1} vs {name2}*\n"
        f"Season: {CURRENT_SEASON}\n\n"

        + team_block(name1, stats1)
        + "\n"
        + team_block(name2, stats2)

        + standings_text
        + h2h_text

        + "\n📈 FORM ASSESSMENT\n"
        f"{form_text}\n"

        + market_text

        + "\n⭐ PRIMARY STATISTICAL SIGNAL\n"
        f"{top_market['name']}\n"
        f"Confidence: {top_market['confidence']}%\n"
        f"Advice: {top_market['advice']}\n"

        + "\n🧠 ANALYSIS\n"
        f"{top_market['reason']}\n"

        + "\n⚠️ RISK NOTE\n"
        "This is statistical analysis, not a guaranteed result. "
        "Lineups, injuries, tactics, motivation and late team news "
        "can change a match."
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
        "Over 1.5, Over 2.5, BTTS, clean sheets, "
        "league position and available H2H data."
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
            "❌ OPENFOOT TEST FAILED\n\n"
            "The API could not be reached."
        )


async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text or ""

    if text.startswith("/analyze"):
        text = text[len("/analyze"):].strip()

    team1, team2 = parse_match(text)

    if not team1 or not team2:

        await update.message.reply_text(
            "❌ Please use this format:\n\n"
            "Chelsea vs Arsenal"
        )

        return

    await update.message.reply_text(
        "🔎 Analysing the match...\n\n"
        "Checking recent form and available statistics."
    )

    try:

        result = await analyze_match(
            team1,
            team2
        )

        await update.message.reply_text(
            result,
            parse_mode="Markdown"
        )

    except Exception as e:

        print("ANALYSIS ERROR:", repr(e))

        await update.message.reply_text(
            "⚠️ Something went wrong while analysing "
            "this match.\n\n"
            "Please try again."
        )


# ============================================================
# TELEGRAM APPLICATION
# ============================================================

def main():

    health_thread = asyncio.get_event_loop()

    import threading

    thread = threading.Thread(
        target=start_health_server,
        daemon=True
    )

    thread.start()

    print(f"GoalLogic AI is running on port {PORT}.")

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

    print("GoalLogic AI Telegram bot is starting...")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
