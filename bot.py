import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")

PORT = int(os.getenv("PORT", "10000"))

API_BASE = "https://v3.football.api-sports.io"

# Current free API plan allows seasons 2022-2024
FIXTURE_SEASON = 2024


# ==================================================
# RENDER HEALTH SERVER
# ==================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain"
        )

        self.end_headers()

        self.wfile.write(
            b"GoalLogic AI is running"
        )

    def log_message(self, format, *args):
        return


def start_health_server():

    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    server.serve_forever()


# ==================================================
# FOOTBALL API
# ==================================================

async def api_get(endpoint, params=None):

    headers = {
        "x-apisports-key": FOOTBALL_API_KEY
    }

    async with httpx.AsyncClient(
        timeout=30
    ) as client:

        response = await client.get(
            f"{API_BASE}/{endpoint}",
            headers=headers,
            params=params
        )

        return response


# ==================================================
# START
# ==================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "⚽ GoalLogic AI is online!\n\n"

        "Commands:\n\n"

        "/team Chelsea\n"
        "/fixtures Chelsea\n"
        "/analyze Chelsea vs Arsenal\n"
        "/apitest"
    )


# ==================================================
# API TEST
# ==================================================

async def api_test(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        response = await api_get("status")

        await update.message.reply_text(

            "🔧 FOOTBALL API TEST\n\n"
            f"HTTP Status: {response.status_code}\n\n"
            f"Response:\n{response.text[:2500]}"
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ API test failed:\n{e}"
        )


# ==================================================
# FIND TEAM
# ==================================================

async def find_team(team_name):

    response = await api_get(
        "teams",
        {
            "search": team_name
        }
    )

    data = response.json()

    if data.get("errors"):
        return None, data.get("errors")

    teams = data.get(
        "response",
        []
    )

    if not teams:
        return None, "Team not found"

    for item in teams:

        name = item.get(
            "team",
            {}
        ).get(
            "name",
            ""
        )

        if name.lower() == team_name.lower():

            return item.get(
                "team",
                {}
            ), None

    return teams[0].get(
        "team",
        {}
    ), None


# ==================================================
# TEAM SEARCH
# ==================================================

async def team_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Use:\n/team Chelsea"
        )

        return

    team_name = " ".join(context.args)

    try:

        response = await api_get(
            "teams",
            {
                "search": team_name
            }
        )

        data = response.json()

        if data.get("errors"):

            await update.message.reply_text(
                f"❌ API error:\n{data['errors']}"
            )

            return

        teams = data.get(
            "response",
            []
        )

        if not teams:

            await update.message.reply_text(
                f"❌ No team found for {team_name}"
            )

            return

        reply = (
            f"🔎 Teams matching "
            f"'{team_name}':\n\n"
        )

        for item in teams[:10]:

            team = item.get(
                "team",
                {}
            )

            reply += (
                f"⚽ {team.get('name', 'Unknown')}\n"
                f"ID: {team.get('id', 'Unknown')}\n"
                f"Country: {team.get('country', 'Unknown')}\n\n"
            )

        await update.message.reply_text(reply)

    except Exception as e:

        await update.message.reply_text(
            f"⚠️ Error searching team:\n{e}"
        )


# ==================================================
# FIXTURES
# ==================================================

async def fixtures(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Use:\n/fixtures Chelsea"
        )

        return

    team_name = " ".join(context.args)

    try:

        team, error = await find_team(team_name)

        if error:

            await update.message.reply_text(
                f"❌ {error}"
            )

            return

        team_id = team.get("id")

        official_name = team.get(
            "name",
            team_name
        )

        response = await api_get(
            "fixtures",
            {
                "team": team_id,
                "season": FIXTURE_SEASON
            }
        )

        data = response.json()

        if data.get("errors"):

            await update.message.reply_text(
                f"❌ Fixture API error:\n"
                f"{data['errors']}"
            )

            return

        matches = data.get(
            "response",
            []
        )

        if not matches:

            await update.message.reply_text(
                "ℹ️ No fixtures returned."
            )

            return

        reply = (
            f"📅 Fixtures for {official_name}\n"
            f"🗓️ Season {FIXTURE_SEASON}\n\n"
        )

        for match in matches[:15]:

            fixture = match.get(
                "fixture",
                {}
            )

            teams_info = match.get(
                "teams",
                {}
            )

            league = match.get(
                "league",
                {}
            )

            home = teams_info.get(
                "home",
                {}
            ).get(
                "name",
                "Unknown"
            )

            away = teams_info.get(
                "away",
                {}
            ).get(
                "name",
                "Unknown"
            )

            date_string = fixture.get(
                "date",
                ""
            )

            if date_string:

                try:

                    date_object = datetime.fromisoformat(
                        date_string.replace(
                            "Z",
                            "+00:00"
                        )
                    )

                    date_display = date_object.strftime(
                        "%d %b %Y, %H:%M UTC"
                    )

                except Exception:

                    date_display = date_string

            else:

                date_display = "Date unavailable"

            reply += (
                f"📅 {date_display}\n"
                f"⚽ {home} vs {away}\n"
                f"🏆 {league.get('name', 'Unknown')}\n\n"
            )

        reply += (
            f"Showing up to 15 fixtures.\n"
            f"Total returned: {len(matches)}"
        )

        await update.message.reply_text(reply)

    except Exception as e:

        await update.message.reply_text(
            f"⚠️ Error fetching fixtures:\n{e}"
        )


# ==================================================
# CALCULATE TEAM GOAL STATISTICS
# ==================================================

def calculate_goal_stats(matches, team_id):

    matches = matches[-5:]

    played = 0
    wins = 0
    draws = 0
    losses = 0

    goals_for = 0
    goals_against = 0

    over_1_5 = 0
    over_2_5 = 0
    btts = 0

    for match in matches:

        teams_info = match.get(
            "teams",
            {}
        )

        score = match.get(
            "goals",
            {}
        )

        home_score = score.get("home")
        away_score = score.get("away")

        if home_score is None or away_score is None:
            continue

        home_team_id = teams_info.get(
            "home",
            {}
        ).get("id")

        away_team_id = teams_info.get(
            "away",
            {}
        ).get("id")

        if team_id == home_team_id:

            team_goals = home_score
            opponent_goals = away_score

        elif team_id == away_team_id:

            team_goals = away_score
            opponent_goals = home_score

        else:

            continue

        played += 1

        goals_for += team_goals
        goals_against += opponent_goals

        if team_goals > opponent_goals:

            wins += 1

        elif team_goals == opponent_goals:

            draws += 1

        else:

            losses += 1

        total_goals = (
            team_goals + opponent_goals
        )

        if total_goals >= 2:
            over_1_5 += 1

        if total_goals >= 3:
            over_2_5 += 1

        if team_goals >= 1 and opponent_goals >= 1:
            btts += 1

    if played > 0:

        avg_for = goals_for / played
        avg_against = goals_against / played

        over_1_5_pct = (
            over_1_5 / played
        ) * 100

        over_2_5_pct = (
            over_2_5 / played
        ) * 100

        btts_pct = (
            btts / played
        ) * 100

    else:

        avg_for = 0
        avg_against = 0
        over_1_5_pct = 0
        over_2_5_pct = 0
        btts_pct = 0

    return {
        "played": played,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "avg_for": avg_for,
        "avg_against": avg_against,
        "over_1_5": over_1_5_pct,
        "over_2_5": over_2_5_pct,
        "btts": btts_pct,
    }


# ==================================================
# ANALYZE
# ==================================================

async def analyze(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if len(context.args) < 3:

        await update.message.reply_text(
            "Use:\n\n"
            "/analyze Chelsea vs Arsenal"
        )

        return

    message = " ".join(context.args)

    parts = message.lower().split(" vs ")

    if len(parts) != 2:

        await update.message.reply_text(
            "❌ Use:\n\n"
            "/analyze Chelsea vs Arsenal"
        )

        return

    home_name = parts[0].strip()
    away_name = parts[1].strip()

    try:

        await update.message.reply_text(
            "🔎 Analyzing match...\n\n"
            f"⚽ {home_name.title()} vs "
            f"{away_name.title()}\n\n"
            "Collecting statistics..."
        )

        home_team, home_error = await find_team(
            home_name
        )

        away_team, away_error = await find_team(
            away_name
        )

        if home_error:

            await update.message.reply_text(
                f"❌ Home team error:\n{home_error}"
            )

            return

        if away_error:

            await update.message.reply_text(
                f"❌ Away team error:\n{away_error}"
            )

            return

        home_id = home_team.get("id")
        away_id = away_team.get("id")

        home_official = home_team.get(
            "name",
            home_name
        )

        away_official = away_team.get(
            "name",
            away_name
        )

        home_response = await api_get(
            "fixtures",
            {
                "team": home_id,
                "season": FIXTURE_SEASON
            }
        )

        away_response = await api_get(
            "fixtures",
            {
                "team": away_id,
                "season": FIXTURE_SEASON
            }
        )

        home_data = home_response.json()
        away_data = away_response.json()

        if home_data.get("errors"):

            await update.message.reply_text(
                f"❌ {home_data['errors']}"
            )

            return

        if away_data.get("errors"):

            await update.message.reply_text(
                f"❌ {away_data['errors']}"
            )

            return

        home_matches = home_data.get(
            "response",
            []
        )

        away_matches = away_data.get(
            "response",
            []
        )

        home_stats = calculate_goal_stats(
            home_matches,
            home_id
        )

        away_stats = calculate_goal_stats(
            away_matches,
            away_id
        )

        reply = (

            "⚽ GOALLOGIC AI ANALYSIS\n\n"

            f"🏟️ {home_official} vs "
            f"{away_official}\n\n"

            f"📊 DATA PERIOD\n"
            f"Season: {FIXTURE_SEASON}\n"
            f"Sample: Last 5 available fixtures\n\n"

            "━━━━━━━━━━━━━━━━━━\n"
            f"🏠 {home_official}\n"
            "━━━━━━━━━━━━━━━━━━\n"

            f"Games: {home_stats['played']}\n"
            f"✅ Wins: {home_stats['wins']}\n"
            f"🤝 Draws: {home_stats['draws']}\n"
            f"❌ Losses: {home_stats['losses']}\n\n"

            f"⚽ Goals scored: "
            f"{home_stats['goals_for']}\n"

            f"🥅 Goals conceded: "
            f"{home_stats['goals_against']}\n"

            f"📈 Avg scored: "
            f"{home_stats['avg_for']:.2f}\n"

            f"📉 Avg conceded: "
            f"{home_stats['avg_against']:.2f}\n\n"

            f"🔥 Over 1.5: "
            f"{home_stats['over_1_5']:.0f}%\n"

            f"🔥 Over 2.5: "
            f"{home_stats['over_2_5']:.0f}%\n"

            f"🎯 BTTS: "
            f"{home_stats['btts']:.0f}%\n\n"

            "━━━━━━━━━━━━━━━━━━\n"
            f"✈️ {away_official}\n"
            "━━━━━━━━━━━━━━━━━━\n"

            f"Games: {away_stats['played']}\n"
            f"✅ Wins: {away_stats['wins']}\n"
            f"🤝 Draws: {away_stats['draws']}\n"
            f"❌ Losses: {away_stats['losses']}\n\n"

            f"⚽ Goals scored: "
            f"{away_stats['goals_for']}\n"

            f"🥅 Goals conceded: "
            f"{away_stats['goals_against']}\n"

            f"📈 Avg scored: "
            f"{away_stats['avg_for']:.2f}\n"

            f"📉 Avg conceded: "
            f"{away_stats['avg_against']:.2f}\n\n"

            f"🔥 Over 1.5: "
            f"{away_stats['over_1_5']:.0f}%\n"

            f"🔥 Over 2.5: "
            f"{away_stats['over_2_5']:.0f}%\n"

            f"🎯 BTTS: "
            f"{away_stats['btts']:.0f}%\n\n"

            "━━━━━━━━━━━━━━━━━━\n"
            "📊 GOALLOGIC SUMMARY\n"
            "━━━━━━━━━━━━━━━━━━\n"

            f"⚽ Combined avg goals: "
            f"{home_stats['avg_for'] + away_stats['avg_for']:.2f}\n\n"

            "⚠️ LIMITATION\n"
            "These figures use historical 2024 "
            "fixtures available on the current "
            "API plan. They are not current 2026 "
            "statistics and should not be treated "
            "as guaranteed predictions.\n\n"

            "🔧 NEXT UPGRADE\n"
            "Shots • Home/Away • H2H • Corners • "
            "Cards • Betting-market analysis"
        )

        await update.message.reply_text(
            reply
        )

    except Exception as e:

        await update.message.reply_text(
            f"⚠️ Analysis error:\n\n{e}"
        )


# ==================================================
# NORMAL MESSAGES
# ==================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message.text.strip()

    if " vs " in message.lower():

        await update.message.reply_text(
            "⚽ Match received!\n\n"
            f"{message}\n\n"
            f"Use:\n/analyze {message}"
        )

    else:

        await update.message.reply_text(
            "⚽ GoalLogic AI received your message.\n\n"
            "Try:\n\n"
            "/team Chelsea\n"
            "/fixtures Chelsea\n"
            "/analyze Chelsea vs Arsenal\n"
            "/apitest"
        )


# ==================================================
# MAIN
# ==================================================

def main():

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not FOOTBALL_API_KEY:

        raise RuntimeError(
            "FOOTBALL_API_KEY is missing."
        )

    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

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
            api_test
        )
    )

    application.add_handler(
        CommandHandler(
            "team",
            team_search
        )
    )

    application.add_handler(
        CommandHandler(
            "fixtures",
            fixtures
        )
    )

    application.add_handler(
        CommandHandler(
            "analyze",
            analyze
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print(
        f"GoalLogic AI is running "
        f"on port {PORT}."
    )

    application.run_polling()


if __name__ == "__main__":
    main()
