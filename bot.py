import os
import threading
import http.server
import statistics
import httpx

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ============================================================
# SETTINGS
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")

API_BASE = "https://v3.football.api-sports.io"

# Your current API plan supports these seasons
FIXTURE_SEASON = 2024

# Number of recent matches used for the analysis
SAMPLE_SIZE = 5


# ============================================================
# HEALTH SERVER FOR RENDER
# ============================================================

class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GoalLogic AI is running.")

    def log_message(self, format, *args):
        return


def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = http.server.HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


# ============================================================
# API HELPER
# ============================================================

async def api_get(endpoint, params=None):
    headers = {
        "x-apisports-key": FOOTBALL_API_KEY
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                API_BASE + endpoint,
                headers=headers,
                params=params or {}
            )

            if response.status_code != 200:
                return None

            data = response.json()

            if data.get("errors"):
                return None

            return data.get("response", [])

    except Exception:
        return None


# ============================================================
# FIND TEAM
# ============================================================

async def find_team(team_name):
    results = await api_get(
        "/teams",
        {
            "search": team_name
        }
    )

    if not results:
        return None

    return results[0]


# ============================================================
# GET TEAM FIXTURES
# ============================================================

async def get_team_fixtures(team_id, season=FIXTURE_SEASON):
    results = await api_get(
        "/fixtures",
        {
            "team": team_id,
            "season": season
        }
    )

    return results or []


# ============================================================
# BASIC MATCH STATS
# ============================================================

def calculate_stats(matches, team_id):
    if not matches:
        return {
            "games": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "avg_goals": 0,
            "avg_conceded": 0,
            "over_1_5": 0,
            "over_2_5": 0,
            "btts": 0,
            "scored": 0
        }

    wins = 0
    draws = 0
    losses = 0

    goals_for = []
    goals_against = []

    over_1_5_count = 0
    over_2_5_count = 0
    btts_count = 0
    scored_count = 0

    for match in matches:

        home_id = match["teams"]["home"]["id"]
        away_id = match["teams"]["away"]["id"]

        home_goals = match["goals"]["home"]
        away_goals = match["goals"]["away"]

        if home_goals is None:
            home_goals = 0

        if away_goals is None:
            away_goals = 0

        if team_id == home_id:
            gf = home_goals
            ga = away_goals
        else:
            gf = away_goals
            ga = home_goals

        goals_for.append(gf)
        goals_against.append(ga)

        if gf > ga:
            wins += 1
        elif gf == ga:
            draws += 1
        else:
            losses += 1

        if gf >= 1:
            scored_count += 1

        total_goals = home_goals + away_goals

        if total_goals >= 2:
            over_1_5_count += 1

        if total_goals >= 3:
            over_2_5_count += 1

        if home_goals >= 1 and away_goals >= 1:
            btts_count += 1

    games = len(matches)

    return {
        "games": games,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "avg_goals": round(statistics.mean(goals_for), 2),
        "avg_conceded": round(statistics.mean(goals_against), 2),
        "over_1_5": round((over_1_5_count / games) * 100),
        "over_2_5": round((over_2_5_count / games) * 100),
        "btts": round((btts_count / games) * 100),
        "scored": round((scored_count / games) * 100)
    }


# ============================================================
# HOME / AWAY FILTER
# ============================================================

def get_home_matches(matches, team_id):
    result = []

    for match in matches:
        if match["teams"]["home"]["id"] == team_id:
            result.append(match)

    return result


def get_away_matches(matches, team_id):
    result = []

    for match in matches:
        if match["teams"]["away"]["id"] == team_id:
            result.append(match)

    return result


# ============================================================
# MATCH STATISTICS
# ============================================================

async def collect_team_match_stats(matches, team_id):
    shots = []
    shots_on_target = []
    corners = []
    cards = []

    for match in matches:

        fixture_id = match["fixture"]["id"]

        stats = await api_get(
            "/fixtures/statistics",
            {
                "fixture": fixture_id
            }
        )

        if not stats:
            continue

        team_stats = None

        for item in stats:
            if item.get("team", {}).get("id") == team_id:
                team_stats = item
                break

        if not team_stats:
            continue

        values = {}

        for stat in team_stats.get("statistics", []):
            values[stat.get("type")] = stat.get("value")

        shot_value = values.get("Total Shots")
        target_value = values.get("Shots on Goal")
        corner_value = values.get("Corner Kicks")
        card_value = values.get("Yellow Cards")

        if isinstance(shot_value, int):
            shots.append(shot_value)

        if isinstance(target_value, int):
            shots_on_target.append(target_value)

        if isinstance(corner_value, int):
            corners.append(corner_value)

        if isinstance(card_value, int):
            cards.append(card_value)

    return {
        "shots": shots,
        "shots_on_target": shots_on_target,
        "corners": corners,
        "cards": cards
    }


def average(values):
    if not values:
        return 0

    return round(statistics.mean(values), 2)


# ============================================================
# H2H
# ============================================================

async def get_h2h(home_id, away_id):
    results = await api_get(
        "/fixtures/headtohead",
        {
            "h2h": f"{home_id}-{away_id}"
        }
    )

    if not results:
        return []

    return results[:5]


# ============================================================
# MARKET ANALYSIS
# ============================================================

def calculate_market_analysis(
    home_name,
    away_name,
    home_home_stats,
    away_away_stats
):
    # These are historical hit rates, NOT predictions.

    over_1_5 = round(
        (
            home_home_stats["over_1_5"]
            + away_away_stats["over_1_5"]
        ) / 2
    )

    over_2_5 = round(
        (
            home_home_stats["over_2_5"]
            + away_away_stats["over_2_5"]
        ) / 2
    )

    btts = round(
        (
            home_home_stats["btts"]
            + away_away_stats["btts"]
        ) / 2
    )

    home_to_score = home_home_stats["scored"]
    away_to_score = away_away_stats["scored"]

    return {
        "over_1_5": over_1_5,
        "over_2_5": over_2_5,
        "btts": btts,
        "home_to_score": home_to_score,
        "away_to_score": away_to_score
    }


def market_label(rate):
    if rate >= 80:
        return "VERY STRONG"
    elif rate >= 70:
        return "STRONG"
    elif rate >= 60:
        return "MODERATE"
    elif rate >= 50:
        return "MIXED"
    else:
        return "WEAK"


# ============================================================
# ANALYZE MATCH
# ============================================================

async def analyze_match(home_name, away_name):

    home_team = await find_team(home_name)
    away_team = await find_team(away_name)

    if not home_team or not away_team:
        return (
            "❌ I couldn't find one or both teams.\n\n"
            "Try using the official team names."
        )

    home_id = home_team["team"]["id"]
    away_id = away_team["team"]["id"]

    home_official = home_team["team"]["name"]
    away_official = away_team["team"]["name"]

    home_fixtures = await get_team_fixtures(home_id)
    away_fixtures = await get_team_fixtures(away_id)

    if not home_fixtures or not away_fixtures:
        return (
            "⚠️ Football data could not be retrieved.\n\n"
            "The current API plan only provides historical "
            "season data."
        )

    # Sort newest first
    home_fixtures = sorted(
        home_fixtures,
        key=lambda x: x["fixture"]["timestamp"],
        reverse=True
    )

    away_fixtures = sorted(
        away_fixtures,
        key=lambda x: x["fixture"]["timestamp"],
        reverse=True
    )

    home_recent = home_fixtures[:SAMPLE_SIZE]
    away_recent = away_fixtures[:SAMPLE_SIZE]

    # Home / away samples
    home_home_matches = get_home_matches(
        home_fixtures,
        home_id
    )[:SAMPLE_SIZE]

    away_away_matches = get_away_matches(
        away_fixtures,
        away_id
    )[:SAMPLE_SIZE]

    home_form = calculate_stats(
        home_recent,
        home_id
    )

    away_form = calculate_stats(
        away_recent,
        away_id
    )

    home_home_stats = calculate_stats(
        home_home_matches,
        home_id
    )

    away_away_stats = calculate_stats(
        away_away_matches,
        away_id
    )

    # Match statistics
    home_match_stats = await collect_team_match_stats(
        home_home_matches,
        home_id
    )

    away_match_stats = await collect_team_match_stats(
        away_away_matches,
        away_id
    )

    # H2H
    h2h = await get_h2h(home_id, away_id)

    # Market analysis
    markets = calculate_market_analysis(
        home_official,
        away_official,
        home_home_stats,
        away_away_stats
    )

    # ========================================================
    # BUILD RESPONSE
    # ========================================================

    response = []

    response.append("⚽ GOALLOGIC AI ANALYSIS")
    response.append("")
    response.append(
        f"🏟️ {home_official} vs {away_official}"
    )

    response.append("")
    response.append("📊 DATA PERIOD")
    response.append("━━━━━━━━━━━━━━━━━━")
    response.append(f"Season: {FIXTURE_SEASON}")
    response.append(
        f"Sample: Last {SAMPLE_SIZE} available matches"
    )

    # --------------------------------------------------------
    # RECENT FORM
    # --------------------------------------------------------

    response.append("")
    response.append("📈 RECENT FORM")
    response.append("━━━━━━━━━━━━━━━━━━")

    response.append(f"🏠 {home_official}")
    response.append(
        f"✅ Wins: {home_form['wins']}"
    )
    response.append(
        f"🤝 Draws: {home_form['draws']}"
    )
    response.append(
        f"❌ Losses: {home_form['losses']}"
    )
    response.append(
        f"⚽ Avg goals: {home_form['avg_goals']}"
    )
    response.append(
        f"🥅 Avg conceded: {home_form['avg_conceded']}"
    )
    response.append(
        f"🔥 Over 2.5: {home_form['over_2_5']}%"
    )
    response.append(
        f"🎯 BTTS: {home_form['btts']}%"
    )

    response.append("")
    response.append(f"✈️ {away_official}")
    response.append(
        f"✅ Wins: {away_form['wins']}"
    )
    response.append(
        f"🤝 Draws: {away_form['draws']}"
    )
    response.append(
        f"❌ Losses: {away_form['losses']}"
    )
    response.append(
        f"⚽ Avg goals: {away_form['avg_goals']}"
    )
    response.append(
        f"🥅 Avg conceded: {away_form['avg_conceded']}"
    )
    response.append(
        f"🔥 Over 2.5: {away_form['over_2_5']}%"
    )
    response.append(
        f"🎯 BTTS: {away_form['btts']}%"
    )

    # --------------------------------------------------------
    # HOME / AWAY
    # --------------------------------------------------------

    response.append("")
    response.append("🏠 HOME / AWAY")
    response.append("━━━━━━━━━━━━━━━━━━")

    response.append(
        f"🏠 {home_official} HOME"
    )
    response.append(
        f"Games: {home_home_stats['games']}"
    )
    response.append(
        f"⚽ Avg scored: {home_home_stats['avg_goals']}"
    )
    response.append(
        f"🥅 Avg conceded: {home_home_stats['avg_conceded']}"
    )
    response.append(
        f"🔥 Over 2.5: {home_home_stats['over_2_5']}%"
    )
    response.append(
        f"🎯 BTTS: {home_home_stats['btts']}%"
    )
    response.append(
        f"⚽ Scored in match: {home_home_stats['scored']}%"
    )

    response.append("")
    response.append(
        f"✈️ {away_official} AWAY"
    )
    response.append(
        f"Games: {away_away_stats['games']}"
    )
    response.append(
        f"⚽ Avg scored: {away_away_stats['avg_goals']}"
    )
    response.append(
        f"🥅 Avg conceded: {away_away_stats['avg_conceded']}"
    )
    response.append(
        f"🔥 Over 2.5: {away_away_stats['over_2_5']}%"
    )
    response.append(
        f"🎯 BTTS: {away_away_stats['btts']}%"
    )
    response.append(
        f"⚽ Scored in match: {away_away_stats['scored']}%"
    )

    # --------------------------------------------------------
    # MATCH STATISTICS
    # --------------------------------------------------------

    response.append("")
    response.append("🎯 MATCH STATISTICS")
    response.append("━━━━━━━━━━━━━━━━━━")

    response.append(f"🏠 {home_official}")
    response.append(
        f"🎯 Shots: {average(home_match_stats['shots'])}"
    )
    response.append(
        f"🎯 Shots on target: "
        f"{average(home_match_stats['shots_on_target'])}"
    )
    response.append(
        f"🚩 Corners: "
        f"{average(home_match_stats['corners'])}"
    )
    response.append(
        f"🟨 Yellow cards: "
        f"{average(home_match_stats['cards'])}"
    )

    response.append("")
    response.append(f"✈️ {away_official}")
    response.append(
        f"🎯 Shots: {average(away_match_stats['shots'])}"
    )
    response.append(
        f"🎯 Shots on target: "
        f"{average(away_match_stats['shots_on_target'])}"
    )
    response.append(
        f"🚩 Corners: "
        f"{average(away_match_stats['corners'])}"
    )
    response.append(
        f"🟨 Yellow cards: "
        f"{average(away_match_stats['cards'])}"
    )

    # --------------------------------------------------------
    # H2H
    # --------------------------------------------------------

    response.append("")
    response.append("🤝 HEAD-TO-HEAD")
    response.append("━━━━━━━━━━━━━━━━━━")

    if h2h:
        h2h_stats_home = calculate_stats(
            h2h,
            home_id
        )

        response.append(
            f"Meetings available: {len(h2h)}"
        )
        response.append(
            f"🔥 Over 2.5: {h2h_stats_home['over_2_5']}%"
        )
        response.append(
            f"🎯 BTTS: {h2h_stats_home['btts']}%"
        )
    else:
        response.append(
            "H2H data was not returned by the available API plan."
        )

    # --------------------------------------------------------
    # MARKET ANALYSIS
    # --------------------------------------------------------

    response.append("")
    response.append("📊 MARKET ANALYSIS")
    response.append("━━━━━━━━━━━━━━━━━━")

    response.append(
        f"⚽ Over 1.5 goals: "
        f"{markets['over_1_5']}% "
        f"({market_label(markets['over_1_5'])})"
    )

    response.append(
        f"🔥 Over 2.5 goals: "
        f"{markets['over_2_5']}% "
        f"({market_label(markets['over_2_5'])})"
    )

    response.append(
        f"🎯 BTTS: "
        f"{markets['btts']}% "
        f"({market_label(markets['btts'])})"
    )

    response.append(
        f"🏠 {home_official} to score: "
        f"{markets['home_to_score']}% "
        f"({market_label(markets['home_to_score'])})"
    )

    response.append(
        f"✈️ {away_official} to score: "
        f"{markets['away_to_score']}% "
        f"({market_label(markets['away_to_score'])})"
    )

    # --------------------------------------------------------
    # BEST HISTORICAL SIGNAL
    # --------------------------------------------------------

    candidates = {
        f"{home_official} to score":
            markets["home_to_score"],

        f"{away_official} to score":
            markets["away_to_score"],

        "Over 1.5 goals":
            markets["over_1_5"],

        "Over 2.5 goals":
            markets["over_2_5"],

        "BTTS":
            markets["btts"]
    }

    best_market = max(
        candidates,
        key=candidates.get
    )

    best_rate = candidates[best_market]

    response.append("")
    response.append("🤖 GOALLOGIC AI SIGNAL")
    response.append("━━━━━━━━━━━━━━━━━━")

    response.append(
        f"📌 Highest historical support: {best_market}"
    )

    response.append(
        f"📈 Historical hit rate: {best_rate}%"
    )

    response.append(
        f"📊 Evidence level: {market_label(best_rate)}"
    )

    response.append("")
    response.append("💡 INTERPRETATION")

    if best_rate >= 70:
        response.append(
            "This market has strong historical support "
            "in the selected sample."
        )
    elif best_rate >= 60:
        response.append(
            "This market has moderate historical support "
            "in the selected sample."
        )
    else:
        response.append(
            "The historical evidence is mixed or weak."
        )

    response.append("")
    response.append("⚠️ DATA NOTICE")
    response.append("━━━━━━━━━━━━━━━━━━")

    response.append(
        "These percentages are historical hit rates, "
        "not guaranteed probabilities of the next match."
    )

    response.append(
        f"The analysis uses {FIXTURE_SEASON} data because "
        "the current API plan does not provide the current "
        "2026 fixture season."
    )

    return "\n".join(response)


# ============================================================
# /START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = (
        "⚽ Welcome to GOALLOGIC AI\n\n"
        "Your football statistics analysis assistant.\n\n"
        "Commands:\n"
        "/analyze Chelsea vs Arsenal\n"
        "/team Chelsea\n"
        "/fixtures Chelsea\n"
        "/apitest\n\n"
        "Send a match using:\n"
        "Team A vs Team B"
    )

    await update.message.reply_text(message)


# ============================================================
# /APITEST
# ============================================================

async def api_test(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not FOOTBALL_API_KEY:
        await update.message.reply_text(
            "❌ FOOTBALL_API_KEY is missing."
        )
        return

    result = await api_get(
        "/status"
    )

    if result is not None:
        await update.message.reply_text(
            "✅ Football API connection is working."
        )
    else:
        await update.message.reply_text(
            "❌ Football API request failed."
        )


# ============================================================
# /TEAM
# ============================================================

async def team_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        await update.message.reply_text(
            "Use:\n/team Chelsea"
        )
        return

    name = " ".join(context.args)

    team = await find_team(name)

    if not team:
        await update.message.reply_text(
            "❌ Team not found."
        )
        return

    info = team["team"]

    response = (
        "⚽ TEAM FOUND\n\n"
        f"🏟️ {info['name']}\n"
        f"🆔 ID: {info['id']}"
    )

    await update.message.reply_text(response)


# ============================================================
# /FIXTURES
# ============================================================

async def fixtures_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:
        await update.message.reply_text(
            "Use:\n/fixtures Chelsea"
        )
        return

    name = " ".join(context.args)

    team = await find_team(name)

    if not team:
        await update.message.reply_text(
            "❌ Team not found."
        )
        return

    team_id = team["team"]["id"]
    official_name = team["team"]["name"]

    fixtures = await get_team_fixtures(
        team_id
    )

    if not fixtures:
        await update.message.reply_text(
            "❌ No fixtures found."
        )
        return

    fixtures = sorted(
        fixtures,
        key=lambda x: x["fixture"]["timestamp"],
        reverse=True
    )[:5]

    response = [
        f"📅 {official_name}",
        f"Season: {FIXTURE_SEASON}",
        ""
    ]

    for match in fixtures:

        home = match["teams"]["home"]["name"]
        away = match["teams"]["away"]["name"]

        home_goals = match["goals"]["home"]
        away_goals = match["goals"]["away"]

        if home_goals is None:
            home_goals = "-"
        if away_goals is None:
            away_goals = "-"

        response.append(
            f"⚽ {home} {home_goals}-{away_goals} {away}"
        )

    await update.message.reply_text(
        "\n".join(response)
    )


# ============================================================
# /ANALYZE
# ============================================================

async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:
        await update.message.reply_text(
            "Use:\n/analyze Chelsea vs Arsenal"
        )
        return

    text = " ".join(context.args)

    if " vs " not in text.lower():
        await update.message.reply_text(
            "Please use this format:\n"
            "/analyze Chelsea vs Arsenal"
        )
        return

    parts = text.lower().split(" vs ", 1)

    home_name = parts[0].strip()
    away_name = parts[1].strip()

    if not home_name or not away_name:
        await update.message.reply_text(
            "Please enter both teams."
        )
        return

    await update.message.reply_text(
        "🔎 Analyzing historical data...\n"
        "Please wait."
    )

    result = await analyze_match(
        home_name,
        away_name
    )

    await update.message.reply_text(
        result
    )


# ============================================================
# NORMAL TEXT MESSAGES
# ============================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    if " vs " in text.lower():

        parts = text.lower().split(
            " vs ",
            1
        )

        home_name = parts[0].strip()
        away_name = parts[1].strip()

        await update.message.reply_text(
            "🔎 Analyzing historical data...\n"
            "Please wait."
        )

        result = await analyze_match(
            home_name,
            away_name
        )

        await update.message.reply_text(
            result
        )

    else:

        await update.message.reply_text(
            "⚽ Send a match like:\n\n"
            "Chelsea vs Arsenal\n\n"
            "or use:\n"
            "/analyze Chelsea vs Arsenal"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN is missing.")
        return

    if not FOOTBALL_API_KEY:
        print("❌ FOOTBALL_API_KEY is missing.")
        return

    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

    print("GoalLogic AI is running.")

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
        CommandHandler("team", team_command)
    )

    application.add_handler(
        CommandHandler("fixtures", fixtures_command)
    )

    application.add_handler(
        CommandHandler("analyze", analyze_command)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
