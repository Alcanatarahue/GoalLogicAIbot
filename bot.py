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
# RENDER HEALTH SERVER
# =========================================================

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

    server = http.server.HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    server.serve_forever()


threading.Thread(
    target=start_health_server,
    daemon=True
).start()


# =========================================================
# API
# =========================================================

def api_get(endpoint, params=None):

    if not FOOTBALL_API_KEY:
        return None

    headers = {
        "x-apisports-key": FOOTBALL_API_KEY
    }

    try:

        response = httpx.get(
            API_BASE + endpoint,
            headers=headers,
            params=params,
            timeout=30
        )

        if response.status_code != 200:
            print("API ERROR:", response.status_code)
            print(response.text)
            return None

        data = response.json()

        if data.get("errors"):
            print("API ERRORS:", data["errors"])
            return None

        return data

    except Exception as e:

        print("API EXCEPTION:", e)
        return None


# =========================================================
# FIND TEAM
# =========================================================

def find_team(team_name):

    data = api_get(
        "/teams",
        {
            "search": team_name
        }
    )

    if not data:
        return None

    teams = data.get("response", [])

    if not teams:
        return None

    return teams[0]


# =========================================================
# TEAM FIXTURES
# =========================================================

def get_team_fixtures(team_id):

    data = api_get(
        "/fixtures",
        {
            "team": team_id,
            "season": FIXTURE_SEASON
        }
    )

    if not data:
        return []

    return data.get("response", [])


# =========================================================
# BASIC STATS
# =========================================================

def calculate_stats(fixtures, team_id):

    wins = 0
    draws = 0
    losses = 0

    goals_for = 0
    goals_against = 0

    over_1_5 = 0
    over_2_5 = 0
    btts = 0
    scored = 0
    clean_sheets = 0

    valid_games = 0

    for fixture in fixtures:

        home_id = fixture["teams"]["home"]["id"]
        away_id = fixture["teams"]["away"]["id"]

        home_goals = fixture["goals"]["home"]
        away_goals = fixture["goals"]["away"]

        if home_goals is None or away_goals is None:
            continue

        valid_games += 1

        if team_id == home_id:
            gf = home_goals
            ga = away_goals
        else:
            gf = away_goals
            ga = home_goals

        if gf > ga:
            wins += 1
        elif gf == ga:
            draws += 1
        else:
            losses += 1

        goals_for += gf
        goals_against += ga

        total_goals = home_goals + away_goals

        if total_goals >= 2:
            over_1_5 += 1

        if total_goals >= 3:
            over_2_5 += 1

        if home_goals > 0 and away_goals > 0:
            btts += 1

        if gf > 0:
            scored += 1

        if ga == 0:
            clean_sheets += 1

    if valid_games == 0:

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
            "scored": 0,
            "clean_sheets": 0
        }

    return {
        "games": valid_games,
        "wins": wins,
        "draws": draws,
        "losses": losses,

        "avg_goals": round(
            goals_for / valid_games,
            2
        ),

        "avg_conceded": round(
            goals_against / valid_games,
            2
        ),

        "over_1_5": round(
            over_1_5 / valid_games * 100
        ),

        "over_2_5": round(
            over_2_5 / valid_games * 100
        ),

        "btts": round(
            btts / valid_games * 100
        ),

        "scored": round(
            scored / valid_games * 100
        ),

        "clean_sheets": round(
            clean_sheets / valid_games * 100
        )
    }


# =========================================================
# HOME / AWAY
# =========================================================

def get_home_fixtures(fixtures, team_id):

    return [
        fixture
        for fixture in fixtures
        if fixture["teams"]["home"]["id"] == team_id
    ]


def get_away_fixtures(fixtures, team_id):

    return [
        fixture
        for fixture in fixtures
        if fixture["teams"]["away"]["id"] == team_id
    ]


# =========================================================
# MATCH STATISTICS
# =========================================================

def collect_team_match_stats(fixtures, team_id):

    shots = []
    shots_on_target = []
    corners = []
    yellow_cards = []

    for fixture in fixtures:

        fixture_id = fixture["fixture"]["id"]

        data = api_get(
            "/fixtures/statistics",
            {
                "fixture": fixture_id
            }
        )

        if not data:
            continue

        responses = data.get("response", [])

        for team_data in responses:

            if team_data["team"]["id"] != team_id:
                continue

            stats = team_data.get("statistics", [])

            for item in stats:

                stat_type = item.get("type")
                value = item.get("value")

                if value is None:
                    continue

                if isinstance(value, str):
                    value = value.replace("%", "")

                try:
                    value = float(value)
                except:
                    continue

                if stat_type == "Total Shots":
                    shots.append(value)

                elif stat_type == "Shots on Goal":
                    shots_on_target.append(value)

                elif stat_type == "Corner Kicks":
                    corners.append(value)

                elif stat_type == "Yellow Cards":
                    yellow_cards.append(value)

    return {
        "shots": round(
            statistics.mean(shots), 1
        ) if shots else 0,

        "shots_on_target": round(
            statistics.mean(shots_on_target), 1
        ) if shots_on_target else 0,

        "corners": round(
            statistics.mean(corners), 1
        ) if corners else 0,

        "yellow_cards": round(
            statistics.mean(yellow_cards), 1
        ) if yellow_cards else 0
    }


# =========================================================
# EVIDENCE
# =========================================================

def evidence_quality(rate, sample_size):

    if sample_size <= 0:
        return "NO DATA"

    if sample_size == 1:
        return "EXTREMELY LIMITED — 1 MATCH"

    if sample_size == 2:
        return "VERY LIMITED — 2 MATCHES"

    if sample_size == 3:
        return "LIMITED — 3 MATCHES"

    if sample_size == 4:
        return "MODERATE — 4 MATCHES"

    if sample_size >= 5:

        if rate >= 80:
            return "GOOD HISTORICAL SUPPORT"

        if rate >= 60:
            return "MODERATE HISTORICAL SUPPORT"

        return "LOW HISTORICAL SUPPORT"

    return "LIMITED"


# =========================================================
# RECORD TEXT
# =========================================================

def record_text(rate, games):

    if games <= 0:
        return "No data"

    hits = round(
        rate / 100 * games
    )

    return (
        str(hits)
        + "/"
        + str(games)
    )


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

    return {
        "over_1_5": over_1_5,
        "over_2_5": over_2_5,
        "btts": btts,
        "home_to_score": home_stats["scored"],
        "away_to_score": away_stats["scored"]
    }


# =========================================================
# ADD SUPPORT
# =========================================================

def add_support(support, text, points):

    support.append(
        {
            "text": text,
            "points": points
        }
    )


# =========================================================
# SIGNAL ENGINE
# =========================================================

def calculate_signal(
    market,
    home_home,
    away_away,
    home_stat,
    away_stat
):

    raw_score = 0
    support = []
    caution = []

    # =====================================================
    # HOME TO SCORE
    # =====================================================

    if market == "home_to_score":

        games = home_home["games"]

        if games > 0:

            if home_home["scored"] >= 80:

                raw_score += 2

                add_support(
                    support,
                    "Home team scored in "
                    + record_text(
                        home_home["scored"],
                        games
                    )
                    + " home matches",
                    2
                )

            elif home_home["scored"] >= 60:

                raw_score += 1

                add_support(
                    support,
                    "Home team scored in "
                    + record_text(
                        home_home["scored"],
                        games
                    )
                    + " home matches",
                    1
                )

            else:

                raw_score -= 2

                caution.append(
                    "Home team failed to score in several home matches"
                )

        opponent_games = away_away["games"]

        if opponent_games > 0:

            if away_away["avg_conceded"] >= 1.2:

                raw_score += 2

                add_support(
                    support,
                    "Opponent concedes "
                    + str(away_away["avg_conceded"])
                    + " goals per away match",
                    2
                )

            elif away_away["avg_conceded"] < 0.8:

                raw_score -= 1

                caution.append(
                    "Opponent has a low away goals-conceded average"
                )

        if home_home["avg_goals"] >= 1.5:

            raw_score += 1

            add_support(
                support,
                "Home team averages "
                + str(home_home["avg_goals"])
                + " goals at home",
                1
            )

        elif home_home["avg_goals"] < 1.0:

            raw_score -= 1

            caution.append(
                "Home team averages below 1.0 goal at home"
            )

        if home_stat["shots_on_target"] >= 5:

            raw_score += 1

            add_support(
                support,
                "Home team averages "
                + str(home_stat["shots_on_target"])
                + " shots on target",
                1
            )

        if home_home["clean_sheets"] <= 20 and games >= 2:

            raw_score += 1

            add_support(
                support,
                "Home scoring environment shows limited clean-sheet resistance",
                1
            )

    # =====================================================
    # AWAY TO SCORE
    # =====================================================

    elif market == "away_to_score":

        games = away_away["games"]

        if games > 0:

            if away_away["scored"] >= 80:

                raw_score += 2

                add_support(
                    support,
                    "Away team scored in "
                    + record_text(
                        away_away["scored"],
                        games
                    )
                    + " away matches",
                    2
                )

            elif away_away["scored"] >= 60:

                raw_score += 1

                add_support(
                    support,
                    "Away team scored in "
                    + record_text(
                        away_away["scored"],
                        games
                    )
                    + " away matches",
                    1
                )

            else:

                raw_score -= 2

                caution.append(
                    "Away team failed to score in several away matches"
                )

        if home_home["avg_conceded"] >= 1.2:

            raw_score += 2

            add_support(
                support,
                "Home opponent concedes "
                + str(home_home["avg_conceded"])
                + " goals per home match",
                2
            )

        elif home_home["avg_conceded"] < 0.8:

            raw_score -= 1

            caution.append(
                "Home opponent has a low goals-conceded average"
            )

        if away_away["avg_goals"] >= 1.5:

            raw_score += 1

            add_support(
                support,
                "Away team averages "
                + str(away_away["avg_goals"])
                + " goals away",
                1
            )

        elif away_away["avg_goals"] < 1.0:

            raw_score -= 1

            caution.append(
                "Away team averages below 1.0 goal away"
            )

        if away_stat["shots_on_target"] >= 5:

            raw_score += 1

            add_support(
                support,
                "Away team averages "
                + str(away_stat["shots_on_target"])
                + " shots on target",
                1
            )

        if home_home["clean_sheets"] <= 20 and home_home["games"] >= 2:

            raw_score += 1

            add_support(
                support,
                "Home team has a limited clean-sheet rate",
                1
            )

    # =====================================================
    # OVER 1.5
    # =====================================================

    elif market == "over_1_5":

        if home_home["over_1_5"] >= 80:

            raw_score += 2

            add_support(
                support,
                "Home matches produced Over 1.5 in "
                + record_text(
                    home_home["over_1_5"],
                    home_home["games"]
                ),
                2
            )

        elif home_home["over_1_5"] >= 60:

            raw_score += 1

        else:

            raw_score -= 1

            caution.append(
                "Home Over 1.5 rate is below 60%"
            )

        if away_away["over_1_5"] >= 80:

            raw_score += 2

            add_support(
                support,
                "Away matches produced Over 1.5 in "
                + record_text(
                    away_away["over_1_5"],
                    away_away["games"]
                ),
                2
            )

        elif away_away["over_1_5"] >= 60:

            raw_score += 1

        else:

            raw_score -= 1

            caution.append(
                "Away Over 1.5 rate is below 60%"
            )

        combined_goals = (
            home_home["avg_goals"]
            + home_home["avg_conceded"]
            + away_away["avg_goals"]
            + away_away["avg_conceded"]
        ) / 2

        if combined_goals >= 2.5:

            raw_score += 2

            add_support(
                support,
                "Combined goal environment is "
                + str(round(combined_goals, 2)),
                2
            )

        elif combined_goals < 1.8:

            raw_score -= 1

            caution.append(
                "Combined goal environment is relatively low"
            )

    # =====================================================
    # OVER 2.5
    # =====================================================

    elif market == "over_2_5":

        if home_home["over_2_5"] >= 80:

            raw_score += 2

            add_support(
                support,
                "Home Over 2.5 occurred in "
                + record_text(
                    home_home["over_2_5"],
                    home_home["games"]
                ),
                2
            )

        elif home_home["over_2_5"] >= 60:

            raw_score += 1

        else:

            caution.append(
                "Home Over 2.5 rate is below 60%"
            )

        if away_away["over_2_5"] >= 80:

            raw_score += 2

            add_support(
                support,
                "Away Over 2.5 occurred in "
                + record_text(
                    away_away["over_2_5"],
                    away_away["games"]
                ),
                2
            )

        elif away_away["over_2_5"] >= 60:

            raw_score += 1

        else:

            caution.append(
                "Away Over 2.5 rate is below 60%"
            )

        combined_goals = (
            home_home["avg_goals"]
            + home_home["avg_conceded"]
            + away_away["avg_goals"]
            + away_away["avg_conceded"]
        ) / 2

        if combined_goals >= 3.0:

            raw_score += 2

            add_support(
                support,
                "Combined goal environment is "
                + str(round(combined_goals, 2))
                + " goals",
                2
            )

        elif combined_goals >= 2.5:

            raw_score += 1

        else:

            raw_score -= 1

            caution.append(
                "Combined goal environment is below 2.5 goals"
            )

        if home_stat["shots_on_target"] >= 5:

            raw_score += 1

            add_support(
                support,
                "Home team averages "
                + str(home_stat["shots_on_target"])
                + " shots on target",
                1
            )

        if away_stat["shots_on_target"] >= 5:

            raw_score += 1

            add_support(
                support,
                "Away team averages "
                + str(away_stat["shots_on_target"])
                + " shots on target",
                1
            )

    # =====================================================
    # BTTS
    # =====================================================

    elif market == "btts":

        if home_home["scored"] >= 80:

            raw_score += 2

            add_support(
                support,
                "Home team scored in "
                + record_text(
                    home_home["scored"],
                    home_home["games"]
                ),
                2
            )

        elif home_home["scored"] >= 60:

            raw_score += 1

        else:

            raw_score -= 2

            caution.append(
                "Home scoring rate is below 60%"
            )

        if away_away["scored"] >= 80:

            raw_score += 2

            add_support(
                support,
                "Away team scored in "
                + record_text(
                    away_away["scored"],
                    away_away["games"]
                ),
                2
            )

        elif away_away["scored"] >= 60:

            raw_score += 1

        else:

            raw_score -= 2

            caution.append(
                "Away scoring rate is below 60%"
            )

        if home_home["btts"] >= 80:

            raw_score += 1

            add_support(
                support,
                "Home BTTS rate is "
                + str(home_home["btts"])
                + "%",
                1
            )

        if away_away["btts"] >= 80:

            raw_score += 1

            add_support(
                support,
                "Away BTTS rate is "
                + str(away_away["btts"])
                + "%",
                1
            )

        if home_home["avg_goals"] + away_away["avg_goals"] >= 2.5:

            raw_score += 1

            add_support(
                support,
                "Combined scoring averages are "
                + str(
                    round(
                        home_home["avg_goals"]
                        + away_away["avg_goals"],
                        2
                    )
                )
                + " goals",
                1
            )

    # =====================================================
    # SCORE NORMALIZATION
    # =====================================================

    # The score is an internal historical signal score.
    # It is NOT a probability.
    #
    # We no longer multiply the score by a severe
    # sample-size weight. Sample size is handled through
    # the evidence label and caution message instead.

    if raw_score < 0:
        raw_score = 0

    if raw_score > 10:
        raw_score = 10

    signal_score = round(
        raw_score,
        1
    )

    # =====================================================
    # SAMPLE WARNING
    # =====================================================

    sample_sizes = [
        home_home["games"],
        away_away["games"]
    ]

    valid_sizes = [
        x for x in sample_sizes
        if x > 0
    ]

    if valid_sizes:

        average_sample = (
            sum(valid_sizes)
            / len(valid_sizes)
        )

    else:

        average_sample = 0

    if average_sample < 3:

        caution.append(
            "Very small home/away sample limits reliability"
        )

    elif average_sample < 5:

        caution.append(
            "Home/away sample is smaller than 5 matches"
        )

    return {
        "score": signal_score,
        "raw_score": raw_score,
        "support": support,
        "caution": caution,
        "average_sample": round(
            average_sample,
            1
        )
    }


# =========================================================
# ANALYZE MATCH
# =========================================================

def analyze_match(home_name, away_name):

    home_team = find_team(home_name)
    away_team = find_team(away_name)

    if not home_team or not away_team:

        return None, "One or both teams could not be found."

    home_id = home_team["team"]["id"]
    away_id = away_team["team"]["id"]

    home_fixtures = get_team_fixtures(home_id)
    away_fixtures = get_team_fixtures(away_id)

    if not home_fixtures or not away_fixtures:

        return None, "Football data could not be retrieved."

    home_fixtures = sorted(
        home_fixtures,
        key=lambda x: x["fixture"]["timestamp"],
        reverse=True
    )[:SAMPLE_SIZE]

    away_fixtures = sorted(
        away_fixtures,
        key=lambda x: x["fixture"]["timestamp"],
        reverse=True
    )[:SAMPLE_SIZE]

    home_stats = calculate_stats(
        home_fixtures,
        home_id
    )

    away_stats = calculate_stats(
        away_fixtures,
        away_id
    )

    home_home_fixtures = get_home_fixtures(
        home_fixtures,
        home_id
    )

    away_away_fixtures = get_away_fixtures(
        away_fixtures,
        away_id
    )

    home_home_stats = calculate_stats(
        home_home_fixtures,
        home_id
    )

    away_away_stats = calculate_stats(
        away_away_fixtures,
        away_id
    )

    home_stat_data = collect_team_match_stats(
        home_home_fixtures,
        home_id
    )

    away_stat_data = collect_team_match_stats(
        away_away_fixtures,
        away_id
    )

    markets = calculate_market_analysis(
        home_stats,
        away_stats
    )

    signals = {}

    signals["home_to_score"] = calculate_signal(
        "home_to_score",
        home_home_stats,
        away_away_stats,
        home_stat_data,
        away_stat_data
    )

    signals["away_to_score"] = calculate_signal(
        "away_to_score",
        home_home_stats,
        away_away_stats,
        home_stat_data,
        away_stat_data
    )

    signals["over_1_5"] = calculate_signal(
        "over_1_5",
        home_home_stats,
        away_away_stats,
        home_stat_data,
        away_stat_data
    )

    signals["over_2_5"] = calculate_signal(
        "over_2_5",
        home_home_stats,
        away_away_stats,
        home_stat_data,
        away_stat_data
    )

    signals["btts"] = calculate_signal(
        "btts",
        home_home_stats,
        away_away_stats,
        home_stat_data,
        away_stat_data
    )

    names = {
        "home_to_score":
            home_team["team"]["name"] + " to score",

        "away_to_score":
            away_team["team"]["name"] + " to score",

        "over_1_5":
            "Over 1.5 goals",

        "over_2_5":
            "Over 2.5 goals",

        "btts":
            "BTTS"
    }

    rates = {
        "home_to_score":
            markets["home_to_score"],

        "away_to_score":
            markets["away_to_score"],

        "over_1_5":
            markets["over_1_5"],

        "over_2_5":
            markets["over_2_5"],

        "btts":
            markets["btts"]
    }

    ordered = sorted(
        signals.keys(),
        key=lambda x: signals[x]["score"],
        reverse=True
    )

    return {
        "home_name": home_team["team"]["name"],
        "away_name": away_team["team"]["name"],

        "home_stats": home_stats,
        "away_stats": away_stats,

        "home_home_stats": home_home_stats,
        "away_away_stats": away_away_stats,

        "home_stat_data": home_stat_data,
        "away_stat_data": away_stat_data,

        "markets": markets,

        "signals": signals,
        "names": names,
        "rates": rates,

        "ordered": ordered
    }, None


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "⚽ Welcome to GoalLogic AI!\n\n"
        "I analyze football matches using historical statistics.\n\n"
        "Commands:\n"
        "/team Chelsea\n"
        "/fixtures Chelsea\n"
        "/analyze Chelsea vs Arsenal\n"
        "/apitest\n\n"
        "⚠️ Current API plan provides historical 2024 data."
    )


# =========================================================
# API TEST
# =========================================================

async def api_test(update: Update, context: ContextTypes.DEFAULT_TYPE):

    data = api_get("/status")

    if data:

        await update.message.reply_text(
            "✅ FOOTBALL API CONNECTION WORKING"
        )

    else:

        await update.message.reply_text(
            "❌ Football API connection failed."
        )


# =========================================================
# TEAM
# =========================================================

async def team_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "Use:\n/team Chelsea"
        )
        return

    team_name = " ".join(context.args)

    team = find_team(team_name)

    if not team:

        await update.message.reply_text(
            "❌ Team not found."
        )
        return

    info = team["team"]

    await update.message.reply_text(
        "⚽ TEAM FOUND\n\n"
        "🏟️ "
        + info["name"]
        + "\n"
        "🌍 "
        + info.get("country", "Unknown")
    )


# =========================================================
# FIXTURES
# =========================================================

async def fixtures_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "Use:\n/fixtures Chelsea"
        )
        return

    team_name = " ".join(context.args)

    team = find_team(team_name)

    if not team:

        await update.message.reply_text(
            "❌ Team not found."
        )
        return

    fixtures = get_team_fixtures(
        team["team"]["id"]
    )

    fixtures = sorted(
        fixtures,
        key=lambda x: x["fixture"]["timestamp"],
        reverse=True
    )[:5]

    if not fixtures:

        await update.message.reply_text(
            "❌ No fixtures found."
        )
        return

    message = (
        "📅 "
        + team["team"]["name"]
        + " — LAST 5 FIXTURES\n\n"
    )

    for fixture in fixtures:

        home = fixture["teams"]["home"]["name"]
        away = fixture["teams"]["away"]["name"]

        hg = fixture["goals"]["home"]
        ag = fixture["goals"]["away"]

        message += (
            "⚽ "
            + home
            + " "
            + str(hg)
            + "-"
            + str(ag)
            + " "
            + away
            + "\n"
        )

    message += (
        "\n📊 Data season: "
        + str(FIXTURE_SEASON)
    )

    await update.message.reply_text(message)


# =========================================================
# ANALYZE
# =========================================================

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "Use:\n/analyze Chelsea vs Arsenal"
        )
        return

    text_input = " ".join(context.args)

    parts = text_input.split(" vs ")

    if len(parts) != 2:

        await update.message.reply_text(
            "Please use:\n"
            "/analyze Chelsea vs Arsenal"
        )
        return

    home_name = parts[0].strip()
    away_name = parts[1].strip()

    await update.message.reply_text(
        "🔎 Analyzing historical data...\n"
        "Please wait."
    )

    result, error = analyze_match(
        home_name,
        away_name
    )

    if error:

        await update.message.reply_text(
            "❌ " + error
        )
        return

    home = result["home_stats"]
    away = result["away_stats"]

    home_home = result["home_home_stats"]
    away_away = result["away_away_stats"]

    home_stat = result["home_stat_data"]
    away_stat = result["away_stat_data"]

    markets = result["markets"]

    signals = result["signals"]
    names = result["names"]
    rates = result["rates"]

    ordered = result["ordered"]

    # =====================================================
    # EVIDENCE
    # =====================================================

    evidence = {}

    evidence["home_to_score"] = evidence_quality(
        markets["home_to_score"],
        home_home["games"]
    )

    evidence["away_to_score"] = evidence_quality(
        markets["away_to_score"],
        away_away["games"]
    )

    combined_sample = min(
        home_home["games"],
        away_away["games"]
    )

    evidence["over_1_5"] = evidence_quality(
        markets["over_1_5"],
        combined_sample
    )

    evidence["over_2_5"] = evidence_quality(
        markets["over_2_5"],
        combined_sample
    )

    evidence["btts"] = evidence_quality(
        markets["btts"],
        combined_sample
    )

    # =====================================================
    # MESSAGE
    # =====================================================

    message = (
        "⚽ GOALLOGIC AI ANALYSIS\n\n"

        "🏟️ "
        + result["home_name"]
        + " vs "
        + result["away_name"]
        + "\n\n"

        "📊 DATA PERIOD\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Season: "
        + str(FIXTURE_SEASON)
        + "\n"
        "Sample: Last "
        + str(SAMPLE_SIZE)
        + " available matches\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "📈 RECENT FORM\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🏠 "
        + result["home_name"]
        + "\n"
        "✅ Wins: "
        + str(home["wins"])
        + "\n"
        "🤝 Draws: "
        + str(home["draws"])
        + "\n"
        "❌ Losses: "
        + str(home["losses"])
        + "\n"
        "⚽ Avg goals: "
        + str(home["avg_goals"])
        + "\n"
        "🥅 Avg conceded: "
        + str(home["avg_conceded"])
        + "\n"
        "🔥 Over 2.5: "
        + str(home["over_2_5"])
        + "%\n"
        "🎯 BTTS: "
        + str(home["btts"])
        + "%\n\n"

        "✈️ "
        + result["away_name"]
        + "\n"
        "✅ Wins: "
        + str(away["wins"])
        + "\n"
        "🤝 Draws: "
        + str(away["draws"])
        + "\n"
        "❌ Losses: "
        + str(away["losses"])
        + "\n"
        "⚽ Avg goals: "
        + str(away["avg_goals"])
        + "\n"
        "🥅 Avg conceded: "
        + str(away["avg_conceded"])
        + "\n"
        "🔥 Over 2.5: "
        + str(away["over_2_5"])
        + "%\n"
        "🎯 BTTS: "
        + str(away["btts"])
        + "%\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🏠 HOME / AWAY\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🏠 "
        + result["home_name"]
        + " HOME\n"
        "Games: "
        + str(home_home["games"])
        + "\n"
        "⚽ Avg scored: "
        + str(home_home["avg_goals"])
        + "\n"
        "🥅 Avg conceded: "
        + str(home_home["avg_conceded"])
        + "\n"
        "🔥 Over 2.5: "
        + str(home_home["over_2_5"])
        + "%\n"
        "🎯 BTTS: "
        + str(home_home["btts"])
        + "%\n\n"

        "✈️ "
        + result["away_name"]
        + " AWAY\n"
        "Games: "
        + str(away_away["games"])
        + "\n"
        "⚽ Avg scored: "
        + str(away_away["avg_goals"])
        + "\n"
        "🥅 Avg conceded: "
        + str(away_away["avg_conceded"])
        + "\n"
        "🔥 Over 2.5: "
        + str(away_away["over_2_5"])
        + "%\n"
        "🎯 BTTS: "
        + str(away_away["btts"])
        + "%\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 MATCH STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🏠 "
        + result["home_name"]
        + "\n"
        "🎯 Shots: "
        + str(home_stat["shots"])
        + "\n"
        "🎯 Shots on target: "
        + str(home_stat["shots_on_target"])
        + "\n"
        "🚩 Corners: "
        + str(home_stat["corners"])
        + "\n"
        "🟨 Yellow cards: "
        + str(home_stat["yellow_cards"])
        + "\n\n"

        "✈️ "
        + result["away_name"]
        + "\n"
        "🎯 Shots: "
        + str(away_stat["shots"])
        + "\n"
        "🎯 Shots on target: "
        + str(away_stat["shots_on_target"])
        + "\n"
        "🚩 Corners: "
        + str(away_stat["corners"])
        + "\n"
        "🟨 Yellow cards: "
        + str(away_stat["yellow_cards"])
        + "\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "📊 MARKET ANALYSIS\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "⚽ Over 1.5 goals: "
        + str(markets["over_1_5"])
        + "%\n"
        "   Sample: "
        + str(combined_sample)
        + " matches per side where available\n"
        "   Evidence: "
        + evidence["over_1_5"]
        + "\n\n"

        "🔥 Over 2.5 goals: "
        + str(markets["over_2_5"])
        + "%\n"
        "   Sample: "
        + str(combined_sample)
        + " matches per side where available\n"
        "   Evidence: "
        + evidence["over_2_5"]
        + "\n\n"

        "🎯 BTTS: "
        + str(markets["btts"])
        + "%\n"
        "   Sample: "
        + str(combined_sample)
        + " matches per side where available\n"
        "   Evidence: "
        + evidence["btts"]
        + "\n\n"

        "🏠 "
        + result["home_name"]
        + " to score: "
        + str(markets["home_to_score"])
        + "%\n"
        "   Record: "
        + record_text(
            markets["home_to_score"],
            home_home["games"]
        )
        + "\n"
        "   Evidence: "
        + evidence["home_to_score"]
        + "\n\n"

        "✈️ "
        + result["away_name"]
        + " to score: "
        + str(markets["away_to_score"])
        + "%\n"
        "   Record: "
        + record_text(
            markets["away_to_score"],
            away_away["games"]
        )
        + "\n"
        "   Evidence: "
        + evidence["away_to_score"]
        + "\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🤖 GOALLOGIC AI SIGNAL ENGINE\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )

    # =====================================================
    # SIGNAL LIST
    # =====================================================

    for index, key in enumerate(ordered):

        signal = signals[key]

        message += (
            str(index + 1)
            + ". "
            + names[key]
            + "\n"
            "   🧠 Signal score: "
            + str(signal["score"])
            + "/10\n"
            "   📈 Historical hit rate: "
            + str(rates[key])
            + "%\n"
        )

        if key == "home_to_score":

            message += (
                "   📋 Record: "
                + record_text(
                    rates[key],
                    home_home["games"]
                )
                + "\n"
            )

        elif key == "away_to_score":

            message += (
                "   📋 Record: "
                + record_text(
                    rates[key],
                    away_away["games"]
                )
                + "\n"
            )

        else:

            message += (
                "   📋 Sample: "
                + str(combined_sample)
                + " matches per side where available\n"
            )

        message += (
            "   📊 Evidence: "
            + evidence[key]
            + "\n\n"
        )

    # =====================================================
    # TOP SIGNAL
    # =====================================================

    top_key = ordered[0]
    top_signal = signals[top_key]

    message += (
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 TOP HISTORICAL SIGNAL\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "📌 "
        + names[top_key]
        + "\n"
        "🧠 Signal score: "
        + str(top_signal["score"])
        + "/10\n"
        "📈 Historical hit rate: "
        + str(rates[top_key])
        + "%\n"
    )

    if top_key == "home_to_score":

        message += (
            "📋 Historical record: "
            + record_text(
                rates[top_key],
                home_home["games"]
            )
            + "\n"
        )

    elif top_key == "away_to_score":

        message += (
            "📋 Historical record: "
            + record_text(
                rates[top_key],
                away_away["games"]
            )
            + "\n"
        )

    else:

        message += (
            "📋 Historical sample: "
            + str(combined_sample)
            + " matches per side where available\n"
        )

    message += (
        "\n📊 Evidence: "
        + evidence[top_key]
        + "\n\n"

        "✅ SUPPORTING FACTORS\n"
    )

    if top_signal["support"]:

        for item in top_signal["support"][:5]:

            message += (
                "• "
                + item["text"]
                + "\n"
            )

    else:

        message += (
            "• No strong supporting factor identified.\n"
        )

    message += (
        "\n⚠️ CAUTION FACTORS\n"
    )

    if top_signal["caution"]:

        for item in top_signal["caution"][:5]:

            message += (
                "• "
                + item
                + "\n"
            )

    else:

        message += (
            "• No major caution factor identified.\n"
        )

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "⚠️ DATA NOTICE\n"
        "━━━━━━━━━━━━━━━━━━\n"

        "Historical hit rates describe the selected "
        "historical sample. They are not guaranteed "
        "probabilities of the next match.\n\n"

        "The signal score combines multiple historical "
        "factors. It is an internal historical screening "
        "score, not a guaranteed prediction or probability.\n\n"

        "Small samples such as 2/2 or 3/3 can look strong "
        "but have limited evidence. Larger samples provide "
        "more historical support.\n\n"

        "Data uses the 2024 season because the current "
        "API plan does not provide the current 2026 "
        "fixture season."
    )

    await update.message.reply_text(message)


# =========================================================
# NORMAL MESSAGE
# =========================================================

async def normal_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "⚽ GoalLogic AI\n\n"
        "Use:\n"
        "/analyze Chelsea vs Arsenal\n\n"
        "Other commands:\n"
        "/team Chelsea\n"
        "/fixtures Chelsea\n"
        "/apitest"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not TELEGRAM_BOT_TOKEN:

        print("ERROR: TELEGRAM_BOT_TOKEN is missing.")
        return

    if not FOOTBALL_API_KEY:

        print("ERROR: FOOTBALL_API_KEY is missing.")
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
            normal_message
        )
    )

    print("GoalLogic AI is running.")

    application.run_polling()


if __name__ == "__main__":
    main()
