import os
import time
import threading
import http.server
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
# SETTINGS
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")

API_BASE = "https://v3.football.api-sports.io"

# Your current API plan supports 2024
FIXTURE_SEASON = 2024

# Keep samples small to reduce API usage
SAMPLE_SIZE = 5
H2H_SAMPLE_SIZE = 5

# API protection
REQUEST_DELAY = 1.2
CACHE_TTL = 300  # 5 minutes

# ============================================================
# HEALTH SERVER FOR RENDER
# ============================================================

PORT = int(os.environ.get("PORT", 10000))


class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GoalLogic AI is running.")

    def log_message(self, format, *args):
        return


def start_health_server():
    server = http.server.HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


threading.Thread(target=start_health_server, daemon=True).start()

# ============================================================
# API STATE
# ============================================================

api_lock = threading.Lock()
last_api_request = 0

CACHE = {}

RATE_LIMITED = False


# ============================================================
# CACHE
# ============================================================

def cache_get(key):
    item = CACHE.get(key)

    if not item:
        return None

    timestamp, value = item

    if time.time() - timestamp > CACHE_TTL:
        del CACHE[key]
        return None

    return value


def cache_set(key, value):
    CACHE[key] = (time.time(), value)


# ============================================================
# FOOTBALL API
# ============================================================

def api_get(endpoint, params=None, retries=2):
    global last_api_request
    global RATE_LIMITED

    if not FOOTBALL_API_KEY:
        print("ERROR: FOOTBALL_API_KEY is missing.")
        return None

    params = params or {}

    cache_key = (
        endpoint,
        tuple(sorted((str(k), str(v)) for k, v in params.items()))
    )

    cached = cache_get(cache_key)

    if cached is not None:
        return cached

    headers = {
        "x-apisports-key": FOOTBALL_API_KEY
    }

    for attempt in range(retries + 1):

        try:
            with api_lock:

                elapsed = time.time() - last_api_request

                if elapsed < REQUEST_DELAY:
                    time.sleep(REQUEST_DELAY - elapsed)

                last_api_request = time.time()

                response = httpx.get(
                    API_BASE + endpoint,
                    headers=headers,
                    params=params,
                    timeout=20
                )

            print(
                f"API {endpoint} "
                f"status={response.status_code}"
            )

            # HTTP rate limit
            if response.status_code == 429:

                RATE_LIMITED = True

                if attempt < retries:
                    wait_time = 6 * (attempt + 1)

                    print(
                        f"Rate limit reached. "
                        f"Waiting {wait_time} seconds..."
                    )

                    time.sleep(wait_time)
                    continue

                print("API rate limit still active.")
                return None

            if response.status_code != 200:
                print(
                    "API ERROR:",
                    response.text[:500]
                )
                return None

            data = response.json()

            # API-Football sometimes returns rateLimit
            # inside a HTTP 200 response.
            errors = data.get("errors", {})

            if isinstance(errors, dict):

                if "rateLimit" in errors:

                    RATE_LIMITED = True

                    if attempt < retries:

                        wait_time = 6 * (attempt + 1)

                        print(
                            f"API rate limit detected. "
                            f"Waiting {wait_time} seconds..."
                        )

                        time.sleep(wait_time)
                        continue

                    print(
                        "API rate limit reached."
                    )

                    return None

                # Other API errors
                if errors:
                    print(
                        "API ERROR:",
                        errors
                    )
                    return None

            RATE_LIMITED = False

            cache_set(cache_key, data)

            return data

        except Exception as e:

            print(
                f"API request error: {e}"
            )

            if attempt < retries:
                time.sleep(3)
            else:
                return None

    return None


# ============================================================
# TEAM SEARCH
# ============================================================

def find_team(team_name):

    team_name = team_name.strip()

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

    # Exact name match first
    for item in teams:

        team = item.get("team", {})

        name = team.get("name", "")

        if name.lower() == team_name.lower():
            return team

    # Otherwise use first result
    return teams[0].get("team", {})


# ============================================================
# TEAM FIXTURES
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
# FINISHED MATCHES
# ============================================================

def is_finished(fixture):

    status = (
        fixture
        .get("fixture", {})
        .get("status", {})
        .get("short", "")
    )

    return status in {
        "FT",
        "AET",
        "PEN"
    }


def get_finished_fixtures(fixtures):

    finished = [
        f for f in fixtures
        if is_finished(f)
    ]

    finished.sort(
        key=lambda x: x.get("fixture", {}).get("date", ""),
        reverse=True
    )

    return finished


# ============================================================
# BASIC MATCH DATA
# ============================================================

def match_goals(fixture):

    goals = fixture.get("goals", {})

    home = goals.get("home")
    away = goals.get("away")

    if home is None or away is None:
        return None, None

    return home, away


def calculate_form(fixtures, team_id):

    wins = 0
    draws = 0
    losses = 0
    goals_for = 0
    goals_against = 0
    games = 0

    for fixture in fixtures:

        home_team = (
            fixture
            .get("teams", {})
            .get("home", {})
            .get("id")
        )

        away_team = (
            fixture
            .get("teams", {})
            .get("away", {})
            .get("id")
        )

        home_goals, away_goals = match_goals(fixture)

        if home_goals is None or away_goals is None:
            continue

        if team_id == home_team:

            goals_for += home_goals
            goals_against += away_goals

            if home_goals > away_goals:
                wins += 1
            elif home_goals == away_goals:
                draws += 1
            else:
                losses += 1

        elif team_id == away_team:

            goals_for += away_goals
            goals_against += home_goals

            if away_goals > home_goals:
                wins += 1
            elif away_goals == home_goals:
                draws += 1
            else:
                losses += 1

        games += 1

    if games == 0:
        return {
            "games": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "gf": 0,
            "ga": 0,
            "avg_gf": 0,
            "avg_ga": 0,
        }

    return {
        "games": games,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "gf": goals_for,
        "ga": goals_against,
        "avg_gf": goals_for / games,
        "avg_ga": goals_against / games,
    }


# ============================================================
# HOME / AWAY FILTERING
# ============================================================

def get_home_fixtures(fixtures, team_id):

    result = []

    for fixture in fixtures:

        home_id = (
            fixture
            .get("teams", {})
            .get("home", {})
            .get("id")
        )

        if home_id == team_id and is_finished(fixture):
            result.append(fixture)

    return result


def get_away_fixtures(fixtures, team_id):

    result = []

    for fixture in fixtures:

        away_id = (
            fixture
            .get("teams", {})
            .get("away", {})
            .get("id")
        )

        if away_id == team_id and is_finished(fixture):
            result.append(fixture)

    return result


# ============================================================
# H2H
# ============================================================

def get_h2h_fixtures(home_id, away_id):

    data = api_get(
        "/fixtures/headtohead",
        {
            "h2h": f"{home_id}-{away_id}",
            "last": H2H_SAMPLE_SIZE
        }
    )

    if not data:
        return []

    fixtures = data.get("response", [])

    return [
        f for f in fixtures
        if is_finished(f)
    ]


def calculate_h2h_stats(fixtures, home_id, away_id):

    if not fixtures:
        return {
            "games": 0,
            "home_wins": 0,
            "draws": 0,
            "away_wins": 0,
            "avg_goals": 0
        }

    home_wins = 0
    draws = 0
    away_wins = 0
    total_goals = 0
    games = 0

    for fixture in fixtures:

        h = (
            fixture
            .get("teams", {})
            .get("home", {})
            .get("id")
        )

        a = (
            fixture
            .get("teams", {})
            .get("away", {})
            .get("id")
        )

        hg, ag = match_goals(fixture)

        if hg is None or ag is None:
            continue

        total_goals += hg + ag
        games += 1

        if h == home_id:

            if hg > ag:
                home_wins += 1
            elif hg == ag:
                draws += 1
            else:
                away_wins += 1

        elif a == home_id:

            if ag > hg:
                home_wins += 1
            elif ag == hg:
                draws += 1
            else:
                away_wins += 1

    avg_goals = (
        total_goals / games
        if games
        else 0
    )

    return {
        "games": games,
        "home_wins": home_wins,
        "draws": draws,
        "away_wins": away_wins,
        "avg_goals": avg_goals
    }


# ============================================================
# DETAILED MATCH STATISTICS
# ============================================================

def extract_statistics(statistics):

    result = {
        "shots": 0,
        "shots_on_target": 0,
        "corners": 0,
        "yellow": 0,
        "red": 0
    }

    for item in statistics or []:

        name = str(
            item.get("type", "")
        ).lower()

        value = item.get("value")

        if value is None:
            continue

        try:
            value = int(value)
        except:
            continue

        if name == "total shots":
            result["shots"] = value

        elif name == "shots on goal":
            result["shots_on_target"] = value

        elif name == "corner kicks":
            result["corners"] = value

        elif name == "yellow cards":
            result["yellow"] = value

        elif name == "red cards":
            result["red"] = value

    return result


def get_fixture_statistics(fixture_id, team_id):

    data = api_get(
        "/fixtures/statistics",
        {
            "fixture": fixture_id,
            "team": team_id
        },
        retries=1
    )

    if not data:
        return None

    response = data.get("response", [])

    if not response:
        return None

    statistics = response[0].get(
        "statistics",
        []
    )

    return extract_statistics(statistics)


# ============================================================
# COLLECT LIMITED STATS
# ============================================================

def collect_team_match_stats(fixtures, team_id, maximum=2):

    results = []

    # Only use the two most recent relevant matches.
    for fixture in fixtures[:maximum]:

        fixture_id = (
            fixture
            .get("fixture", {})
            .get("id")
        )

        if not fixture_id:
            continue

        stats = get_fixture_statistics(
            fixture_id,
            team_id
        )

        if stats:
            results.append(stats)

        # Stop if API rate limit is active.
        if RATE_LIMITED:
            break

    return results


def average_stat(stats_list, key):

    values = [
        item.get(key, 0)
        for item in stats_list
        if item.get(key) is not None
    ]

    if not values:
        return None

    return sum(values) / len(values)


# ============================================================
# MARKET ANALYSIS
# ============================================================

def market_analysis(
    home_form,
    away_form,
    h2h_stats
):

    result = {}

    # Over 1.5
    avg_total = (
        home_form["avg_gf"]
        + home_form["avg_ga"]
        + away_form["avg_gf"]
        + away_form["avg_ga"]
    ) / 2

    result["Over 1.5"] = {
        "score": min(
            95,
            50 + avg_total * 12
        )
    }

    # Over 2.5
    result["Over 2.5"] = {
        "score": min(
            90,
            35 + avg_total * 10
        )
    }

    # Under 4.5
    result["Under 4.5"] = {
        "score": min(
            95,
            90 - max(0, avg_total - 2.5) * 12
        )
    }

    # Both teams to score
    btts_score = 40

    if home_form["avg_gf"] >= 1:
        btts_score += 15

    if away_form["avg_gf"] >= 1:
        btts_score += 15

    if home_form["avg_ga"] >= 1:
        btts_score += 10

    if away_form["avg_ga"] >= 1:
        btts_score += 10

    result["BTTS"] = {
        "score": min(90, btts_score)
    }

    # Draw
    draw_score = 30

    if home_form["draws"] >= 2:
        draw_score += 15

    if away_form["draws"] >= 2:
        draw_score += 15

    if h2h_stats["draws"] >= 1:
        draw_score += 15

    result["Draw"] = {
        "score": min(85, draw_score)
    }

    return result


# ============================================================
# SIGNAL ENGINE
# ============================================================

def signal_engine(
    home,
    away,
    home_form,
    away_form,
    h2h_stats,
    markets
):

    signals = []

    # Home win
    home_score = 50

    if home_form["wins"] > away_form["wins"]:
        home_score += 10

    if home_form["avg_gf"] > away_form["avg_gf"]:
        home_score += 10

    if home_form["avg_ga"] < away_form["avg_ga"]:
        home_score += 5

    signals.append(
        (
            "Home Win",
            min(home_score, 85)
        )
    )

    # Away win
    away_score = 50

    if away_form["wins"] > home_form["wins"]:
        away_score += 10

    if away_form["avg_gf"] > home_form["avg_gf"]:
        away_score += 10

    if away_form["avg_ga"] < home_form["avg_ga"]:
        away_score += 5

    signals.append(
        (
            "Away Win",
            min(away_score, 85)
        )
    )

    # Add market signals
    for market, info in markets.items():

        signals.append(
            (
                market,
                round(info["score"], 1)
            )
        )

    # H2H adjustment
    if h2h_stats["games"] > 0:

        if h2h_stats["draws"] >= 2:

            signals.append(
                (
                    "H2H Draw",
                    65
                )
            )

        if h2h_stats["avg_goals"] >= 3:

            signals.append(
                (
                    "H2H Over 2.5",
                    65
                )
            )

    signals.sort(
        key=lambda x: x[1],
        reverse=True
    )

    return signals


# ============================================================
# ANALYSIS
# ============================================================

def analyze_match(home_name, away_name):

    global RATE_LIMITED

    RATE_LIMITED = False

    home = find_team(home_name)

    if not home:
        return (
            f"❌ I couldn't find **{home_name}**.\n\n"
            "Try using the official team name."
        )

    away = find_team(away_name)

    if not away:
        return (
            f"❌ I couldn't find **{away_name}**.\n\n"
            "Try using the official team name."
        )

    home_id = home.get("id")
    away_id = away.get("id")

    home_real_name = home.get(
        "name",
        home_name
    )

    away_real_name = away.get(
        "name",
        away_name
    )

    # --------------------------------------------------------
    # FIXTURES
    # --------------------------------------------------------

    home_all = get_team_fixtures(home_id)
    away_all = get_team_fixtures(away_id)

    home_finished = get_finished_fixtures(
        home_all
    )

    away_finished = get_finished_fixtures(
        away_all
    )

    if not home_finished:
        return (
            f"❌ No completed {FIXTURE_SEASON} "
            f"fixtures found for {home_real_name}."
        )

    if not away_finished:
        return (
            f"❌ No completed {FIXTURE_SEASON} "
            f"fixtures found for {away_real_name}."
        )

    # Last five
    home_recent = home_finished[:SAMPLE_SIZE]
    away_recent = away_finished[:SAMPLE_SIZE]

    # Home / away samples
    home_home = get_home_fixtures(
        home_finished,
        home_id
    )[:SAMPLE_SIZE]

    away_away = get_away_fixtures(
        away_finished,
        away_id
    )[:SAMPLE_SIZE]

    # --------------------------------------------------------
    # FORM
    # --------------------------------------------------------

    home_form = calculate_form(
        home_recent,
        home_id
    )

    away_form = calculate_form(
        away_recent,
        away_id
    )

    home_home_form = calculate_form(
        home_home,
        home_id
    )

    away_away_form = calculate_form(
        away_away,
        away_id
    )

    # --------------------------------------------------------
    # H2H
    # --------------------------------------------------------

    h2h_fixtures = get_h2h_fixtures(
        home_id,
        away_id
    )

    h2h_stats = calculate_h2h_stats(
        h2h_fixtures,
        home_id,
        away_id
    )

    # --------------------------------------------------------
    # LIMITED DETAILED STATS
    # --------------------------------------------------------

    home_stats = collect_team_match_stats(
        home_home,
        home_id,
        maximum=2
    )

    away_stats = collect_team_match_stats(
        away_away,
        away_id,
        maximum=2
    )

    # --------------------------------------------------------
    # MARKET ANALYSIS
    # --------------------------------------------------------

    markets = market_analysis(
        home_home_form,
        away_away_form,
        h2h_stats
    )

    signals = signal_engine(
        home_real_name,
        away_real_name,
        home_home_form,
        away_away_form,
        h2h_stats,
        markets
    )

    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    lines = []

    lines.append(
        f"⚽ **{home_real_name} vs {away_real_name}**"
    )

    lines.append(
        f"📅 Historical season: **{FIXTURE_SEASON}**"
    )

    lines.append("")

    # Recent form
    lines.append("📊 **RECENT FORM**")

    lines.append(
        f"🏠 {home_real_name}: "
        f"{home_form['wins']}W "
        f"{home_form['draws']}D "
        f"{home_form['losses']}L"
    )

    lines.append(
        f"✈️ {away_real_name}: "
        f"{away_form['wins']}W "
        f"{away_form['draws']}D "
        f"{away_form['losses']}L"
    )

    lines.append("")

    # Home / away
    lines.append("🏟️ **HOME / AWAY FORM**")

    lines.append(
        f"🏠 {home_real_name} at home: "
        f"{home_home_form['wins']}W "
        f"{home_home_form['draws']}D "
        f"{home_home_form['losses']}L"
    )

    lines.append(
        f"✈️ {away_real_name} away: "
        f"{away_away_form['wins']}W "
        f"{away_away_form['draws']}D "
        f"{away_away_form['losses']}L"
    )

    lines.append("")

    # Goals
    lines.append("⚽ **GOAL AVERAGES**")

    lines.append(
        f"{home_real_name}: "
        f"{home_home_form['avg_gf']:.2f} scored / "
        f"{home_home_form['avg_ga']:.2f} conceded"
    )

    lines.append(
        f"{away_real_name}: "
        f"{away_away_form['avg_gf']:.2f} scored / "
        f"{away_away_form['avg_ga']:.2f} conceded"
    )

    lines.append("")

    # H2H
    lines.append("🔄 **HEAD-TO-HEAD**")

    if h2h_stats["games"] == 0:

        lines.append(
            "⚠️ No H2H data available."
        )

    else:

        lines.append(
            f"Games analysed: {h2h_stats['games']}"
        )

        lines.append(
            f"Home-side wins: "
            f"{h2h_stats['home_wins']}"
        )

        lines.append(
            f"Draws: "
            f"{h2h_stats['draws']}"
        )

        lines.append(
            f"Away-side wins: "
            f"{h2h_stats['away_wins']}"
        )

        lines.append(
            f"Average goals: "
            f"{h2h_stats['avg_goals']:.2f}"
        )

    lines.append("")

    # Detailed stats
    lines.append("📈 **MATCH STATISTICS**")

    home_shots = average_stat(
        home_stats,
        "shots"
    )

    away_shots = average_stat(
        away_stats,
        "shots"
    )

    home_target = average_stat(
        home_stats,
        "shots_on_target"
    )

    away_target = average_stat(
        away_stats,
        "shots_on_target"
    )

    home_corners = average_stat(
        home_stats,
        "corners"
    )

    away_corners = average_stat(
        away_stats,
        "corners"
    )

    if home_shots is None:
        lines.append(
            f"🏠 {home_real_name} shots: unavailable"
        )
    else:
        lines.append(
            f"🏠 {home_real_name} shots: "
            f"{home_shots:.1f}"
        )

    if away_shots is None:
        lines.append(
            f"✈️ {away_real_name} shots: unavailable"
        )
    else:
        lines.append(
            f"✈️ {away_real_name} shots: "
            f"{away_shots:.1f}"
        )

    if home_target is not None and away_target is not None:

        lines.append(
            f"🎯 Shots on target: "
            f"{home_target:.1f} - "
            f"{away_target:.1f}"
        )

    if home_corners is not None and away_corners is not None:

        lines.append(
            f"🚩 Corners: "
            f"{home_corners:.1f} - "
            f"{away_corners:.1f}"
        )

    lines.append("")

    # Markets
    lines.append("🎯 **MARKET ANALYSIS**")

    for market, info in markets.items():

        lines.append(
            f"{market}: "
            f"**{info['score']:.0f}% historical signal**"
        )

    lines.append("")

    # Signals
    lines.append("🤖 **SIGNAL ENGINE**")

    for market, score in signals[:5]:

        lines.append(
            f"• {market}: **{score:.0f}%**"
        )

    lines.append("")

    # Top signal
    if signals:

        top_market, top_score = signals[0]

        lines.append(
            f"🔥 **TOP HISTORICAL SIGNAL:** "
            f"{top_market} — {top_score:.0f}%"
        )

    lines.append("")

    # Data warning
    if RATE_LIMITED:

        lines.append(
            "⚠️ **DATA LIMIT:** "
            "The football API rate limit was reached. "
            "Some detailed statistics may be unavailable."
        )

    lines.append("")

    lines.append(
        "ℹ️ The signal score is based on historical "
        "form, goals, limited H2H information and "
        "available match statistics. It is not a guarantee "
        "of a future result."
    )

    return "\n".join(lines)


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = (
        "🤖 **GoalLogic AI is online!**\n\n"
        "Send a football match like:\n\n"
        "**Chelsea vs Arsenal**\n\n"
        "You can also use:\n"
        "/team Chelsea\n"
        "/fixtures Chelsea\n"
        "/analyze Chelsea vs Arsenal\n\n"
        f"📊 Historical data season: {FIXTURE_SEASON}"
    )

    await update.message.reply_text(
        message,
        parse_mode="Markdown"
    )


async def team_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "Use:\n/team Chelsea"
        )

        return

    team_name = " ".join(
        context.args
    )

    team = find_team(team_name)

    if not team:

        await update.message.reply_text(
            f"❌ I couldn't find {team_name}."
        )

        return

    await update.message.reply_text(
        f"⚽ {team.get('name')}\n"
        f"ID: {team.get('id')}\n"
        f"Country: {team.get('country', 'Unknown')}"
    )


async def fixtures_command(
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

    team = find_team(team_name)

    if not team:

        await update.message.reply_text(
            f"❌ I couldn't find {team_name}."
        )

        return

    fixtures = get_finished_fixtures(
        get_team_fixtures(
            team.get("id")
        )
    )

    fixtures = fixtures[:5]

    if not fixtures:

        await update.message.reply_text(
            "❌ No completed fixtures found."
        )

        return

    lines = [
        f"📅 **{team.get('name')}**",
        f"Historical season: {FIXTURE_SEASON}",
        ""
    ]

    for fixture in fixtures:

        teams = fixture.get(
            "teams",
            {}
        )

        home = teams.get(
            "home",
            {}
        ).get(
            "name",
            "Home"
        )

        away = teams.get(
            "away",
            {}
        ).get(
            "name",
            "Away"
        )

        hg, ag = match_goals(fixture)

        lines.append(
            f"• {home} {hg}-{ag} {away}"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown"
    )


async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Use:\n/analyze Chelsea vs Arsenal"
        )

        return

    text = " ".join(
        context.args
    )

    if " vs " in text.lower():

        parts = text.lower().split(" vs ", 1)

        home = parts[0].strip()
        away = parts[1].strip()

    elif " v " in text.lower():

        parts = text.lower().split(" v ", 1)

        home = parts[0].strip()
        away = parts[1].strip()

    else:

        await update.message.reply_text(
            "Please use:\n/analyze Chelsea vs Arsenal"
        )

        return

    await update.message.reply_text(
        "🔎 Analysing historical data...\n"
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


# ============================================================
# NORMAL MESSAGE
# ============================================================

async def normal_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    text = update.message.text.strip()

    lower = text.lower()

    if " vs " in lower:

        parts = lower.split(
            " vs ",
            1
        )

    elif " v " in lower:

        parts = lower.split(
            " v ",
            1
        )

    else:

        await update.message.reply_text(
            "Send a match like:\n\n"
            "Chelsea vs Arsenal"
        )

        return

    home = parts[0].strip()
    away = parts[1].strip()

    if not home or not away:

        await update.message.reply_text(
            "Please send a match like:\n\n"
            "Chelsea vs Arsenal"
        )

        return

    await update.message.reply_text(
        "🔎 Analysing...\n"
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


# ============================================================
# API TEST
# ============================================================

async def apitest_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not FOOTBALL_API_KEY:

        await update.message.reply_text(
            "❌ FOOTBALL_API_KEY is missing from Render."
        )

        return

    await update.message.reply_text(
        "🔧 Testing Football API..."
    )

    data = api_get(
        "/status"
    )

    if not data:

        await update.message.reply_text(
            "❌ Football API test failed.\n\n"
            "Check the Render logs."
        )

        return

    await update.message.reply_text(
        "✅ Football API connection is working."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not TELEGRAM_BOT_TOKEN:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN is missing."
        )

        return

    if not FOOTBALL_API_KEY:

        print(
            "ERROR: FOOTBALL_API_KEY is missing."
        )

        return

    print(
        "GoalLogic AI is starting..."
    )

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
        CommandHandler(
            "apitest",
            apitest_command
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            normal_message
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
