import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from statistics import mean

import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

PORT = int(os.getenv("PORT", "10000"))
OPENFOOT_BASE = "https://openfootapi.com"
CURRENT_SEASON = "2026/27"


# ============================================================
# HEALTH SERVER
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

    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    print(f"GoalLogic AI is running on port {PORT}.")

    server.serve_forever()


# ============================================================
# OPENFOOT
# ============================================================

def openfoot_headers():

    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {OPENFOOT_API_KEY}",
    }


def openfoot_get(endpoint, params=None):

    url = f"{OPENFOOT_BASE}{endpoint}"

    try:

        response = requests.get(
            url,
            headers=openfoot_headers(),
            params=params,
            timeout=20
        )

        print(
            "OpenFoot:",
            response.status_code,
            response.url
        )

        if response.status_code != 200:

            print(response.text)

            return None

        payload = response.json()

        if "error" in payload:

            print(payload["error"])

            return None

        return payload.get("data", [])

    except Exception as e:

        print("OpenFoot request error:", e)

        return None


# ============================================================
# TEAM SEARCH
# ============================================================

def search_team(name):

    results = openfoot_get(
        "/v1/search",
        {"q": name}
    )

    if not results:
        return None

    query = name.lower().strip()

    for team in results:

        team_name = str(
            team.get("name", "")
        ).lower().strip()

        if team_name == query:
            return team

    for team in results:

        team_name = str(
            team.get("name", "")
        ).lower()

        if (
            query in team_name
            or team_name in query
        ):
            return team

    return results[0]


# ============================================================
# SCORE
# ============================================================

def get_score(match):

    score = match.get("score")

    if isinstance(score, dict):

        home = score.get("home")
        away = score.get("away")

        if isinstance(home, dict):

            home = (
                home.get("current")
                or home.get("display")
                or home.get("goals")
            )

        if isinstance(away, dict):

            away = (
                away.get("current")
                or away.get("display")
                or away.get("goals")
            )

        if home is not None and away is not None:

            try:

                return int(home), int(away)

            except:

                pass

    home = (
        match.get("homeScore")
        or match.get("home_score")
    )

    away = (
        match.get("awayScore")
        or match.get("away_score")
    )

    if home is not None and away is not None:

        try:

            return int(home), int(away)

        except:

            pass

    return None


# ============================================================
# MATCH DATE
# ============================================================

def match_date(match):

    return str(
        match.get("kickoffAt")
        or match.get("date")
        or match.get("startTime")
        or match.get("scheduledAt")
        or ""
    )


# ============================================================
# GET MATCHES
# ============================================================

def get_team_matches(team_id):

    matches = openfoot_get(
        "/v1/matches",
        {
            "team": team_id,
            "season": CURRENT_SEASON
        }
    )

    if not matches:

        return []

    finished_statuses = {
        "finished",
        "completed",
        "complete",
        "ft",
        "ended",
        "full_time",
        "full-time",
        "full time",
        "final",
        "closed"
    }

    finished = []

    for match in matches:

        status = str(
            match.get("status", "")
        ).lower().strip()

        status_code = str(
            match.get("statusCode", "")
        ).lower().strip()

        score_exists = (
            get_score(match) is not None
        )

        is_finished = (
            status in finished_statuses
            or status_code in finished_statuses
            or score_exists
        )

        if is_finished:

            finished.append(match)

    finished.sort(
        key=match_date,
        reverse=True
    )

    print(
        f"Team {team_id}: "
        f"{len(finished)} completed matches found."
    )

    return finished


# ============================================================
# TEAM RECORD
# ============================================================

def build_record(match, team_id):

    home = match.get("home") or {}
    away = match.get("away") or {}

    home_id = (
        home.get("id")
        or home.get("teamId")
    )

    away_id = (
        away.get("id")
        or away.get("teamId")
    )

    score = get_score(match)

    if not score:

        return None

    home_goals, away_goals = score

    if str(home_id) == str(team_id):

        venue = "home"

        gf = home_goals
        ga = away_goals

    elif str(away_id) == str(team_id):

        venue = "away"

        gf = away_goals
        ga = home_goals

    else:

        return None

    if gf > ga:

        result = "W"

    elif gf == ga:

        result = "D"

    else:

        result = "L"

    return {
        "date": match_date(match),
        "venue": venue,
        "gf": gf,
        "ga": ga,
        "total": gf + ga,
        "result": result
    }


# ============================================================
# STATISTICS
# ============================================================

def stats(records):

    if not records:

        return {
            "sample": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "gf": 0,
            "ga": 0,
            "avg_gf": 0,
            "avg_ga": 0,
            "avg_total": 0,
            "over05": 0,
            "over15": 0,
            "over25": 0,
            "under35": 0,
            "btts": 0,
            "scoring": 0,
            "clean": 0,
            "conceding": 0,
            "two_four": 0
        }

    n = len(records)

    totals = [
        r["total"]
        for r in records
    ]

    gf = [
        r["gf"]
        for r in records
    ]

    ga = [
        r["ga"]
        for r in records
    ]

    return {

        "sample": n,

        "wins": sum(
            r["result"] == "W"
            for r in records
        ),

        "draws": sum(
            r["result"] == "D"
            for r in records
        ),

        "losses": sum(
            r["result"] == "L"
            for r in records
        ),

        "gf": sum(gf),

        "ga": sum(ga),

        "avg_gf": mean(gf),

        "avg_ga": mean(ga),

        "avg_total": mean(totals),

        "over05": 100 * sum(
            x >= 1 for x in totals
        ) / n,

        "over15": 100 * sum(
            x >= 2 for x in totals
        ) / n,

        "over25": 100 * sum(
            x >= 3 for x in totals
        ) / n,

        "under35": 100 * sum(
            x <= 3 for x in totals
        ) / n,

        "btts": 100 * sum(
            r["gf"] > 0 and r["ga"] > 0
            for r in records
        ) / n,

        "scoring": 100 * sum(
            r["gf"] > 0
            for r in records
        ) / n,

        "clean": 100 * sum(
            r["ga"] == 0
            for r in records
        ) / n,

        "conceding": 100 * sum(
            r["ga"] > 0
            for r in records
        ) / n,

        "two_four": 100 * sum(
            2 <= x <= 4
            for x in totals
        ) / n
    }


# ============================================================
# CONFIDENCE
# ============================================================

def reliability(sample):

    if sample >= 5:
        return 90

    if sample >= 3:
        return 75

    if sample >= 2:
        return 60

    return 40


def market_confidence(
    s1,
    s2,
    v1,
    v2,
    key
):

    overall = (
        s1[key] + s2[key]
    ) / 2

    venue = (
        v1[key] + v2[key]
    ) / 2

    rel = (
        reliability(v1["sample"])
        + reliability(v2["sample"])
    ) / 2

    agreement = 100 - abs(
        s1[key] - s2[key]
    )

    confidence = (
        overall * 0.45
        + venue * 0.25
        + agreement * 0.10
        + rel * 0.20
    )

    # Under 3.5 counter-signal
    if key == "under35":

        over_signal = (
            s1["over25"]
            + s2["over25"]
        ) / 2

        if over_signal >= 70:

            confidence -= 8

    # Over 2.5 counter-signal
    if key == "over25":

        under_signal = (
            s1["under35"]
            + s2["under35"]
        ) / 2

        if under_signal >= 80:

            confidence -= 7

    # BTTS clean-sheet counter
    if key == "btts":

        clean_signal = (
            v1["clean"]
            + v2["clean"]
        ) / 2

        if clean_signal >= 60:

            confidence -= 8

    # Small venue samples
    if min(
        v1["sample"],
        v2["sample"]
    ) < 2:

        confidence = min(
            confidence,
            72
        )

    elif min(
        v1["sample"],
        v2["sample"]
    ) < 3:

        confidence = min(
            confidence,
            78
        )

    return round(
        max(
            0,
            min(90, confidence)
        )
    )


def scoring_confidence(
    team,
    venue,
    opponent,
    opponent_venue
):

    value = (
        team["scoring"] * 0.35
        + venue["scoring"] * 0.25
        + opponent["conceding"] * 0.20
        + opponent_venue["conceding"] * 0.10
        + reliability(
            venue["sample"]
        ) * 0.10
    )

    if opponent_venue["clean"] >= 67:

        value -= 7

    return round(
        max(
            0,
            min(90, value)
        )
    )


def btts_confidence(
    s1,
    s2,
    v1,
    v2
):

    value = (
        ((s1["scoring"] + s2["scoring"]) / 2)
        * 0.25
        +
        ((s1["conceding"] + s2["conceding"]) / 2)
        * 0.20
        +
        ((v1["btts"] + v2["btts"]) / 2)
        * 0.30
        +
        (100 - ((v1["clean"] + v2["clean"]) / 2))
        * 0.15
        +
        ((reliability(v1["sample"])
          + reliability(v2["sample"])) / 2)
        * 0.10
    )

    if (
        v1["clean"] + v2["clean"]
    ) / 2 >= 60:

        value -= 8

    return round(
        max(
            0,
            min(90, value)
        )
    )


# ============================================================
# GRADING
# ============================================================

def grade(c):

    if c >= 80:
        return "🔥 STRONG"

    if c >= 70:
        return "🟢 GOOD"

    if c >= 60:
        return "🟡 MODERATE"

    return "🔴 AVOID"


def advice(c):

    if c >= 70:
        return "BET"

    if c >= 60:
        return "CAUTION"

    return "AVOID"


# ============================================================
# ANALYSIS
# ============================================================

def analyze(team1_name, team2_name):

    team1 = search_team(team1_name)
    team2 = search_team(team2_name)

    if not team1:

        return f"❌ I couldn't find {team1_name}."

    if not team2:

        return f"❌ I couldn't find {team2_name}."

    id1 = team1.get("id") or team1.get("teamId")
    id2 = team2.get("id") or team2.get("teamId")

    matches1 = get_team_matches(id1)
    matches2 = get_team_matches(id2)

    records1 = [
        r
        for r in (
            build_record(m, id1)
            for m in matches1
        )
        if r
    ]

    records2 = [
        r
        for r in (
            build_record(m, id2)
            for m in matches2
        )
        if r
    ]

    print(
        "Records:",
        len(records1),
        len(records2)
    )

    if len(records1) < 2:

        return (
            f"⚠️ OpenFoot returned only "
            f"{len(records1)} usable completed "
            f"matches for {team1_name}."
        )

    if len(records2) < 2:

        return (
            f"⚠️ OpenFoot returned only "
            f"{len(records2)} usable completed "
            f"matches for {team2_name}."
        )

    recent1 = records1[:5]
    recent2 = records2[:5]

    home1 = [
        r for r in records1
        if r["venue"] == "home"
    ][:5]

    away2 = [
        r for r in records2
        if r["venue"] == "away"
    ][:5]

    s1 = stats(recent1)
    s2 = stats(recent2)

    v1 = stats(home1)
    v2 = stats(away2)

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    markets = {}

    markets["Over 0.5 Goals"] = market_confidence(
        s1, s2, v1, v2, "over05"
    )

    markets["Over 1.5 Goals"] = market_confidence(
        s1, s2, v1, v2, "over15"
    )

    markets["Over 2.5 Goals"] = market_confidence(
        s1, s2, v1, v2, "over25"
    )

    markets["Under 3.5 Goals"] = market_confidence(
        s1, s2, v1, v2, "under35"
    )

    markets["BTTS — Yes"] = btts_confidence(
        s1, s2, v1, v2
    )

    name1 = team1.get(
        "name",
        team1_name
    )

    name2 = team2.get(
        "name",
        team2_name
    )

    markets[
        f"{name1} to Score"
    ] = scoring_confidence(
        s1,
        v1,
        s2,
        v2
    )

    markets[
        f"{name2} to Score"
    ] = scoring_confidence(
        s2,
        v2,
        s1,
        v1
    )

    markets["2–4 Total Goals"] = market_confidence(
        s1,
        s2,
        v1,
        v2,
        "two_four"
    )

    # --------------------------------------------------------
    # PRIMARY SIGNAL
    # --------------------------------------------------------

    preferred = [
        "Over 1.5 Goals",
        "Over 2.5 Goals",
        "Under 3.5 Goals",
        "BTTS — Yes",
        f"{name1} to Score",
        f"{name2} to Score",
        "2–4 Total Goals"
    ]

    candidates = {
        k: v
        for k, v in markets.items()
        if k in preferred and v >= 60
    }

    if candidates:

        primary = max(
            candidates,
            key=candidates.get
        )

    else:

        primary = "Over 0.5 Goals"

    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    out = []

    out.append(
        "⚽ GOALLOGIC AI — ADVANCED ANALYSIS"
    )

    out.append("")

    out.append(
        f"{name1} vs {name2}"
    )

    out.append(
        f"Season: {CURRENT_SEASON}"
    )

    out.append("")

    # Team 1
    out.append(
        f"📊 {name1.upper()} — LAST 5"
    )

    out.append(
        f"Form: "
        f"{''.join(r['result'] for r in recent1)}"
    )

    out.append(
        f"W/D/L: "
        f"{s1['wins']}/{s1['draws']}/{s1['losses']}"
    )

    out.append(
        f"Goals scored: {s1['gf']}"
    )

    out.append(
        f"Goals conceded: {s1['ga']}"
    )

    out.append(
        f"Avg scored: {s1['avg_gf']:.1f}"
    )

    out.append(
        f"Avg conceded: {s1['avg_ga']:.1f}"
    )

    out.append(
        f"Avg total goals: {s1['avg_total']:.1f}"
    )

    out.append(
        f"Over 0.5: {s1['over05']:.0f}%"
    )

    out.append(
        f"Over 1.5: {s1['over15']:.0f}%"
    )

    out.append(
        f"Over 2.5: {s1['over25']:.0f}%"
    )

    out.append(
        f"Under 3.5: {s1['under35']:.0f}%"
    )

    out.append(
        f"BTTS: {s1['btts']:.0f}%"
    )

    out.append(
        f"Scoring consistency: {s1['scoring']:.0f}%"
    )

    out.append(
        f"Clean sheets: {s1['clean']:.0f}%"
    )

    out.append(
        f"Sample: {s1['sample']} matches"
    )

    out.append("")

    # Home
    out.append(
        f"🏠 {name1.upper()} — RECENT HOME"
    )

    out.append(
        f"Form: "
        f"{''.join(r['result'] for r in home1)}"
    )

    out.append(
        f"Avg scored: {v1['avg_gf']:.1f}"
    )

    out.append(
        f"Avg conceded: {v1['avg_ga']:.1f}"
    )

    out.append(
        f"Over 1.5: {v1['over15']:.0f}%"
    )

    out.append(
        f"Over 2.5: {v1['over25']:.0f}%"
    )

    out.append(
        f"Under 3.5: {v1['under35']:.0f}%"
    )

    out.append(
        f"BTTS: {v1['btts']:.0f}%"
    )

    out.append(
        f"Scoring: {v1['scoring']:.0f}%"
    )

    out.append(
        f"Clean sheets: {v1['clean']:.0f}%"
    )

    out.append(
        f"Sample: {v1['sample']} matches"
    )

    if v1["sample"] < 3:

        out.append(
            "⚠️ Small home sample."
        )

    out.append("")

    # Team 2
    out.append(
        f"📊 {name2.upper()} — LAST 5"
    )

    out.append(
        f"Form: "
        f"{''.join(r['result'] for r in recent2)}"
    )

    out.append(
        f"W/D/L: "
        f"{s2['wins']}/{s2['draws']}/{s2['losses']}"
    )

    out.append(
        f"Goals scored: {s2['gf']}"
    )

    out.append(
        f"Goals conceded: {s2['ga']}"
    )

    out.append(
        f"Avg scored: {s2['avg_gf']:.1f}"
    )

    out.append(
        f"Avg conceded: {s2['avg_ga']:.1f}"
    )

    out.append(
        f"Avg total goals: {s2['avg_total']:.1f}"
    )

    out.append(
        f"Over 0.5: {s2['over05']:.0f}%"
    )

    out.append(
        f"Over 1.5: {s2['over15']:.0f}%"
    )

    out.append(
        f"Over 2.5: {s2['over25']:.0f}%"
    )

    out.append(
        f"Under 3.5: {s2['under35']:.0f}%"
    )

    out.append(
        f"BTTS: {s2['btts']:.0f}%"
    )

    out.append(
        f"Scoring consistency: {s2['scoring']:.0f}%"
    )

    out.append(
        f"Clean sheets: {s2['clean']:.0f}%"
    )

    out.append(
        f"Sample: {s2['sample']} matches"
    )

    out.append("")

    # Away
    out.append(
        f"✈️ {name2.upper()} — RECENT AWAY"
    )

    out.append(
        f"Form: "
        f"{''.join(r['result'] for r in away2)}"
    )

    out.append(
        f"Avg scored: {v2['avg_gf']:.1f}"
    )

    out.append(
        f"Avg conceded: {v2['avg_ga']:.1f}"
    )

    out.append(
        f"Over 1.5: {v2['over15']:.0f}%"
    )

    out.append(
        f"Over 2.5: {v2['over25']:.0f}%"
    )

    out.append(
        f"Under 3.5: {v2['under35']:.0f}%"
    )

    out.append(
        f"BTTS: {v2['btts']:.0f}%"
    )

    out.append(
        f"Scoring: {v2['scoring']:.0f}%"
    )

    out.append(
        f"Clean sheets: {v2['clean']:.0f}%"
    )

    out.append(
        f"Sample: {v2['sample']} matches"
    )

    if v2["sample"] < 3:

        out.append(
            "⚠️ Small away sample."
        )

    out.append("")

    # Goal environment
    combined = (
        s1["avg_total"]
        + s2["avg_total"]
    ) / 2

    if combined >= 3:
        environment = "🔥 HIGH"

    elif combined >= 2.3:
        environment = "🟡 MODERATE"

    else:
        environment = "🛡️ LOW"

    out.append(
        "🎯 GOAL INTELLIGENCE"
    )

    out.append(
        f"Combined goal environment: "
        f"{combined:.2f}"
    )

    out.append(
        f"Goal environment: {environment}"
    )

    out.append("")

    # Markets
    out.append(
        "📊 MARKET SIGNALS"
    )

    out.append("")

    for market, confidence in markets.items():

        out.append(
            f"{market} — "
            f"Confidence {confidence}%"
        )

        out.append(
            f"Grade: {grade(confidence)}"
        )

        out.append(
            f"Advice: {advice(confidence)}"
        )

        out.append("")

    # Primary
    out.append(
        "⭐ PRIMARY STATISTICAL SIGNAL"
    )

    out.append(
        f"{primary} — "
        f"Confidence {markets[primary]}%"
    )

    out.append(
        f"Grade: {grade(markets[primary])}"
    )

    out.append(
        f"Advice: {advice(markets[primary])}"
    )

    out.append("")

    # Data quality
    out.append(
        "🔎 DATA QUALITY"
    )

    out.append(
        f"{name1}: "
        f"{s1['sample']} recent matches; "
        f"{v1['sample']} home matches."
    )

    out.append(
        f"{name2}: "
        f"{s2['sample']} recent matches; "
        f"{v2['sample']} away matches."
    )

    if (
        v1["sample"] < 3
        or v2["sample"] < 3
    ):

        out.append(
            "⚠️ Venue samples are limited, "
            "so venue data receives less weight."
        )

    out.append("")

    out.append(
        "⚠️ Statistical analysis is not a guarantee "
        "of the match outcome."
    )

    return "\n".join(out)


# ============================================================
# TELEGRAM
# ============================================================

async def start(update, context):

    await update.message.reply_text(
        "⚽ Welcome to GoalLogic AI!\n\n"
        "Send a match like:\n\n"
        "Chelsea vs Arsenal"
    )


async def apitest(update, context):

    result = openfoot_get(
        "/v1/search",
        {"q": "Chelsea"}
    )

    if result:

        await update.message.reply_text(
            "✅ OPENFOOT TEST PASSED\n\n"
            "OpenFoot API is connected successfully."
        )

    else:

        await update.message.reply_text(
            "❌ OPENFOOT TEST FAILED."
        )


async def analyze_command(update, context):

    if not context.args:

        await update.message.reply_text(
            "Use:\n"
            "/analyze Chelsea vs Arsenal"
        )

        return

    text = " ".join(
        context.args
    )

    await process_match(
        update,
        text
    )


async def process_match(update, text):

    pattern = re.compile(
        r"^\s*(.+?)\s+(?:vs\.?|v\.?)\s+(.+?)\s*$",
        re.IGNORECASE
    )

    match = pattern.match(text)

    if not match:

        await update.message.reply_text(
            "⚽ Send a match like:\n\n"
            "Chelsea vs Arsenal"
        )

        return

    team1 = match.group(1).strip()
    team2 = match.group(2).strip()

    await update.message.reply_text(
        "🔎 Analyzing...\n\n"
        f"{team1} vs {team2}"
    )

    try:

        result = analyze(
            team1,
            team2
        )

        await update.message.reply_text(
            result
        )

    except Exception as e:

        print(
            "Analysis error:",
            e
        )

        await update.message.reply_text(
            "❌ Analysis error occurred.\n"
            "Please try again."
        )


async def message_handler(
    update,
    context
):

    if not update.message:
        return

    text = (
        update.message.text
        or ""
    ).strip()

    if re.search(
        r"\s+(?:vs\.?|v\.?)\s+",
        text,
        re.IGNORECASE
    ):

        await process_match(
            update,
            text
        )

    else:

        await update.message.reply_text(
            "⚽ Send a match like:\n\n"
            "Chelsea vs Arsenal"
        )


# ============================================================
# START
# ============================================================

def main():

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not OPENFOOT_API_KEY:

        raise RuntimeError(
            "OPENFOOT_API_KEY is missing."
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
            filters.TEXT
            & ~filters.COMMAND,
            message_handler
        )
    )

    print(
        "GoalLogic AI is live."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
