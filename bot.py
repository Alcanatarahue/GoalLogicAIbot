import os
import re
import threading
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


# =========================================================
# SETTINGS
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
        self.wfile.write(
            b"GoalLogic AI is running."
        )

    def log_message(self, format, *args):
        return


def start_health_server():

    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    print(f"Health server running on port {PORT}")

    server.serve_forever()


# =========================================================
# OPENFOOT REQUEST
# =========================================================

def openfoot_get(endpoint, params=None):

    if not OPENFOOT_API_KEY:

        print("OPENFOOT_API_KEY is missing.")

        return None

    url = OPENFOOT_BASE + endpoint

    headers = {
        "Authorization": f"Bearer {OPENFOOT_API_KEY}",
        "Accept": "application/json",
    }

    try:

        response = httpx.get(
            url,
            params=params or {},
            headers=headers,
            timeout=20
        )

        print(
            "OpenFoot:",
            endpoint,
            response.status_code
        )

        if response.status_code != 200:

            print(
                "OpenFoot error:",
                response.text[:500]
            )

            return None

        return response.json()

    except Exception as error:

        print(
            "OpenFoot connection error:",
            repr(error)
        )

        return None


# =========================================================
# SEARCH TEAM
# =========================================================

def search_team(team_name):

    data = openfoot_get(
        "/v1/search",
        {
            "q": team_name
        }
    )

    if not data:

        return None

    results = data.get("data", [])

    if isinstance(results, dict):

        results = (
            results.get("teams")
            or results.get("results")
            or []
        )

    if not isinstance(results, list):

        return None

    wanted = team_name.lower().strip()

    # Exact match first
    for item in results:

        if not isinstance(item, dict):
            continue

        name = str(
            item.get("name")
            or item.get("teamName")
            or item.get("title")
            or ""
        )

        if name.lower() == wanted:

            return item

    # Partial match second
    for item in results:

        if not isinstance(item, dict):
            continue

        name = str(
            item.get("name")
            or item.get("teamName")
            or item.get("title")
            or ""
        )

        if wanted in name.lower():

            return item

    # First usable result
    for item in results:

        if isinstance(item, dict):

            return item

    return None


# =========================================================
# TEAM ID
# =========================================================

def get_team_id(team):

    if not team:
        return None

    return (
        team.get("id")
        or team.get("teamId")
        or team.get("team_id")
    )


def get_team_name(team, fallback):

    if not team:
        return fallback

    return (
        team.get("name")
        or team.get("teamName")
        or fallback
    )


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

    matches = data.get("data", [])

    if isinstance(matches, dict):

        matches = (
            matches.get("matches")
            or matches.get("results")
            or []
        )

    if not isinstance(matches, list):

        return []

    return matches


# =========================================================
# MATCH HELPERS
# =========================================================

def team_id_from_match(team):

    if not isinstance(team, dict):
        return None

    return (
        team.get("id")
        or team.get("teamId")
        or team.get("team_id")
    )


def team_name_from_match(team):

    if not isinstance(team, dict):
        return "Unknown"

    return (
        team.get("name")
        or team.get("teamName")
        or "Unknown"
    )


def get_match_status(match):

    return str(
        match.get("status")
        or ""
    ).lower()


def get_score_value(score):

    if score is None:
        return None

    if isinstance(score, int):
        return score

    if isinstance(score, float):
        return int(score)

    if isinstance(score, str):

        try:
            return int(score)

        except ValueError:
            return None

    if isinstance(score, dict):

        for key in [
            "home",
            "away",
            "goals",
            "value",
            "total",
            "current",
            "display"
        ]:

            if key in score:

                value = score[key]

                if isinstance(value, int):
                    return value

                if isinstance(value, str):

                    try:
                        return int(value)

                    except ValueError:
                        pass

    return None


def extract_scores(match):

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

    score = match.get("score") or {}

    home_score = None
    away_score = None

    # Common OpenFoot shape
    if isinstance(score, dict):

        if "home" in score:

            home_score = get_score_value(
                score.get("home")
            )

        if "away" in score:

            away_score = get_score_value(
                score.get("away")
            )

        # Sometimes nested
        if home_score is None:

            home_score = get_score_value(
                score.get("fullTime", {}).get("home")
                if isinstance(score.get("fullTime"), dict)
                else None
            )

        if away_score is None:

            away_score = get_score_value(
                score.get("fullTime", {}).get("away")
                if isinstance(score.get("fullTime"), dict)
                else None
            )

    # Other possible fields
    if home_score is None:

        home_score = get_score_value(
            match.get("homeScore")
        )

    if away_score is None:

        away_score = get_score_value(
            match.get("awayScore")
        )

    return home_score, away_score


def extract_kickoff(match):

    return (
        match.get("kickoffAt")
        or match.get("date")
        or match.get("kickoff")
        or ""
    )


# =========================================================
# NORMALIZE TEAM FORM
# =========================================================

def build_team_form(matches, team_id):

    completed = []

    for match in matches:

        status = get_match_status(match)

        if status not in [
            "finished",
            "ft",
            "completed",
            "fulltime"
        ]:

            continue

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

        home_id = team_id_from_match(home)
        away_id = team_id_from_match(away)

        home_score, away_score = extract_scores(match)

        if home_score is None or away_score is None:
            continue

        if home_id == team_id:

            goals_for = home_score
            goals_against = away_score
            venue = "Home"
            opponent = team_name_from_match(away)

        elif away_id == team_id:

            goals_for = away_score
            goals_against = home_score
            venue = "Away"
            opponent = team_name_from_match(home)

        else:

            continue

        if goals_for > goals_against:

            result = "W"

        elif goals_for == goals_against:

            result = "D"

        else:

            result = "L"

        completed.append({
            "date": extract_kickoff(match),
            "opponent": opponent,
            "venue": venue,
            "gf": goals_for,
            "ga": goals_against,
            "result": result,
        })

    # Sort newest first
    completed.sort(
        key=lambda x: x["date"],
        reverse=True
    )

    return completed[:5]


# =========================================================
# FORM STATISTICS
# =========================================================

def calculate_stats(form):

    if not form:

        return {
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
        }

    wins = 0
    draws = 0
    losses = 0

    goals_for = 0
    goals_against = 0

    over15 = 0
    over25 = 0
    btts = 0
    clean_sheets = 0

    for game in form:

        gf = game["gf"]
        ga = game["ga"]

        goals_for += gf
        goals_against += ga

        if game["result"] == "W":
            wins += 1

        elif game["result"] == "D":
            draws += 1

        else:
            losses += 1

        total = gf + ga

        if total >= 2:
            over15 += 1

        if total >= 3:
            over25 += 1

        if gf >= 1 and ga >= 1:
            btts += 1

        if ga == 0:
            clean_sheets += 1

    played = len(form)

    return {
        "played": played,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "over15": round(over15 / played * 100),
        "over25": round(over25 / played * 100),
        "btts": round(btts / played * 100),
        "clean_sheets": round(clean_sheets / played * 100),
    }


# =========================================================
# MARKET SIGNALS
# =========================================================

def market_signals(home_stats, away_stats):

    signals = []

    # Over 1.5
    if (
        home_stats["over15"] >= 80
        and away_stats["over15"] >= 80
    ):

        signals.append(
            (
                "Over 1.5 Goals",
                min(
                    home_stats["over15"],
                    away_stats["over15"]
                ),
                "Both teams have recorded 2+ total goals in at least 80% of their recent matches."
            )
        )

    # Over 2.5
    if (
        home_stats["over25"] >= 60
        and away_stats["over25"] >= 60
    ):

        signals.append(
            (
                "Over 2.5 Goals",
                min(
                    home_stats["over25"],
                    away_stats["over25"]
                ),
                "Both teams have a strong recent Over 2.5 rate."
            )
        )

    # BTTS
    if (
        home_stats["btts"] >= 60
        and away_stats["btts"] >= 60
    ):

        signals.append(
            (
                "Both Teams To Score",
                min(
                    home_stats["btts"],
                    away_stats["btts"]
                ),
                "Both teams have scored and conceded regularly in recent matches."
            )
        )

    # Home team scoring
    if home_stats["played"] > 0:

        home_scoring_rate = round(
            (
                home_stats["played"]
                - home_stats["clean_sheets"]
            )
            / home_stats["played"]
            * 100
        )

    # Defensive market
    if (
        home_stats["clean_sheets"] >= 40
        and away_stats["clean_sheets"] >= 40
    ):

        signals.append(
            (
                "Under 4.5 Goals",
                70,
                "Both teams have shown some defensive stability recently."
            )
        )

    return signals


# =========================================================
# FORMAT FORM
# =========================================================

def form_string(form):

    if not form:
        return "No recent completed matches found."

    return " ".join(
        game["result"]
        for game in form
    )


def recent_results_text(form):

    if not form:
        return "No recent results available."

    lines = []

    for game in form:

        lines.append(
            f'{game["venue"][0]} vs {game["opponent"]}: '
            f'{game["gf"]}-{game["ga"]} ({game["result"]})'
        )

    return "\n".join(lines)


# =========================================================
# ANALYSIS ENGINE
# =========================================================

def analyze_match(home_name, away_name):

    print(
        f"Analyzing: {home_name} vs {away_name}"
    )

    home_team = search_team(home_name)
    away_team = search_team(away_name)

    if not home_team:

        return (
            f"❌ I couldn't find **{home_name}** in OpenFoot."
        )

    if not away_team:

        return (
            f"❌ I couldn't find **{away_name}** in OpenFoot."
        )

    home_id = get_team_id(home_team)
    away_id = get_team_id(away_team)

    if not home_id or not away_id:

        return (
            "❌ I found the teams but could not obtain "
            "their OpenFoot IDs."
        )

    home_display = get_team_name(
        home_team,
        home_name
    )

    away_display = get_team_name(
        away_team,
        away_name
    )

    home_matches = get_team_matches(home_id)
    away_matches = get_team_matches(away_id)

    home_form = build_team_form(
        home_matches,
        home_id
    )

    away_form = build_team_form(
        away_matches,
        away_id
    )

    home_stats = calculate_stats(
        home_form
    )

    away_stats = calculate_stats(
        away_form
    )

    if (
        home_stats["played"] == 0
        or away_stats["played"] == 0
    ):

        return (
            f"⚠️ **{home_display} vs {away_display}**\n\n"
            "I found the teams, but there isn't enough "
            f"completed {CURRENT_SEASON} match data yet "
            "to produce a reliable statistical analysis."
        )

    signals = market_signals(
        home_stats,
        away_stats
    )

    # Overall form points
    home_points = (
        home_stats["wins"] * 3
        + home_stats["draws"]
    )

    away_points = (
        away_stats["wins"] * 3
        + away_stats["draws"]
    )

    if home_points > away_points:

        form_edge = (
            f"Recent form edge: **{home_display}**"
        )

    elif away_points > home_points:

        form_edge = (
            f"Recent form edge: **{away_display}**"
        )

    else:

        form_edge = (
            "Recent form: **fairly balanced**"
        )

    # Market section
    if signals:

        market_lines = []

        for name, confidence, reason in signals:

            market_lines.append(
                f"• **{name}** — {confidence}%\n"
                f"  {reason}"
            )

        market_text = "\n".join(
            market_lines
        )

    else:

        market_text = (
            "No strong market signal from the "
            "available recent-form data."
        )

    # Final response
    response = (
        f"⚽ **GOALLOGIC AI ANALYSIS**\n\n"
        f"**{home_display} vs {away_display}**\n"
        f"Season: {CURRENT_SEASON}\n\n"

        f"📊 **{home_display} — Last {home_stats['played']}**\n"
        f"Form: `{form_string(home_form)}`\n"
        f"W/D/L: {home_stats['wins']}/"
        f"{home_stats['draws']}/"
        f"{home_stats['losses']}\n"
        f"Goals: {home_stats['goals_for']} scored / "
        f"{home_stats['goals_against']} conceded\n"
        f"Over 1.5: {home_stats['over15']}%\n"
        f"Over 2.5: {home_stats['over25']}%\n"
        f"BTTS: {home_stats['btts']}%\n"
        f"Clean sheets: {home_stats['clean_sheets']}%\n\n"

        f"📊 **{away_display} — Last {away_stats['played']}**\n"
        f"Form: `{form_string(away_form)}`\n"
        f"W/D/L: {away_stats['wins']}/"
        f"{away_stats['draws']}/"
        f"{away_stats['losses']}\n"
        f"Goals: {away_stats['goals_for']} scored / "
        f"{away_stats['goals_against']} conceded\n"
        f"Over 1.5: {away_stats['over15']}%\n"
        f"Over 2.5: {away_stats['over25']}%\n"
        f"BTTS: {away_stats['btts']}%\n"
        f"Clean sheets: {away_stats['clean_sheets']}%\n\n"

        f"📈 **FORM ASSESSMENT**\n"
        f"{form_edge}\n\n"

        f"🎯 **MARKET SIGNALS**\n"
        f"{market_text}\n\n"

        f"⚠️ **Important**\n"
        f"This is statistical analysis, not a guarantee "
        f"of a match result. Team news, lineups, injuries "
        f"and late changes can affect the outcome."
    )

    return response


# =========================================================
# PARSE MATCH MESSAGE
# =========================================================

def parse_match(text):

    patterns = [
        r"(.+?)\s+vs\.?\s+(.+)",
        r"(.+?)\s+v\s+(.+)",
        r"(.+?)\s+-\s+(.+)",
    ]

    for pattern in patterns:

        match = re.match(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            home = match.group(1).strip()
            away = match.group(2).strip()

            if home and away:

                return home, away

    return None, None


# =========================================================
# TELEGRAM COMMANDS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🤖 **GoalLogic AI is online!**\n\n"
        "Send me a match like:\n\n"
        "Chelsea vs Arsenal\n\n"
        "I will analyze recent form, goals, "
        "Over/Under and BTTS statistics."
    )


async def apitest(update: Update, context: ContextTypes.DEFAULT_TYPE):

    result = openfoot_get(
        "/v1/search",
        {
            "q": "Arsenal"
        }
    )

    if result is not None:

        await update.message.reply_text(
            "✅ **OPENFOOT TEST PASSED**\n\n"
            "OpenFoot API is connected successfully."
        )

    else:

        await update.message.reply_text(
            "❌ **OPENFOOT TEST FAILED**\n\n"
            "OpenFoot could not be reached."
        )


async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Use:\n\n"
            "/analyze Chelsea vs Arsenal"
        )

        return

    text = " ".join(
        context.args
    )

    home, away = parse_match(text)

    if not home or not away:

        await update.message.reply_text(
            "Please use:\n\n"
            "/analyze Chelsea vs Arsenal"
        )

        return

    await update.message.reply_text(
        f"🔎 Analyzing **{home} vs {away}**...\n\n"
        "This may take a few seconds."
    )

    result = analyze_match(
        home,
        away
    )

    await update.message.reply_text(
        result,
        parse_mode="Markdown"
    )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    home, away = parse_match(text)

    if not home or not away:

        await update.message.reply_text(
            "⚽ Send a match like:\n\n"
            "Chelsea vs Arsenal\n\n"
            "or use:\n\n"
            "/analyze Chelsea vs Arsenal"
        )

        return

    await update.message.reply_text(
        f"🔎 Analyzing **{home} vs {away}**...\n\n"
        "Please wait."
    )

    result = analyze_match(
        home,
        away
    )

    await update.message.reply_text(
        result,
        parse_mode="Markdown"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not TELEGRAM_BOT_TOKEN:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN is missing."
        )

        return

    if not OPENFOOT_API_KEY:

        print(
            "WARNING: OPENFOOT_API_KEY is missing."
        )

    print(
        "Starting GoalLogic AI..."
    )

    health_thread = threading.Thread(
        target=start_health_server,
        daemon=True
    )

    health_thread.start()

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "apitest",
            apitest
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
            handle_message
        )
    )

    print(
        "GoalLogic AI is running."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
