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

# Your current free API plan allows seasons 2022-2024.
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
# FOOTBALL API REQUEST
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
        "/apitest\n\n"

        "You can also send:\n"
        "Chelsea vs Arsenal"
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

            f"HTTP Status: "
            f"{response.status_code}\n\n"

            f"Response:\n"
            f"{response.text[:2500]}"
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ API test failed:\n{e}"
        )


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
                f"❌ API error:\n"
                f"{data['errors']}"
            )

            return

        teams = data.get(
            "response",
            []
        )

        if not teams:

            await update.message.reply_text(
                f"❌ No team found for "
                f"{team_name}"
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

            name = team.get(
                "name",
                "Unknown"
            )

            team_id = team.get(
                "id",
                "Unknown"
            )

            country = team.get(
                "country",
                "Unknown"
            )

            reply += (
                f"⚽ {name}\n"
                f"ID: {team_id}\n"
                f"Country: {country}\n\n"
            )

        await update.message.reply_text(reply)

    except Exception as e:

        await update.message.reply_text(
            f"⚠️ Error searching team:\n{e}"
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

        team, error = await find_team(
            team_name
        )

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

        fixture_response = await api_get(
            "fixtures",
            {
                "team": team_id,
                "season": FIXTURE_SEASON
            }
        )

        fixture_data = fixture_response.json()

        if fixture_data.get("errors"):

            await update.message.reply_text(

                "❌ Fixture API error:\n\n"

                f"{fixture_data['errors']}\n\n"

                f"Team: {official_name}\n"
                f"Season: {FIXTURE_SEASON}"
            )

            return

        matches = fixture_data.get(
            "response",
            []
        )

        if not matches:

            await update.message.reply_text(

                "ℹ️ No fixtures returned.\n\n"

                f"Team: {official_name}\n"
                f"Season: {FIXTURE_SEASON}"
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

            league_name = league.get(
                "name",
                "Unknown competition"
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
                f"🏆 {league_name}\n\n"
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
# ANALYZE MATCH
# ==================================================

async def analyze(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if len(context.args) < 3:

        await update.message.reply_text(

            "Use this format:\n\n"
            "/analyze Chelsea vs Arsenal"
        )

        return

    message = " ".join(context.args)

    parts = message.lower().split(" vs ")

    if len(parts) != 2:

        await update.message.reply_text(

            "❌ Please use this format:\n\n"
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
            "Please wait..."
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

        # Get historical fixtures for both teams

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

        home_matches = home_data.get(
            "response",
            []
        )

        away_matches = away_data.get(
            "response",
            []
        )

        # Recent results

        home_recent = home_matches[-5:]
        away_recent = away_matches[-5:]

        home_wins = 0
        home_draws = 0
        home_losses = 0

        for match in home_recent:

            teams_info = match.get(
                "teams",
                {}
            )

            score = match.get(
                "goals",
                {}
            )

            home_score = score.get(
                "home"
            )

            away_score = score.get(
                "away"
            )

            if home_score is None or away_score is None:
                continue

            team_is_home = (
                teams_info.get(
                    "home",
                    {}
                ).get("id") == home_id
            )

            if team_is_home:

                if home_score > away_score:
                    home_wins += 1

                elif home_score == away_score:
                    home_draws += 1

                else:
                    home_losses += 1

            else:

                if away_score > home_score:
                    home_wins += 1

                elif away_score == home_score:
                    home_draws += 1

                else:
                    home_losses += 1

        away_wins = 0
        away_draws = 0
        away_losses = 0

        for match in away_recent:

            teams_info = match.get(
                "teams",
                {}
            )

            score = match.get(
                "goals",
                {}
            )

            home_score = score.get(
                "home"
            )

            away_score = score.get(
                "away"
            )

            if home_score is None or away_score is None:
                continue

            team_is_home = (
                teams_info.get(
                    "home",
                    {}
                ).get("id") == away_id
            )

            if team_is_home:

                if home_score > away_score:
                    away_wins += 1

                elif home_score == away_score:
                    away_draws += 1

                else:
                    away_losses += 1

            else:

                if away_score > home_score:
                    away_wins += 1

                elif away_score == home_score:
                    away_draws += 1

                else:
                    away_losses += 1

        reply = (

            "⚽ GOALLOGIC AI ANALYSIS\n\n"

            f"🏟️ {home_official} vs "
            f"{away_official}\n\n"

            f"📊 DATA PERIOD\n"
            f"Season: {FIXTURE_SEASON}\n\n"

            f"🏠 {home_official} - Recent 5\n"
            f"✅ Wins: {home_wins}\n"
            f"🤝 Draws: {home_draws}\n"
            f"❌ Losses: {home_losses}\n\n"

            f"✈️ {away_official} - Recent 5\n"
            f"✅ Wins: {away_wins}\n"
            f"🤝 Draws: {away_draws}\n"
            f"❌ Losses: {away_losses}\n\n"

            "📈 INITIAL ASSESSMENT\n"
            "The statistics above are based on "
            "historical 2024 fixtures available "
            "through your current API plan.\n\n"

            "⚠️ IMPORTANT\n"
            "This is statistical analysis, not a "
            "guaranteed prediction. Current 2026 "
            "data is not available through the "
            "current free API plan.\n\n"

            "🔧 NEXT STAGE\n"
            "We will add goals, shots, home/away "
            "records, head-to-head and betting "
            "market analysis."
        )

        await update.message.reply_text(
            reply
        )

    except Exception as e:

        await update.message.reply_text(

            "⚠️ Analysis error:\n\n"
            f"{e}"
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

            "Use:\n"
            f"/analyze {message}"
        )

    else:

        await update.message.reply_text(

            "⚽ GoalLogic AI received "
            "your message.\n\n"

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
