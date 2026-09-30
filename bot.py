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

# Your free API plan currently allows seasons 2022-2024.
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
# START COMMAND
# ==================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "⚽ GoalLogic AI is online!\n\n"

        "Available commands:\n\n"

        "/team Chelsea\n"
        "/fixtures Chelsea\n"
        "/apitest\n\n"

        "Example:\n"
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

        response = await api_get(
            "status"
        )

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

    team_name = " ".join(
        context.args
    )

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

        await update.message.reply_text(
            reply
        )

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

    team_name = " ".join(
        context.args
    )

    try:

        # ------------------------------------------
        # STEP 1: FIND TEAM
        # ------------------------------------------

        team_response = await api_get(
            "teams",
            {
                "search": team_name
            }
        )

        team_data = team_response.json()

        if team_data.get("errors"):

            await update.message.reply_text(
                "❌ Team search error:\n"
                f"{team_data['errors']}"
            )

            return

        teams = team_data.get(
            "response",
            []
        )

        if not teams:

            await update.message.reply_text(
                f"❌ Team not found:\n"
                f"{team_name}"
            )

            return

        # ------------------------------------------
        # STEP 2: FIND EXACT TEAM
        # ------------------------------------------

        selected_team = None

        for item in teams:

            name = item.get(
                "team",
                {}
            ).get(
                "name",
                ""
            )

            if name.lower() == team_name.lower():

                selected_team = item

                break

        if selected_team is None:

            selected_team = teams[0]

        team = selected_team.get(
            "team",
            {}
        )

        team_id = team.get(
            "id"
        )

        official_name = team.get(
            "name",
            team_name
        )

        # ------------------------------------------
        # STEP 3: GET FIXTURES
        #
        # IMPORTANT:
        # No "next" parameter.
        # Season 2024 is used because the
        # current API plan allows 2022-2024.
        # ------------------------------------------

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
                f"Team ID: {team_id}\n"
                f"Season: {FIXTURE_SEASON}"
            )

            return

        matches = fixture_data.get(
            "response",
            []
        )

        # ------------------------------------------
        # STEP 4: NO FIXTURES
        # ------------------------------------------

        if not matches:

            await update.message.reply_text(

                "ℹ️ No fixtures were returned.\n\n"

                f"Team: {official_name}\n"
                f"Team ID: {team_id}\n"
                f"Season: {FIXTURE_SEASON}\n\n"

                "Your current API plan only provides "
                "fixture seasons 2022-2024."
            )

            return

        # ------------------------------------------
        # STEP 5: SHOW FIXTURES
        # ------------------------------------------

        reply = (

            f"📅 Fixtures for {official_name}\n"
            f"🗓️ Season {FIXTURE_SEASON}\n\n"
        )

        # Show up to 15 fixtures

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
            f"Total returned by API: "
            f"{len(matches)}"
        )

        await update.message.reply_text(
            reply
        )

    except Exception as e:

        await update.message.reply_text(

            "⚠️ Error fetching fixtures:\n"
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

            "🔧 Match analysis engine "
            "will be connected next."
        )

    else:

        await update.message.reply_text(

            "⚽ GoalLogic AI received "
            "your message.\n\n"

            "Try:\n"

            "/team Chelsea\n"
            "/fixtures Chelsea\n"
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

    # Start Render health server

    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

    # Create Telegram application

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Commands

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

    # Normal messages

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


# ==================================================
# RUN BOT
# ==================================================

if __name__ == "__main__":
    main()
