import os
import threading
import http.server
import statistics
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
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")

API_BASE = "https://v3.football.api-sports.io"

FIXTURE_SEASON = 2024
SAMPLE_SIZE = 5


# =========================================================
# HEALTH SERVER FOR RENDER
# =========================================================

class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"GoalLogic AI is running.")

    def log_message(self, format, *args):
        return


def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = http.server.HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"GoalLogic AI is running on port {port}.")
    server.serve_forever()


threading.Thread(target=run_health_server, daemon=True).start()


# =========================================================
# API REQUEST
# =========================================================

async def api_get(endpoint, params=None):
    if not FOOTBALL_API_KEY:
        return None

    headers = {
        "x-apisports-key": FOOTBALL_API_KEY
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{API_BASE}/{endpoint}",
                headers=headers,
                params=params or {}
            )

            print("API STATUS:", response.status_code)

            if response.status_code != 200:
                print("API RESPONSE:", response.text)
                return None

            data = response.json()

            if data.get("errors"):
                print("API ERRORS:", data["errors"])
                return None

            return data

    except Exception as e:
        print("API ERROR:", e)
        return None


# =========================================================
# FIND TEAM
# =========================================================

async def find_team(team_name):
    data = await api_get(
        "teams",
        {
            "search": team_name
        }
    )

    if not data or not data.get("response"):
        return None

    return data["response"][0]


# =========================================================
# GET TEAM FIXTURES
# =========================================================

async def get_team_fixtures(team_id):
    data = await api_get(
        "fixtures",
        {
            "team": team_id,
            "season": FIXTURE_SEASON
        }
    )

    if not data:
        return []

    return data.get("response", [])


# =========================================================
# BASIC MATCH STATISTICS
# =========================================================

def calculate_stats(matches, team_id):

    matches = matches[:SAMPLE_SIZE]

    if not matches:
        return {
            "games": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goals_for": [],
            "goals_against": [],
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

        home_goals = match["goals"]["home"] or 0
        away_goals = match["goals"]["away"] or 0

        if team_id == home_id:

            gf = home_goals
            ga = away_goals

            if gf > ga:
                wins += 1
            elif gf == ga:
                draws += 1
            else:
                losses += 1

        else:

            gf = away_goals
            ga = home_goals

            if gf > ga:
                wins += 1
            elif gf == ga:
                draws += 1
            else:
                losses += 1

        goals_for.append(gf)
        goals_against.append(ga)

        total_goals = gf + ga

        if total_goals >= 2:
            over_1_5_count += 1

        if total_goals >= 3:
            over_2_5_count += 1

        if gf > 0 and ga > 0:
            btts_count += 1

        if gf > 0:
            scored_count += 1

    games = len(matches)

    return {
        "games": games,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "avg_goals": round(statistics.mean(goals_for), 2),
        "avg_conceded": round(statistics.mean(goals_against), 2),
        "over_1_5": round((over_1_5_count / games) * 100),
        "over_2_5": round((over_2_5_count / games) * 100),
        "btts": round((btts_count / games) * 100),
        "scored": round((scored_count / games) * 100)
    }


# =========================================================
# HOME / AWAY FILTER
# =========================================================

def filter_home_matches(matches, team_id):
    return [
        m for m in matches
        if m["teams"]["home"]["id"] == team_id
    ]


def filter_away_matches(matches, team_id):
    return [
        m for m in matches
        if m["teams"]["away"]["id"] == team_id
    ]


# =========================================================
# MATCH STATISTICS
# =========================================================

async def collect_team_match_stats(matches, team_id):

    shots = []
    shots_on_target = []
    corners = []
    yellow_cards = []

    for match in matches[:SAMPLE_SIZE]:

        fixture_id = match["fixture"]["id"]

        data = await api_get(
            "fixtures/statistics",
            {
                "fixture": fixture_id
            }
        )

        if not data or not data.get("response"):
            continue

        for team_data in data["response"]:

            if team_data["team"]["id"] != team_id:
                continue

            statistics_list = team_data.get("statistics", [])

            for stat in statistics_list:

                name = stat.get("type")
                value = stat.get("value")

                if value is None:
                    continue

                try:
                    if isinstance(value, str):
                        value = value.replace("%", "")
                        value = float(value)
                    else:
                        value = float(value)
                except:
                    continue

                if name == "Total Shots":
                    shots.append(value)

                elif name == "Shots on Goal":
                    shots_on_target.append(value)

                elif name == "Corner Kicks":
                    corners.append(value)

                elif name == "Yellow Cards":
                    yellow_cards.append(value)

    return {
        "shots": round(statistics.mean(shots), 2) if shots else 0,
        "shots_on_target": round(statistics.mean(shots_on_target), 2)
        if shots_on_target else 0,
        "corners": round(statistics.mean(corners), 2)
        if corners else 0,
        "yellow_cards": round(statistics.mean(yellow_cards), 2)
        if yellow_cards else 0
    }


# =========================================================
# EVIDENCE QUALITY
# =========================================================

def evidence_quality(rate, sample_size):

    if sample_size <= 2:
        return "VERY LIMITED SAMPLE"

    if sample_size == 3:
        if rate >= 80:
            return "LIMITED — HIGH RATE"
        if rate >= 60:
            return "LIMITED"
        return "LIMITED — LOW RATE"

    if sample_size == 4:
        if rate >= 80:
            return "MODERATE — HIGH RATE"
        if rate >= 60:
            return "MODERATE"
        return "MODERATE — LOW RATE"

    if sample_size >= 5:
        if rate >= 80:
            return "GOOD HISTORICAL SUPPORT"
        if rate >= 60:
            return "MODERATE HISTORICAL SUPPORT"
        return "LOW HISTORICAL SUPPORT"

    return "LIMITED"


# =========================================================
# MARKET ANALYSIS
# =========================================================

def calculate_market_analysis(home_stats, away_stats):

    over_1_5 = round(
        (
            home_stats["over_1_5"]
            + away_stats["over_1_5"]
        ) / 2
    )

    over_2_5 = round(
        (
            home_stats["over_2_5"]
            + away_stats["over_2_5"]
        ) / 2
    )

    btts = round(
        (
            home_stats["btts"]
            + away_stats["btts"]
        ) / 2
    )

    home_to_score = home_stats["scored"]
    away_to_score = away_stats["scored"]

    return {
        "over_1_5": over_1_5,
        "over_2_5": over_2_5,
        "btts": btts,
        "home_to_score": home_to_score,
        "away_to_score": away_to_score
    }


def market_label(rate):

    if rate >= 80:
        return "STRONG"

    if rate >= 60:
        return "MODERATE"

    return "WEAK"


# =========================================================
# MAIN ANALYSIS
# =========================================================

async def analyze_match(home_name, away_name):

    home = await find_team(home_name)
    away = await find_team(away_name)

    if not home:
        return f"❌ I couldn't find {home_name}."

    if not away:
        return f"❌ I couldn't find {away_name}."

    home_id = home["team"]["id"]
    away_id = away["team"]["id"]

    home_fixtures = await get_team_fixtures(home_id)
    away_fixtures = await get_team_fixtures(away_id)

    if not home_fixtures:
        return "⚠️ Football data could not be retrieved for the home team."

    if not away_fixtures:
        return "⚠️ Football data could not be retrieved for the away team."

    home_fixtures = sorted(
        home_fixtures,
        key=lambda x: x["fixture"]["date"],
        reverse=True
    )

    away_fixtures = sorted(
        away_fixtures,
        key=lambda x: x["fixture"]["date"],
        reverse=True
    )

    home_recent = home_fixtures[:SAMPLE_SIZE]
    away_recent = away_fixtures[:SAMPLE_SIZE]

    home_stats = calculate_stats(
        home_recent,
        home_id
    )

    away_stats = calculate_stats(
        away_recent,
        away_id
    )

    home_home = filter_home_matches(
        home_fixtures,
        home_id
    )[:SAMPLE_SIZE]

    away_away = filter_away_matches(
        away_fixtures,
        away_id
    )[:SAMPLE_SIZE]

    home_home_stats = calculate_stats(
        home_home,
        home_id
    )

    away_away_stats = calculate_stats(
        away_away,
        away_id
    )

    home_match_stats = await collect_team_match_stats(
        home_home,
        home_id
    )

    away_match_stats = await collect_team_match_stats(
        away_away,
        away_id
    )

    markets = calculate_market_analysis(
        home_home_stats,
        away_away_stats
    )

    # -----------------------------------------------------
    # Evidence labels
    # -----------------------------------------------------

    goal_sample = min(
        home_home_stats["games"],
        away_away_stats["games"]
    )

    over15_evidence = evidence_quality(
        markets["over_1_5"],
        goal_sample
    )

    over25_evidence = evidence_quality(
        markets["over_2_5"],
        goal_sample
    )

    btts_evidence = evidence_quality(
        markets["btts"],
        goal_sample
    )

    home_score_evidence = evidence_quality(
        markets["home_to_score"],
        home_home_stats["games"]
    )

    away_score_evidence = evidence_quality(
        markets["away_to_score"],
        away_away_stats["games"]
    )

    # -----------------------------------------------------
    # Response
    # -----------------------------------------------------

    response = []

    response.append("⚽ GOALLOGIC AI ANALYSIS")
    response.append("")
    response.append(
        f"🏟️ {home['team']['name']} vs {away['team']['name']}"
    )

    response.append("")
    response.append("📊 DATA PERIOD")
    response.append("━━━━━━━━━━━━━━━━━━")
    response.append(f"Season: {FIXTURE_SEASON}")
    response.append("Sample: Last 5 available")

    response.append("")
    response.append("━━━━━━━━━━━━━━━━━━")
    response.append("📈 RECENT FORM")
    response.append("━━━━━━━━━━━━━━━━━━")

    response.append("")
    response.append(f"🏠 {home['team']['name']}")
    response.append(f"✅ Wins: {home_stats['wins']}")
    response.append(f"🤝 Draws: {home_stats['draws']}")
    response.append(f"❌ Losses: {home_stats['losses']}")
    response.append(f"⚽ Avg goals: {home_stats['avg_goals']}")
    response.append(f"🥅 Avg conceded: {home_stats['avg_conceded']}")
    response.append(f"🔥 Over 2.5: {home_stats['over_2_5']}%")
    response.append(f"🎯 BTTS: {home_stats['btts']}%")

    response.append("")
    response.append(f"✈️ {away['team']['name']}")
    response.append(f"✅ Wins: {away_stats['wins']}")
    response.append(f"🤝 Draws: {away_stats['draws']}")
    response.append(f"❌ Losses: {away_stats['losses']}")
    response.append(f"⚽ Avg goals: {away_stats['avg_goals']}")
    response.append(f"🥅 Avg conceded: {away_stats['avg_conceded']}")
    response.append(f"🔥 Over 2.5: {away_stats['over_2_5']}%")
    response.append(f"🎯 BTTS: {away_stats['btts']}%")

    response.append("")
    response.append("━━━━━━━━━━━━━━━━━━")
    response.append("🏠 HOME / AWAY")
    response.append("━━━━━━━━━━━━━━━━━━")

    response.append("")
    response.append(f"🏠 {home['team']['name']} HOME")
    response.append(f"Games: {home_home_stats['games']}")
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

    response.append("")
    response.append(f"✈️ {away['team']['name']} AWAY")
    response.append(f"Games: {away_away_stats['games']}")
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

    response.append("")
    response.append("━━━━━━━━━━━━━━━━━━")
    response.append("🎯 MATCH STATISTICS")
    response.append("━━━━━━━━━━━━━━━━━━")

    response.append("")
    response.append(f"🏠 {home['team']['name']}")
    response.append(
        f"🎯 Shots: {home_match_stats['shots']}"
    )
    response.append(
        f"🎯 Shots on target: {home_match_stats['shots_on_target']}"
    )
    response.append(
        f"🚩 Corners: {home_match_stats['corners']}"
    )
    response.append(
        f"🟨 Yellow cards: {home_match_stats['yellow_cards']}"
    )

    response.append("")
    response.append(f"✈️ {away['team']['name']}")
    response.append(
        f"🎯 Shots: {away_match_stats['shots']}"
    )
    response.append(
        f"🎯 Shots on target: {away_match_stats['shots_on_target']}"
    )
    response.append(
        f"🚩 Corners: {away_match_stats['corners']}"
    )
    response.append(
        f"🟨 Yellow cards: {away_match_stats['yellow_cards']}"
    )

    response.append("")
    response.append("━━━━━━━━━━━━━━━━━━")
    response.append("🤝 HEAD-TO-HEAD")
    response.append("━━━━━━━━━━━━━━━━━━")
    response.append(
        "H2H data was not returned by the available API plan."
    )

    response.append("")
    response.append("━━━━━━━━━━━━━━━━━━")
    response.append("📊 MARKET ANALYSIS")
    response.append("━━━━━━━━━━━━━━━━━━")

    response.append("")
    response.append(
        f"⚽ Over 1.5 goals: {markets['over_1_5']}% "
        f"({market_label(markets['over_1_5'])})"
    )
    response.append(
        f"   Historical record: "
        f"{round(markets['over_1_5'] * goal_sample / 100)}"
        f"/{goal_sample}"
    )
    response.append(
        f"   Evidence: {over15_evidence}"
    )

    response.append("")
    response.append(
        f"🔥 Over 2.5 goals: {markets['over_2_5']}% "
        f"({market_label(markets['over_2_5'])})"
    )
    response.append(
        f"   Historical record: "
        f"{round(markets['over_2_5'] * goal_sample / 100)}"
        f"/{goal_sample}"
    )
    response.append(
        f"   Evidence: {over25_evidence}"
    )

    response.append("")
    response.append(
        f"🎯 BTTS: {markets['btts']}% "
        f"({market_label(markets['btts'])})"
    )
    response.append(
        f"   Historical record: "
        f"{round(markets['btts'] * goal_sample / 100)}"
        f"/{goal_sample}"
    )
    response.append(
        f"   Evidence: {btts_evidence}"
    )

    response.append("")
    response.append(
        f"🏠 {home['team']['name']} to score: "
        f"{markets['home_to_score']}%"
    )
    response.append(
        f"   Historical record: "
        f"{round(markets['home_to_score'] * home_home_stats['games'] / 100)}"
        f"/{home_home_stats['games']}"
    )
    response.append(
        f"   Evidence: {home_score_evidence}"
    )

    response.append("")
    response.append(
        f"✈️ {away['team']['name']} to score: "
        f"{markets['away_to_score']}%"
    )
    response.append(
        f"   Historical record: "
        f"{round(markets['away_to_score'] * away_away_stats['games'] / 100)}"
        f"/{away_away_stats['games']}"
    )
    response.append(
        f"   Evidence: {away_score_evidence}"
    )

    response.append("")
    response.append("━━━━━━━━━━━━━━━━━━")
    response.append("🤖 GOALLOGIC AI SIGNAL")
    response.append("━━━━━━━━━━━━━━━━━━")

    market_values = {
        f"{home['team']['name']} to score": (
            markets["home_to_score"],
            home_score_evidence
        ),
        f"{away['team']['name']} to score": (
            markets["away_to_score"],
            away_score_evidence
        ),
        "Over 1.5 goals": (
            markets["over_1_5"],
            over15_evidence
        ),
        "Over 2.5 goals": (
            markets["over_2_5"],
            over25_evidence
        ),
        "BTTS": (
            markets["btts"],
            btts_evidence
        )
    }

    best_market = max(
        market_values,
        key=lambda x: market_values[x][0]
    )

    best_rate = market_values[best_market][0]
    best_evidence = market_values[best_market][1]

    response.append("")
    response.append(
        f"📌 Highest historical hit rate: {best_market}"
    )
    response.append(
        f"📈 Historical hit rate: {best_rate}%"
    )
    response.append(
        f"📊 Evidence quality: {best_evidence}"
    )

    response.append("")
    response.append("💡 INTERPRETATION")

    if "LIMITED" in best_evidence:
        response.append(
            "This market has a high historical rate, "
            "but the sample is small. Treat the result cautiously."
        )
    elif "MODERATE" in best_evidence:
        response.append(
            "This market has moderate historical support "
            "in the selected sample."
        )
    else:
        response.append(
            "This market has stronger historical support "
            "in the selected sample."
        )

    response.append("")
    response.append("⚠️ DATA NOTICE")
    response.append("━━━━━━━━━━━━━━━━━━")
    response.append(
        "These percentages are historical hit rates, "
        "not guaranteed probabilities of the next match."
    )
    response.append(
        "The analysis uses 2024 data because the current "
        "API plan does not provide the current 2026 fixture season."
    )

    return "\n".join(response)


# =========================================================
# TELEGRAM COMMANDS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "⚽ Welcome to GoalLogic AI!\n\n"
        "I analyze football matches using historical statistics.\n\n"
        "Commands:\n"
        "/team Chelsea\n"
        "/fixtures Chelsea\n"
        "/analyze Chelsea vs Arsenal\n"
        "/apitest"
    )


async def apitest(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not FOOTBALL_API_KEY:
        await update.message.reply_text(
            "❌ FOOTBALL_API_KEY is missing."
        )
        return

    data = await api_get(
        "status"
    )

    if data:
        await update.message.reply_text(
            "✅ Football API connection is working."
        )
    else:
        await update.message.reply_text(
            "❌ Football API request failed."
        )


async def team_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        await update.message.reply_text(
            "Example:\n/team Chelsea"
        )
        return

    team_name = " ".join(context.args)

    team = await find_team(team_name)

    if not team:
        await update.message.reply_text(
            f"❌ I couldn't find {team_name}."
        )
        return

    await update.message.reply_text(
        f"⚽ {team['team']['name']}\n"
        f"ID: {team['team']['id']}\n"
        f"Country: {team['team'].get('country', 'Unknown')}"
    )


async def fixtures_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:
        await update.message.reply_text(
            "Example:\n/fixtures Chelsea"
        )
        return

    team_name = " ".join(context.args)

    team = await find_team(team_name)

    if not team:
        await update.message.reply_text(
            f"❌ I couldn't find {team_name}."
        )
        return

    fixtures = await get_team_fixtures(
        team["team"]["id"]
    )

    if not fixtures:
        await update.message.reply_text(
            "⚠️ No fixtures were found."
        )
        return

    fixtures = sorted(
        fixtures,
        key=lambda x: x["fixture"]["date"],
        reverse=True
    )

    lines = [
        f"📅 {team['team']['name']} fixtures",
        f"Season: {FIXTURE_SEASON}",
        ""
    ]

    for fixture in fixtures[:5]:

        home = fixture["teams"]["home"]["name"]
        away = fixture["teams"]["away"]["name"]

        date = fixture["fixture"]["date"][:10]

        lines.append(
            f"{date} — {home} vs {away}"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )


async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if len(context.args) < 3:
        await update.message.reply_text(
            "Example:\n/analyze Chelsea vs Arsenal"
        )
        return

    text = " ".join(context.args)

    if " vs " not in text.lower():
        await update.message.reply_text(
            "Please use:\n/analyze Chelsea vs Arsenal"
        )
        return

    parts = text.lower().split(" vs ", 1)

    home_name = parts[0].strip()
    away_name = parts[1].strip()

    await update.message.reply_text(
        "🔎 Analyzing match...\n"
        "Please wait."
    )

    result = await analyze_match(
        home_name,
        away_name
    )

    await update.message.reply_text(
        result
    )


# =========================================================
# NORMAL TEXT
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message.text

    if " vs " in message.lower():

        parts = message.lower().split(
            " vs ",
            1
        )

        home_name = parts[0].strip()
        away_name = parts[1].strip()

        await update.message.reply_text(
            "🔎 Analyzing match...\n"
            "Please wait."
        )

        result = await analyze_match(
            home_name,
            away_name
        )

        await update.message.reply_text(
            result
        )

        return

    await update.message.reply_text(
        "⚽ Send a match like:\n\n"
        "Chelsea vs Arsenal"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN is missing.")
        return

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
            text_handler
        )
    )

    print("GoalLogic AI is running.")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
