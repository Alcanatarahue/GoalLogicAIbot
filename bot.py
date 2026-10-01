import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

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

API_BASE = "https://v3.football.api-sports.io"
FIXTURE_SEASON = 2024
SAMPLE_SIZE = 5


# ============================================================
# RENDER HEALTH SERVER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GoalLogic AI is running.")

    def log_message(self, format, *args):
        return


def run_health_server():
    port = int(os.environ.get("PORT", 10000))

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    print(f"GoalLogic AI is running on port {port}.")
    server.serve_forever()


# ============================================================
# API
# ============================================================

def api_get(endpoint, params=None):

    if not FOOTBALL_API_KEY:
        print("FOOTBALL_API_KEY is missing.")
        return None

    try:
        response = httpx.get(
            API_BASE + endpoint,
            headers={
                "x-apisports-key": FOOTBALL_API_KEY
            },
            params=params or {},
            timeout=30
        )

        print(
            f"API REQUEST: {endpoint} | "
            f"STATUS: {response.status_code}"
        )

        if response.status_code != 200:
            print("API ERROR:", response.text)
            return None

        return response.json()

    except Exception as e:
        print("API ERROR:", e)
        return None


# ============================================================
# TEAM SEARCH
# ============================================================

def find_team(team_name):

    data = api_get(
        "/teams",
        {"search": team_name}
    )

    if not data:
        return None

    response = data.get("response", [])

    if not response:
        return None

    return response[0]


# ============================================================
# FIXTURES
# ============================================================

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


# ============================================================
# BASIC STATISTICS
# ============================================================

def calculate_stats(fixtures, team_id):

    stats = {
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

    if not fixtures:
        return stats

    goals_for = 0
    goals_against = 0
    over15 = 0
    over25 = 0
    btts = 0
    scored = 0
    clean_sheets = 0

    for fixture in fixtures:

        status = (
            fixture.get("fixture", {})
            .get("status", {})
            .get("short")
        )

        if status not in ["FT", "AET", "PEN"]:
            continue

        teams = fixture.get("teams", {})
        goals = fixture.get("goals", {})

        home_id = teams.get("home", {}).get("id")
        away_id = teams.get("away", {}).get("id")

        home_goals = goals.get("home")
        away_goals = goals.get("away")

        if home_goals is None or away_goals is None:
            continue

        if team_id == home_id:
            gf = home_goals
            ga = away_goals
        elif team_id == away_id:
            gf = away_goals
            ga = home_goals
        else:
            continue

        stats["games"] += 1

        goals_for += gf
        goals_against += ga

        if gf > ga:
            stats["wins"] += 1
        elif gf == ga:
            stats["draws"] += 1
        else:
            stats["losses"] += 1

        total = gf + ga

        if total >= 2:
            over15 += 1

        if total >= 3:
            over25 += 1

        if gf > 0:
            scored += 1

        if gf > 0 and ga > 0:
            btts += 1

        if ga == 0:
            clean_sheets += 1

        if stats["games"] >= SAMPLE_SIZE:
            break

    games = stats["games"]

    if games == 0:
        return stats

    stats["avg_goals"] = round(
        goals_for / games,
        2
    )

    stats["avg_conceded"] = round(
        goals_against / games,
        2
    )

    stats["over_1_5"] = round(
        over15 / games * 100
    )

    stats["over_2_5"] = round(
        over25 / games * 100
    )

    stats["btts"] = round(
        btts / games * 100
    )

    stats["scored"] = round(
        scored / games * 100
    )

    stats["clean_sheets"] = round(
        clean_sheets / games * 100
    )

    return stats


# ============================================================
# HOME / AWAY
# ============================================================

def get_home_fixtures(fixtures, team_id):

    result = []

    for fixture in fixtures:

        home_id = (
            fixture.get("teams", {})
            .get("home", {})
            .get("id")
        )

        if home_id == team_id:
            result.append(fixture)

        if len(result) >= SAMPLE_SIZE:
            break

    return result


def get_away_fixtures(fixtures, team_id):

    result = []

    for fixture in fixtures:

        away_id = (
            fixture.get("teams", {})
            .get("away", {})
            .get("id")
        )

        if away_id == team_id:
            result.append(fixture)

        if len(result) >= SAMPLE_SIZE:
            break

    return result


# ============================================================
# MATCH STATISTICS
# ============================================================

def collect_team_match_stats(fixtures, team_id):

    shots = []
    shots_on_target = []
    corners = []
    yellow_cards = []

    for fixture in fixtures:

        fixture_id = (
            fixture.get("fixture", {})
            .get("id")
        )

        if not fixture_id:
            continue

        data = api_get(
            "/fixtures/statistics",
            {"fixture": fixture_id}
        )

        if not data:
            continue

        response = data.get("response", [])

        team_stats = None

        for item in response:

            if (
                item.get("team", {})
                .get("id")
                == team_id
            ):
                team_stats = item
                break

        if not team_stats:
            continue

        stat_map = {}

        for item in team_stats.get(
            "statistics",
            []
        ):
            stat_map[item.get("type")] = item.get("value")

        def number(value):

            if value is None:
                return None

            if isinstance(value, str):
                value = value.replace("%", "")

            try:
                return float(value)
            except:
                return None

        value = number(
            stat_map.get("Total Shots")
        )
        if value is not None:
            shots.append(value)

        value = number(
            stat_map.get("Shots on Goal")
        )
        if value is not None:
            shots_on_target.append(value)

        value = number(
            stat_map.get("Corner Kicks")
        )
        if value is not None:
            corners.append(value)

        value = number(
            stat_map.get("Yellow Cards")
        )
        if value is not None:
            yellow_cards.append(value)

    def average(values):

        if not values:
            return 0

        return round(
            sum(values) / len(values),
            1
        )

    return {
        "shots": average(shots),
        "shots_on_target": average(shots_on_target),
        "corners": average(corners),
        "yellow_cards": average(yellow_cards)
    }


# ============================================================
# EVIDENCE
# ============================================================

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

    if rate >= 80:
        return "GOOD HISTORICAL SUPPORT"

    if rate >= 60:
        return "MODERATE HISTORICAL SUPPORT"

    return "LOW HISTORICAL SUPPORT"


def record_text(rate, games):

    if games <= 0:
        return "No data"

    hits = round(
        rate / 100 * games
    )

    return f"{hits}/{games}"


# ============================================================
# MARKET ANALYSIS
# ============================================================

def calculate_market_analysis(
    home_home,
    away_away
):

    return {

        "over_1_5": round(
            (
                home_home["over_1_5"]
                + away_away["over_1_5"]
            ) / 2
        ),

        "over_2_5": round(
            (
                home_home["over_2_5"]
                + away_away["over_2_5"]
            ) / 2
        ),

        "btts": round(
            (
                home_home["btts"]
                + away_away["btts"]
            ) / 2
        ),

        "home_to_score":
            home_home["scored"],

        "away_to_score":
            away_away["scored"]
    }


# ============================================================
# SIGNAL ENGINE
# ============================================================

def calculate_signal(
    market,
    home_home,
    away_away,
    home_match_stats,
    away_match_stats
):

    market_rates = calculate_market_analysis(
        home_home,
        away_away
    )

    rate = market_rates[market]

    # Direct historical hit rate is the
    # most important factor.
    score = round(
        (rate / 100) * 7,
        1
    )

    support = []
    caution = []

    # --------------------------------------------------------
    # HOME TO SCORE
    # --------------------------------------------------------

    if market == "home_to_score":

        if away_away["avg_conceded"] >= 1.2:

            score += 1

            support.append(
                "Away team concedes "
                f"{away_away['avg_conceded']} "
                "goals per away match"
            )

        if home_home["avg_goals"] >= 1.5:

            score += 1

            support.append(
                "Home team averages "
                f"{home_home['avg_goals']} "
                "goals at home"
            )

        if home_match_stats["shots_on_target"] >= 5:

            score += 1

            support.append(
                "Home team averages "
                f"{home_match_stats['shots_on_target']} "
                "shots on target"
            )

        if away_away["clean_sheets"] >= 60:

            score -= 1

            caution.append(
                "Away team has a strong "
                "away clean-sheet rate"
            )

    # --------------------------------------------------------
    # AWAY TO SCORE
    # --------------------------------------------------------

    elif market == "away_to_score":

        if home_home["avg_conceded"] >= 1.2:

            score += 1

            support.append(
                "Home team concedes "
                f"{home_home['avg_conceded']} "
                "goals per home match"
            )

        if away_away["avg_goals"] >= 1.5:

            score += 1

            support.append(
                "Away team averages "
                f"{away_away['avg_goals']} "
                "goals away"
            )

        if away_match_stats["shots_on_target"] >= 5:

            score += 1

            support.append(
                "Away team averages "
                f"{away_match_stats['shots_on_target']} "
                "shots on target"
            )

        if home_home["clean_sheets"] >= 60:

            score -= 1

            caution.append(
                "Home team has a strong "
                "home clean-sheet rate"
            )

    # --------------------------------------------------------
    # OVER 1.5
    # --------------------------------------------------------

    elif market == "over_1_5":

        if home_home["over_1_5"] >= 80:
            score += 1
            support.append(
                "Home over 1.5 rate is "
                f"{home_home['over_1_5']}%"
            )

        elif home_home["over_1_5"] >= 60:
            score += 0.5
            support.append(
                "Home over 1.5 rate is "
                f"{home_home['over_1_5']}%"
            )

        if away_away["over_1_5"] >= 80:
            score += 1
            support.append(
                "Away over 1.5 rate is "
                f"{away_away['over_1_5']}%"
            )

        elif away_away["over_1_5"] >= 60:
            score += 0.5
            support.append(
                "Away over 1.5 rate is "
                f"{away_away['over_1_5']}%"
            )

        combined_goals = (
            home_home["avg_goals"]
            + home_home["avg_conceded"]
            + away_away["avg_goals"]
            + away_away["avg_conceded"]
        ) / 2

        if combined_goals >= 2.5:

            score += 1

            support.append(
                "Combined goal environment "
                f"is {round(combined_goals, 2)}"
            )

    # --------------------------------------------------------
    # OVER 2.5
    # --------------------------------------------------------

    elif market == "over_2_5":

        if home_home["over_2_5"] >= 80:
            score += 1
            support.append(
                "Home over 2.5 rate is "
                f"{home_home['over_2_5']}%"
            )

        elif home_home["over_2_5"] >= 60:
            score += 0.5
            support.append(
                "Home over 2.5 rate is "
                f"{home_home['over_2_5']}%"
            )

        if away_away["over_2_5"] >= 80:
            score += 1
            support.append(
                "Away over 2.5 rate is "
                f"{away_away['over_2_5']}%"
            )

        elif away_away["over_2_5"] >= 60:
            score += 0.5
            support.append(
                "Away over 2.5 rate is "
                f"{away_away['over_2_5']}%"
            )

        combined_goals = (
            home_home["avg_goals"]
            + home_home["avg_conceded"]
            + away_away["avg_goals"]
            + away_away["avg_conceded"]
        ) / 2

        if combined_goals >= 3.0:

            score += 1

            support.append(
                "Strong combined goal "
                f"environment: {round(combined_goals, 2)}"
            )

        elif combined_goals >= 2.5:

            score += 0.5

            support.append(
                "Positive combined goal "
                f"environment: {round(combined_goals, 2)}"
            )

    # --------------------------------------------------------
    # BTTS
    # --------------------------------------------------------

    elif market == "btts":

        if (
            home_home["scored"] >= 80
            and
            away_away["scored"] >= 80
        ):

            score += 1

            support.append(
                "Both teams scored in "
                "80%+ of relevant matches"
            )

        if (
            home_home["btts"] >= 80
            and
            away_away["btts"] >= 80
        ):

            score += 1

            support.append(
                "Both teams have strong "
                "BTTS records"
            )

        combined_scoring = (
            home_home["avg_goals"]
            + away_away["avg_goals"]
        )

        if combined_scoring >= 2.5:

            score += 0.5

            support.append(
                "Combined scoring average is "
                f"{round(combined_scoring, 2)}"
            )

    score = max(
        0,
        min(
            10,
            round(score, 1)
        )
    )

    if market == "home_to_score":
        sample = home_home["games"]

    elif market == "away_to_score":
        sample = away_away["games"]

    else:
        sample = min(
            home_home["games"],
            away_away["games"]
        )

    if sample < 3:
        caution.append(
            "Very small home/away sample"
        )

    elif sample < 5:
        caution.append(
            "Home/away sample is smaller "
            "than 5 matches"
        )

    return {
        "market": market,
        "score": score,
        "rate": rate,
        "support": support,
        "caution": caution
    }


# ============================================================
# MARKET NAME
# ============================================================

def market_name(market):

    names = {
        "over_1_5": "Over 1.5 goals",
        "over_2_5": "Over 2.5 goals",
        "btts": "BTTS"
    }

    return names.get(
        market,
        market
    )


# ============================================================
# ANALYZE MATCH
# ============================================================

def analyze_match(
    home_name,
    away_name
):

    home_team = find_team(home_name)
    away_team = find_team(away_name)

    if not home_team:
        return f"❌ Could not find {home_name}."

    if not away_team:
        return f"❌ Could not find {away_name}."

    home_info = home_team.get("team", {})
    away_info = away_team.get("team", {})

    home_id = home_info.get("id")
    away_id = away_info.get("id")

    official_home = home_info.get(
        "name",
        home_name
    )

    official_away = away_info.get(
        "name",
        away_name
    )

    home_fixtures = get_team_fixtures(
        home_id
    )

    away_fixtures = get_team_fixtures(
        away_id
    )

    if not home_fixtures or not away_fixtures:

        return (
            "⚠️ Football data could not "
            "be retrieved."
        )

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

    home_home = calculate_stats(
        home_home_fixtures,
        home_id
    )

    away_away = calculate_stats(
        away_away_fixtures,
        away_id
    )

    home_match_stats = collect_team_match_stats(
        home_fixtures[:SAMPLE_SIZE],
        home_id
    )

    away_match_stats = collect_team_match_stats(
        away_fixtures[:SAMPLE_SIZE],
        away_id
    )

    markets = calculate_market_analysis(
        home_home,
        away_away
    )

    market_list = [
        "home_to_score",
        "away_to_score",
        "over_1_5",
        "over_2_5",
        "btts"
    ]

    signals = []

    for market in market_list:

        signals.append(
            calculate_signal(
                market,
                home_home,
                away_away,
                home_match_stats,
                away_match_stats
            )
        )

    signals.sort(
        key=lambda x: (
            x["score"],
            x["rate"]
        ),
        reverse=True
    )

    top = signals[0]

    # ========================================================
    # OUTPUT
    # ========================================================

    lines = []

    lines.append(
        "⚽ GOALLOGIC AI ANALYSIS"
    )

    lines.append("")
    lines.append(
        f"🏟️ {official_home} vs {official_away}"
    )

    lines.append("")
    lines.append("📊 DATA PERIOD")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append(
        f"Season: {FIXTURE_SEASON}"
    )
    lines.append(
        "Sample: Last 5 available matches"
    )

    # --------------------------------------------------------
    # FORM
    # --------------------------------------------------------

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("📈 RECENT FORM")
    lines.append("━━━━━━━━━━━━━━━━━━")

    lines.append("")
    lines.append(f"🏠 {official_home}")
    lines.append(
        f"✅ Wins: {home_stats['wins']}"
    )
    lines.append(
        f"🤝 Draws: {home_stats['draws']}"
    )
    lines.append(
        f"❌ Losses: {home_stats['losses']}"
    )
    lines.append(
        f"⚽ Avg goals: {home_stats['avg_goals']}"
    )
    lines.append(
        f"🥅 Avg conceded: "
        f"{home_stats['avg_conceded']}"
    )
    lines.append(
        f"🔥 Over 2.5: "
        f"{home_stats['over_2_5']}%"
    )
    lines.append(
        f"🎯 BTTS: {home_stats['btts']}%"
    )

    lines.append("")
    lines.append(f"✈️ {official_away}")
    lines.append(
        f"✅ Wins: {away_stats['wins']}"
    )
    lines.append(
        f"🤝 Draws: {away_stats['draws']}"
    )
    lines.append(
        f"❌ Losses: {away_stats['losses']}"
    )
    lines.append(
        f"⚽ Avg goals: {away_stats['avg_goals']}"
    )
    lines.append(
        f"🥅 Avg conceded: "
        f"{away_stats['avg_conceded']}"
    )
    lines.append(
        f"🔥 Over 2.5: "
        f"{away_stats['over_2_5']}%"
    )
    lines.append(
        f"🎯 BTTS: {away_stats['btts']}%"
    )

    # --------------------------------------------------------
    # HOME / AWAY
    # --------------------------------------------------------

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("🏠 HOME / AWAY")
    lines.append("━━━━━━━━━━━━━━━━━━")

    lines.append("")
    lines.append(
        f"🏠 {official_home} HOME"
    )
    lines.append(
        f"Games: {home_home['games']}"
    )
    lines.append(
        f"⚽ Avg scored: "
        f"{home_home['avg_goals']}"
    )
    lines.append(
        f"🥅 Avg conceded: "
        f"{home_home['avg_conceded']}"
    )
    lines.append(
        f"🔥 Over 2.5: "
        f"{home_home['over_2_5']}%"
    )
    lines.append(
        f"🎯 BTTS: {home_home['btts']}%"
    )

    lines.append("")
    lines.append(
        f"✈️ {official_away} AWAY"
    )
    lines.append(
        f"Games: {away_away['games']}"
    )
    lines.append(
        f"⚽ Avg scored: "
        f"{away_away['avg_goals']}"
    )
    lines.append(
        f"🥅 Avg conceded: "
        f"{away_away['avg_conceded']}"
    )
    lines.append(
        f"🔥 Over 2.5: "
        f"{away_away['over_2_5']}%"
    )
    lines.append(
        f"🎯 BTTS: {away_away['btts']}%"
    )

    # --------------------------------------------------------
    # MATCH STATS
    # --------------------------------------------------------

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("🎯 MATCH STATISTICS")
    lines.append("━━━━━━━━━━━━━━━━━━")

    lines.append("")
    lines.append(f"🏠 {official_home}")
    lines.append(
        f"🎯 Shots: {home_match_stats['shots']}"
    )
    lines.append(
        f"🎯 Shots on target: "
        f"{home_match_stats['shots_on_target']}"
    )
    lines.append(
        f"🚩 Corners: "
        f"{home_match_stats['corners']}"
    )
    lines.append(
        f"🟨 Yellow cards: "
        f"{home_match_stats['yellow_cards']}"
    )

    lines.append("")
    lines.append(f"✈️ {official_away}")
    lines.append(
        f"🎯 Shots: {away_match_stats['shots']}"
    )
    lines.append(
        f"🎯 Shots on target: "
        f"{away_match_stats['shots_on_target']}"
    )
    lines.append(
        f"🚩 Corners: "
        f"{away_match_stats['corners']}"
    )
    lines.append(
        f"🟨 Yellow cards: "
        f"{away_match_stats['yellow_cards']}"
    )

    # --------------------------------------------------------
    # MARKET ANALYSIS
    # --------------------------------------------------------

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("📊 MARKET ANALYSIS")
    lines.append("━━━━━━━━━━━━━━━━━━")

    lines.append("")
    lines.append(
        f"⚽ Over 1.5 goals: "
        f"{markets['over_1_5']}%"
    )
    lines.append(
        f"   Sample: {home_home['games']} home + "
        f"{away_away['games']} away"
    )

    lines.append("")
    lines.append(
        f"🔥 Over 2.5 goals: "
        f"{markets['over_2_5']}%"
    )
    lines.append(
        f"   Sample: {home_home['games']} home + "
        f"{away_away['games']} away"
    )

    lines.append("")
    lines.append(
        f"🎯 BTTS: {markets['btts']}%"
    )
    lines.append(
        f"   Sample: {home_home['games']} home + "
        f"{away_away['games']} away"
    )

    lines.append("")
    lines.append(
        f"🏠 {official_home} to score: "
        f"{markets['home_to_score']}%"
    )
    lines.append(
        f"   Record: "
        f"{record_text(markets['home_to_score'], home_home['games'])}"
    )

    lines.append("")
    lines.append(
        f"✈️ {official_away} to score: "
        f"{markets['away_to_score']}%"
    )
    lines.append(
        f"   Record: "
        f"{record_text(markets['away_to_score'], away_away['games'])}"
    )

    # --------------------------------------------------------
    # SIGNAL ENGINE
    # --------------------------------------------------------

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("🤖 GOALLOGIC AI SIGNAL ENGINE")
    lines.append("━━━━━━━━━━━━━━━━━━")

    for index, signal in enumerate(
        signals,
        start=1
    ):

        market = signal["market"]

        if market == "home_to_score":

            name = (
                f"{official_home} to score"
            )

            sample = home_home["games"]

            record = record_text(
                signal["rate"],
                sample
            )

        elif market == "away_to_score":

            name = (
                f"{official_away} to score"
            )

            sample = away_away["games"]

            record = record_text(
                signal["rate"],
                sample
            )

        else:

            name = market_name(market)

            sample = min(
                home_home["games"],
                away_away["games"]
            )

            record = None

        lines.append("")
        lines.append(
            f"{index}. {name}"
        )
        lines.append(
            f"   🧠 Signal score: "
            f"{signal['score']}/10"
        )
        lines.append(
            f"   📈 Historical hit rate: "
            f"{signal['rate']}%"
        )

        if record:
            lines.append(
                f"   📋 Record: {record}"
            )
        else:
            lines.append(
                f"   📋 Sample: "
                f"{home_home['games']} home + "
                f"{away_away['games']} away"
            )

        lines.append(
            f"   📊 Evidence: "
            f"{evidence_quality(signal['rate'], sample)}"
        )

    # --------------------------------------------------------
    # TOP SIGNAL
    # --------------------------------------------------------

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("🎯 TOP HISTORICAL SIGNAL")
    lines.append("━━━━━━━━━━━━━━━━━━")

    top_market = top["market"]

    if top_market == "home_to_score":

        top_name = (
            f"{official_home} to score"
        )

        top_sample = home_home["games"]

        top_record = record_text(
            top["rate"],
            top_sample
        )

    elif top_market == "away_to_score":

        top_name = (
            f"{official_away} to score"
        )

        top_sample = away_away["games"]

        top_record = record_text(
            top["rate"],
            top_sample
        )

    else:

        top_name = market_name(
            top_market
        )

        top_sample = min(
            home_home["games"],
            away_away["games"]
        )

        top_record = None

    lines.append("")
    lines.append(
        f"📌 {top_name}"
    )
    lines.append(
        f"🧠 Signal score: {top['score']}/10"
    )
    lines.append(
        f"📈 Historical hit rate: {top['rate']}%"
    )

    if top_record:
        lines.append(
            f"📋 Historical record: {top_record}"
        )
    else:
        lines.append(
            f"📋 Historical sample: "
            f"{home_home['games']} home + "
            f"{away_away['games']} away"
        )

    lines.append(
        f"📊 Evidence: "
        f"{evidence_quality(top['rate'], top_sample)}"
    )

    if top["support"]:

        lines.append("")
        lines.append(
            "✅ SUPPORTING FACTORS"
        )

        for item in top["support"]:
            lines.append(
                f"• {item}"
            )

    if top["caution"]:

        lines.append("")
        lines.append(
            "⚠️ CAUTION FACTORS"
        )

        for item in top["caution"]:
            lines.append(
                f"• {item}"
            )

    # --------------------------------------------------------
    # NOTICE
    # --------------------------------------------------------

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("⚠️ DATA NOTICE")
    lines.append("━━━━━━━━━━━━━━━━━━")

    lines.append(
        "Historical hit rates describe "
        "the selected historical sample. "
        "They are not guaranteed probabilities "
        "of the next match."
    )

    lines.append("")

    lines.append(
        "The signal score gives the greatest "
        "weight to the direct historical hit "
        "rate, followed by supporting statistics."
    )

    lines.append("")

    lines.append(
        "The signal score is an internal "
        "historical screening score, not a "
        "guaranteed prediction or probability."
    )

    lines.append("")

    lines.append(
        "Small samples such as 2/2 or 3/3 "
        "can look strong but have limited "
        "historical support."
    )

    lines.append("")

    lines.append(
        "Data uses the 2024 season because "
        "the current API plan does not provide "
        "the current 2026 fixture season."
    )

    return "\n".join(lines)


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "⚽ Welcome to GoalLogic AI!\n\n"
        "I analyze football matches using "
        "historical statistics.\n\n"
        "Commands:\n"
        "/team Chelsea\n"
        "/fixtures Chelsea\n"
        "/analyze Chelsea vs Arsenal\n"
        "/apitest\n\n"
        "⚠️ Current API plan provides "
        "historical 2024 data."
    )


async def api_test_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    data = api_get("/status")

    if not data:

        await update.message.reply_text(
            "❌ Football API test failed."
        )

        return

    await update.message.reply_text(
        "🔧 FOOTBALL API TEST\n\n"
        "✅ API connection is working."
    )


async def team_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Usage:\n/team Chelsea"
        )

        return

    team_name = " ".join(
        context.args
    )

    team = find_team(team_name)

    if not team:

        await update.message.reply_text(
            f"❌ Could not find {team_name}."
        )

        return

    info = team.get("team", {})

    await update.message.reply_text(
        "⚽ TEAM FOUND\n\n"
        f"Team: {info.get('name', team_name)}\n"
        f"Country: {info.get('country', 'Unknown')}\n"
        f"Season: {FIXTURE_SEASON}"
    )


async def fixtures_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Usage:\n/fixtures Chelsea"
        )

        return

    team_name = " ".join(
        context.args
    )

    team = find_team(team_name)

    if not team:

        await update.message.reply_text(
            f"❌ Could not find {team_name}."
        )

        return

    info = team.get("team", {})

    fixtures = get_team_fixtures(
        info.get("id")
    )

    if not fixtures:

        await update.message.reply_text(
            "⚠️ No fixtures found."
        )

        return

    lines = [
        f"📅 {info.get('name', team_name)} "
        f"— {FIXTURE_SEASON} fixtures",
        ""
    ]

    count = 0

    for fixture in fixtures:

        if count >= 5:
            break

        teams = fixture.get(
            "teams",
            {}
        )

        home = (
            teams.get("home", {})
            .get("name", "")
        )

        away = (
            teams.get("away", {})
            .get("name", "")
        )

        date = (
            fixture.get("fixture", {})
            .get("date", "")
        )

        lines.append(
            f"⚽ {home} vs {away}"
        )

        lines.append(
            f"📅 {date[:10]}"
        )

        lines.append("")

        count += 1

    await update.message.reply_text(
        "\n".join(lines)
    )


async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if len(context.args) < 3:

        await update.message.reply_text(
            "Usage:\n"
            "/analyze Chelsea vs Arsenal"
        )

        return

    text = " ".join(
        context.args
    )

    parts = text.split(
        " vs ",
        1
    )

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

    try:

        result = analyze_match(
            home_name,
            away_name
        )

        await update.message.reply_text(
            result
        )

    except Exception as e:

        print(
            "ANALYSIS ERROR:",
            e
        )

        await update.message.reply_text(
            "❌ Analysis failed.\n"
            "Please try again."
        )


async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    parts = text.split(
        " vs ",
        1
    )

    if len(parts) == 2:

        home_name = parts[0].strip()
        away_name = parts[1].strip()

        await update.message.reply_text(
            "🔎 Analyzing historical data...\n"
            "Please wait."
        )

        try:

            result = analyze_match(
                home_name,
                away_name
            )

            await update.message.reply_text(
                result
            )

        except Exception as e:

            print(
                "TEXT ANALYSIS ERROR:",
                e
            )

            await update.message.reply_text(
                "❌ Analysis failed."
            )

        return

    await update.message.reply_text(
        "⚽ Send a match like:\n\n"
        "Chelsea vs Arsenal\n\n"
        "Or use:\n"
        "/analyze Chelsea vs Arsenal"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not TELEGRAM_BOT_TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN is missing."
        )

        return

    if not FOOTBALL_API_KEY:

        print(
            "❌ FOOTBALL_API_KEY is missing."
        )

        return

    health_thread = threading.Thread(
        target=run_health_server,
        daemon=True
    )

    health_thread.start()

    print(
        "Starting GoalLogic AI..."
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
            api_test_command
        )
    )

    application.add_handler(
        CommandHandler(
            "team",
            team_command
        )
    )

    application.add_handler(
        CommandHandler(
            "fixtures",
            fixtures_command
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
            text_handler
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
