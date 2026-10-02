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
    ContextTypes,
    MessageHandler,
    filters,
)


# ============================================================
# CONFIGURATION
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

OPENFOOT_BASE = "https://openfootapi.com"
CURRENT_SEASON = "2026/27"

RECENT_MATCHES = 5
MAX_CONFIDENCE = 85
MIN_CONFIDENCE = 50


# ============================================================
# RENDER HEALTH SERVER
# ============================================================

PORT = int(os.getenv("PORT", "10000"))


class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GoalLogic AI is running")

    def log_message(self, format, *args):
        return


def start_health_server():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


# ============================================================
# OPENFOOT API
# ============================================================

def openfoot_get(endpoint, params=None):
    url = OPENFOOT_BASE + endpoint

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {OPENFOOT_API_KEY}",
    }

    response = requests.get(
        url,
        headers=headers,
        params=params or {},
        timeout=20,
    )

    try:
        body = response.json()
    except Exception:
        body = {}

    if response.status_code != 200:
        error = body.get("error", {})
        message = error.get(
            "message",
            f"OpenFoot HTTP {response.status_code}"
        )
        raise RuntimeError(message)

    return body


# ============================================================
# TEAM SEARCH
# ============================================================

def normalize_name(name):
    name = name.lower().strip()

    replacements = {
        "fc": "",
        "afc": "",
        "cf": "",
        "sc": "",
        "club": "",
        "football club": "",
    }

    for old, new in replacements.items():
        name = name.replace(old, new)

    name = re.sub(r"[^a-z0-9 ]", "", name)
    name = re.sub(r"\s+", " ", name)

    return name.strip()


def search_team(team_name):
    body = openfoot_get(
        "/v1/search",
        {
            "q": team_name
        }
    )

    results = body.get("data", [])

    if not isinstance(results, list):
        return None

    target = normalize_name(team_name)

    # Exact normalized name
    for item in results:
        name = item.get("name", "")

        if normalize_name(name) == target:
            return item

    # Partial match
    for item in results:
        name = normalize_name(item.get("name", ""))

        if target in name or name in target:
            return item

    return None


# ============================================================
# MATCH PARSING
# ============================================================

def get_score(match):
    score = match.get("score")

    if isinstance(score, dict):
        home = score.get("home")
        away = score.get("away")

        if isinstance(home, (int, float)) and isinstance(
            away, (int, float)
        ):
            return int(home), int(away)

        home = score.get("homeGoals")
        away = score.get("awayGoals")

        if isinstance(home, (int, float)) and isinstance(
            away, (int, float)
        ):
            return int(home), int(away)

    home = match.get("homeScore")
    away = match.get("awayScore")

    if isinstance(home, (int, float)) and isinstance(
        away, (int, float)
    ):
        return int(home), int(away)

    return None


def team_side(match, team_id):
    home_team = match.get("homeTeam", {})
    away_team = match.get("awayTeam", {})

    if home_team.get("id") == team_id:
        return "home"

    if away_team.get("id") == team_id:
        return "away"

    return None


# ============================================================
# RECENT MATCHES
# ============================================================

def get_recent_matches(team_id):
    body = openfoot_get(
        "/v1/matches",
        {
            "team": team_id,
            "season": CURRENT_SEASON,
            "status": "finished",
        }
    )

    matches = body.get("data", [])

    if not isinstance(matches, list):
        return []

    usable = []

    for match in matches:
        score = get_score(match)

        if score is None:
            continue

        side = team_side(match, team_id)

        if side is None:
            continue

        home_goals, away_goals = score

        if side == "home":
            gf = home_goals
            ga = away_goals
        else:
            gf = away_goals
            ga = home_goals

        usable.append({
            "match": match,
            "side": side,
            "gf": gf,
            "ga": ga,
            "total": gf + ga,
            "btts": gf > 0 and ga > 0,
        })

    # OpenFoot normally returns newest first.
    # Sorting by kickoff keeps the newest five consistent.
    usable.sort(
        key=lambda x: x["match"].get(
            "kickoffAt",
            ""
        ),
        reverse=True
    )

    return usable[:RECENT_MATCHES]


# ============================================================
# STATISTICS
# ============================================================

def calculate_stats(matches):
    if not matches:
        return None

    gf = [m["gf"] for m in matches]
    ga = [m["ga"] for m in matches]
    total = [m["total"] for m in matches]

    wins = sum(m["gf"] > m["ga"] for m in matches)
    draws = sum(m["gf"] == m["ga"] for m in matches)
    losses = sum(m["gf"] < m["ga"] for m in matches)

    return {
        "sample": len(matches),

        "wins": wins,
        "draws": draws,
        "losses": losses,

        "wd_rate": (wins + draws) / len(matches) * 100,
        "draw_rate": draws / len(matches) * 100,

        "gf": sum(gf),
        "ga": sum(ga),

        "avg_scored": mean(gf),
        "avg_conceded": mean(ga),
        "avg_total": mean(total),

        "over05": sum(x >= 1 for x in total)
        / len(matches) * 100,

        "over15": sum(x >= 2 for x in total)
        / len(matches) * 100,

        "over25": sum(x >= 3 for x in total)
        / len(matches) * 100,

        "under35": sum(x <= 3 for x in total)
        / len(matches) * 100,

        "btts": sum(m["btts"] for m in matches)
        / len(matches) * 100,

        "scoring": sum(m["gf"] > 0 for m in matches)
        / len(matches) * 100,

        "clean_sheet": sum(m["ga"] == 0 for m in matches)
        / len(matches) * 100,
    }


# ============================================================
# VENUE STATISTICS
# ============================================================

def venue_stats(matches, venue):
    selected = [
        m for m in matches
        if m["side"] == venue
    ]

    if not selected:
        return {
            "sample": 0,
            "scoring": None,
            "over25": None,
            "btts": None,
            "wd": None,
        }

    return {
        "sample": len(selected),

        "scoring":
            sum(m["gf"] > 0 for m in selected)
            / len(selected) * 100,

        "over25":
            sum(m["total"] >= 3 for m in selected)
            / len(selected) * 100,

        "btts":
            sum(m["btts"] for m in selected)
            / len(selected) * 100,

        "wd":
            sum(m["gf"] >= m["ga"] for m in selected)
            / len(selected) * 100,
    }


# ============================================================
# CONFIDENCE ENGINE
# ============================================================

def sample_weight(sample):
    if sample <= 0:
        return 0.30

    if sample == 1:
        return 0.45

    if sample == 2:
        return 0.60

    if sample == 3:
        return 0.75

    if sample == 4:
        return 0.90

    return 1.00


def confidence(
    base,
    supports=0,
    contradictions=0,
    sample=5,
):
    """
    Central confidence engine.

    IMPORTANT:
    Every market uses this same function.

    The model:
    1. Starts with the raw statistical base.
    2. Pulls small samples toward 50.
    3. Rewards supporting evidence.
    4. Penalizes contradictory evidence.
    5. Caps confidence at 85%.
    """

    weight = sample_weight(sample)

    # Conservative shrinkage toward 50%.
    adjusted = 50 + ((base - 50) * 0.55 * weight)

    # Supporting evidence.
    adjusted += supports * 1.50

    # Contradictory evidence.
    adjusted -= contradictions * 2.00

    return round(
        max(
            MIN_CONFIDENCE,
            min(MAX_CONFIDENCE, adjusted)
        )
    )


def grade(value):
    if value >= 78:
        return "🔥 STRONG"

    if value >= 68:
        return "🟢 GOOD"

    if value >= 58:
        return "🟡 MODERATE"

    return "🔴 WEAK"


def advice(value):
    if value >= 68:
        return "BET"

    if value >= 58:
        return "CAUTION"

    return "AVOID"


def market_line(name, value):
    return (
        f"{name} — Confidence {value}%\n"
        f"Grade: {grade(value)}\n"
        f"Advice: {advice(value)}"
    )


# ============================================================
# MARKET CALCULATIONS
# ============================================================

def calculate_markets(team1, team2, home_context, away_context):
    s1 = team1["stats"]
    s2 = team2["stats"]

    # --------------------------------------------------------
    # DOUBLE CHANCE
    # --------------------------------------------------------

    one_x_base = (
        s1["wd_rate"] * 0.55
        + s2["losses"] / s2["sample"] * 100 * 0.25
        + (home_context["wd"] or 50) * 0.20
    )

    x2_base = (
        s2["wd_rate"] * 0.55
        + s1["losses"] / s1["sample"] * 100 * 0.25
        + (100 - (home_context["wd"] or 50)) * 0.20
    )

    # Either team wins.
    no_draw_base = (
        (100 - s1["draw_rate"]) * 0.50
        + (100 - s2["draw_rate"]) * 0.50
    )

    # Venue contradiction checks.
    one_x_contradictions = 0

    if home_context["sample"] >= 2:
        if home_context["wd"] is not None:
            if home_context["wd"] < 50:
                one_x_contradictions += 1

    x2_contradictions = 0

    if away_context["sample"] >= 2:
        if away_context["wd"] is not None:
            if away_context["wd"] < 50:
                x2_contradictions += 1

    one_x = confidence(
        one_x_base,
        supports=1 if s1["wd_rate"] >= 80 else 0,
        contradictions=one_x_contradictions,
        sample=s1["sample"],
    )

    x2 = confidence(
        x2_base,
        supports=1 if s2["wd_rate"] >= 80 else 0,
        contradictions=x2_contradictions,
        sample=s2["sample"],
    )

    twelve = confidence(
        no_draw_base,
        supports=1 if (
            s1["draw_rate"] <= 20
            and s2["draw_rate"] <= 20
        ) else 0,
        contradictions=1 if (
            s1["draw_rate"] >= 40
            or s2["draw_rate"] >= 40
        ) else 0,
        sample=min(
            s1["sample"],
            s2["sample"]
        ),
    )

    # --------------------------------------------------------
    # GOALS
    # --------------------------------------------------------

    over05_base = (
        s1["over05"] * 0.50
        + s2["over05"] * 0.50
    )

    over15_base = (
        s1["over15"] * 0.50
        + s2["over15"] * 0.50
    )

    over25_base = (
        s1["over25"] * 0.50
        + s2["over25"] * 0.50
    )

    under35_base = (
        s1["under35"] * 0.50
        + s2["under35"] * 0.50
    )

    over05 = confidence(
        over05_base,
        supports=1 if (
            s1["over05"] >= 80
            and s2["over05"] >= 80
        ) else 0,
        contradictions=1 if (
            (home_context["sample"] >= 2
             and home_context["over25"] == 0)
            or
            (away_context["sample"] >= 2
             and away_context["over25"] == 0)
        ) else 0,
        sample=min(
            s1["sample"],
            s2["sample"]
        ),
    )

    over15 = confidence(
        over15_base,
        supports=1 if (
            s1["avg_total"] >= 2.5
            and s2["avg_total"] >= 2.5
        ) else 0,
        contradictions=1 if (
            s1["avg_total"] < 2
            or s2["avg_total"] < 2
        ) else 0,
        sample=min(
            s1["sample"],
            s2["sample"]
        ),
    )

    over25 = confidence(
        over25_base,
        supports=1 if (
            s1["over25"] >= 70
            and s2["over25"] >= 70
        ) else 0,
        contradictions=1 if (
            s1["over25"] <= 40
            or s2["over25"] <= 40
        ) else 0,
        sample=min(
            s1["sample"],
            s2["sample"]
        ),
    )

    under35 = confidence(
        under35_base,
        supports=1 if (
            s1["under35"] >= 70
            and s2["under35"] >= 70
        ) else 0,
        contradictions=1 if (
            s1["avg_total"] >= 3.2
            or s2["avg_total"] >= 3.2
        ) else 0,
        sample=min(
            s1["sample"],
            s2["sample"]
        ),
    )

    # --------------------------------------------------------
    # BTTS
    # --------------------------------------------------------

    btts_base = (
        s1["btts"] * 0.50
        + s2["btts"] * 0.50
    )

    btts_contradictions = 0

    if home_context["sample"] >= 2:
        if home_context["btts"] == 0:
            btts_contradictions += 1

    if away_context["sample"] >= 2:
        if away_context["btts"] == 0:
            btts_contradictions += 1

    btts = confidence(
        btts_base,
        supports=1 if (
            s1["btts"] >= 60
            and s2["btts"] >= 60
        ) else 0,
        contradictions=btts_contradictions,
        sample=min(
            s1["sample"],
            s2["sample"]
        ),
    )

    # --------------------------------------------------------
    # TEAM TO SCORE
    # --------------------------------------------------------

    # Team 1 scoring:
    # Own scoring + opponent failure to keep clean sheets.
    team1_base = (
        s1["scoring"] * 0.60
        + (100 - s2["clean_sheet"]) * 0.40
    )

    team1_contradictions = 0

    if home_context["sample"] >= 2:
        if home_context["scoring"] == 0:
            team1_contradictions += 1

    if s2["clean_sheet"] >= 60:
        team1_contradictions += 1

    team1_score = confidence(
        team1_base,
        supports=1 if s1["scoring"] >= 80 else 0,
        contradictions=team1_contradictions,
        sample=s1["sample"],
    )

    # Team 2 scoring.
    team2_base = (
        s2["scoring"] * 0.60
        + (100 - s1["clean_sheet"]) * 0.40
    )

    team2_contradictions = 0

    if away_context["sample"] >= 2:
        if away_context["scoring"] == 0:
            team2_contradictions += 1

    if s1["clean_sheet"] >= 60:
        team2_contradictions += 1

    team2_score = confidence(
        team2_base,
        supports=1 if s2["scoring"] >= 80 else 0,
        contradictions=team2_contradictions,
        sample=s2["sample"],
    )

    return {
        "1X": one_x,
        "X2": x2,
        "12": twelve,
        "Over 0.5": over05,
        "Over 1.5": over15,
        "Over 2.5": over25,
        "Under 3.5": under35,
        "BTTS Yes": btts,
        f"{team1['name']} to Score": team1_score,
        f"{team2['name']} to Score": team2_score,
    }


# ============================================================
# PRIMARY SIGNAL
# ============================================================

def choose_primary(markets):
    candidates = {
        name: value
        for name, value in markets.items()
        if value >= 58
    }

    if not candidates:
        return max(
            markets.items(),
            key=lambda x: x[1]
        )

    # Prefer markets that are statistically broad
    # rather than team-specific when confidence is close.
    priority = {
        "1X": 5,
        "X2": 5,
        "12": 4,
        "Over 1.5": 4,
        "Under 3.5": 4,
        "Over 2.5": 3,
        "Over 0.5": 2,
        "BTTS Yes": 2,
    }

    best = None

    for name, value in candidates.items():
        score = value + priority.get(name, 1)

        if best is None or score > best[0]:
            best = (score, name, value)

    return best[1], best[2]


# ============================================================
# FORMAT TEAM STATS
# ============================================================

def format_team_stats(name, stats):
    return (
        f"📊 {name.upper()} — LAST {stats['sample']}\n"
        f"Form: "
        f"{'W' * stats['wins']}"
        f"{'D' * stats['draws']}"
        f"{'L' * stats['losses']}\n"
        f"W/D/L: "
        f"{stats['wins']}/"
        f"{stats['draws']}/"
        f"{stats['losses']}\n"
        f"Goals scored: {stats['gf']}\n"
        f"Goals conceded: {stats['ga']}\n"
        f"Avg scored: {stats['avg_scored']:.2f}\n"
        f"Avg conceded: {stats['avg_conceded']:.2f}\n"
        f"Avg total goals: {stats['avg_total']:.2f}\n"
        f"Over 0.5: {stats['over05']:.0f}%\n"
        f"Over 1.5: {stats['over15']:.0f}%\n"
        f"Over 2.5: {stats['over25']:.0f}%\n"
        f"Under 3.5: {stats['under35']:.0f}%\n"
        f"BTTS: {stats['btts']:.0f}%\n"
        f"Scoring consistency: {stats['scoring']:.0f}%\n"
        f"Clean sheets: {stats['clean_sheet']:.0f}%"
    )


# ============================================================
# ANALYSIS
# ============================================================

def analyze_match(team1_name, team2_name):

    team1 = search_team(team1_name)
    team2 = search_team(team2_name)

    if not team1:
        return f"❌ I couldn't find {team1_name} in OpenFoot."

    if not team2:
        return f"❌ I couldn't find {team2_name} in OpenFoot."

    team1_id = team1.get("id")
    team2_id = team2.get("id")

    if not team1_id or not team2_id:
        return "❌ OpenFoot returned an incomplete team record."

    matches1 = get_recent_matches(team1_id)
    matches2 = get_recent_matches(team2_id)

    if len(matches1) < 3:
        return (
            f"⚠️ OpenFoot returned only "
            f"{len(matches1)} usable completed matches "
            f"for {team1.get('name', team1_name)}."
        )

    if len(matches2) < 3:
        return (
            f"⚠️ OpenFoot returned only "
            f"{len(matches2)} usable completed matches "
            f"for {team2.get('name', team2_name)}."
        )

    stats1 = calculate_stats(matches1)
    stats2 = calculate_stats(matches2)

    name1 = team1.get("name", team1_name)
    name2 = team2.get("name", team2_name)

    team1_data = {
        "name": name1,
        "stats": stats1,
    }

    team2_data = {
        "name": name2,
        "stats": stats2,
    }

    # Team 1 is treated as home.
    # Team 2 is treated as away.
    home_context = venue_stats(
        matches1,
        "home"
    )

    away_context = venue_stats(
        matches2,
        "away"
    )

    markets = calculate_markets(
        team1_data,
        team2_data,
        home_context,
        away_context,
    )

    primary_name, primary_value = choose_primary(
        markets
    )

    response = []

    response.append(
        "⚽ GOALLOGIC AI — MATCH ANALYSIS"
    )

    response.append("")

    response.append(
        f"{name1} vs {name2}"
    )

    response.append(
        f"Season: {CURRENT_SEASON}"
    )

    response.append("")

    response.append(
        format_team_stats(
            name1,
            stats1
        )
    )

    response.append("")

    response.append(
        format_team_stats(
            name2,
            stats2
        )
    )

    response.append("")

    response.append(
        "🏠 HOME / AWAY CONTEXT"
    )

    response.append("")

    response.append(
        f"{name1} home sample: "
        f"{home_context['sample']} matches"
    )

    if home_context["sample"]:
        response.append(
            f"Home scoring: "
            f"{home_context['scoring']:.0f}%"
        )

        response.append(
            f"Home Over 2.5: "
            f"{home_context['over25']:.0f}%"
        )

        response.append(
            f"Home BTTS: "
            f"{home_context['btts']:.0f}%"
        )
    else:
        response.append(
            "Home context: insufficient sample"
        )

    response.append("")

    response.append(
        f"{name2} away sample: "
        f"{away_context['sample']} matches"
    )

    if away_context["sample"]:
        response.append(
            f"Away scoring: "
            f"{away_context['scoring']:.0f}%"
        )

        response.append(
            f"Away Over 2.5: "
            f"{away_context['over25']:.0f}%"
        )

        response.append(
            f"Away BTTS: "
            f"{away_context['btts']:.0f}%"
        )
    else:
        response.append(
            "Away context: insufficient sample"
        )

    # --------------------------------------------------------
    # DOUBLE CHANCE
    # --------------------------------------------------------

    response.append("")
    response.append("🎯 DOUBLE CHANCE")
    response.append("")

    response.append(
        market_line(
            "1X — Home Win or Draw",
            markets["1X"]
        )
    )

    response.append(
        f"Reason: {name1} recent W/D rate "
        f"is {stats1['wd_rate']:.0f}%"
    )

    response.append("")

    response.append(
        market_line(
            "X2 — Draw or Away Win",
            markets["X2"]
        )
    )

    response.append(
        f"Reason: {name2} recent W/D rate "
        f"is {stats2['wd_rate']:.0f}%"
    )

    response.append("")

    response.append(
        market_line(
            "12 — Either Team Wins",
            markets["12"]
        )
    )

    response.append(
        f"Reason: Recent draw rates: "
        f"{name1} {stats1['draw_rate']:.0f}%, "
        f"{name2} {stats2['draw_rate']:.0f}%"
    )

    # --------------------------------------------------------
    # GOAL MARKETS
    # --------------------------------------------------------

    response.append("")
    response.append("⚽ GOAL MARKETS")
    response.append("")

    response.append(
        market_line(
            "Over 0.5 Goals",
            markets["Over 0.5"]
        )
    )

    response.append(
        f"Reason: {name1} recent Over 0.5 "
        f"{stats1['over05']:.0f}%; "
        f"{name2}: {stats2['over05']:.0f}%"
    )

    response.append("")

    response.append(
        market_line(
            "Over 1.5 Goals",
            markets["Over 1.5"]
        )
    )

    response.append(
        f"Reason: Combined recent goal "
        f"environment: "
        f"{(stats1['avg_total'] + stats2['avg_total']) / 2:.2f}"
    )

    response.append("")

    response.append(
        market_line(
            "Over 2.5 Goals",
            markets["Over 2.5"]
        )
    )

    response.append(
        f"Reason: {name1}: "
        f"{stats1['over25']:.0f}%; "
        f"{name2}: {stats2['over25']:.0f}%; "
        f"combined average: "
        f"{(stats1['avg_total'] + stats2['avg_total']) / 2:.2f}"
    )

    response.append("")

    response.append(
        market_line(
            "Under 3.5 Goals",
            markets["Under 3.5"]
        )
    )

    response.append(
        f"Reason: Combined recent goal "
        f"environment: "
        f"{(stats1['avg_total'] + stats2['avg_total']) / 2:.2f}"
    )

    # --------------------------------------------------------
    # BTTS
    # --------------------------------------------------------

    response.append("")
    response.append("🤝 BTTS")
    response.append("")

    response.append(
        market_line(
            "BTTS — Yes",
            markets["BTTS Yes"]
        )
    )

    response.append(
        f"Reason: {name1} BTTS "
        f"{stats1['btts']:.0f}%; "
        f"{name2} BTTS {stats2['btts']:.0f}%"
    )

    # --------------------------------------------------------
    # TEAM TO SCORE
    # --------------------------------------------------------

    response.append("")
    response.append("🎯 TEAM TO SCORE")
    response.append("")

    team1_market = f"{name1} to Score"

    response.append(
        market_line(
            team1_market,
            markets[team1_market]
        )
    )

    response.append(
        f"Reason: Scoring consistency "
        f"{stats1['scoring']:.0f}%; "
        f"opponent clean-sheet rate "
        f"{stats2['clean_sheet']:.0f}%"
    )

    response.append("")

    team2_market = f"{name2} to Score"

    response.append(
        market_line(
            team2_market,
            markets[team2_market]
        )
    )

    response.append(
        f"Reason: Scoring consistency "
        f"{stats2['scoring']:.0f}%; "
        f"opponent clean-sheet rate "
        f"{stats1['clean_sheet']:.0f}%"
    )

    # --------------------------------------------------------
    # PRIMARY SIGNAL
    # --------------------------------------------------------

    response.append("")
    response.append("⭐ PRIMARY STATISTICAL SIGNAL")
    response.append("")

    response.append(
        f"{primary_name} — Confidence "
        f"{primary_value}%"
    )

    response.append(
        f"Grade: {grade(primary_value)}"
    )

    response.append(
        f"Advice: {advice(primary_value)}"
    )

    response.append("")

    response.append(
        "🧠 GoalLogic AI uses one centralized "
        "confidence model combining recent form, "
        "home/away evidence, scoring, defending "
        "and sample size."
    )

    response.append("")

    response.append(
        "⚠️ Statistical analysis is not a guarantee "
        "of the match outcome. Confidence figures "
        "are statistical indicators, not certainty."
    )

    return "\n".join(response)


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "⚽ GoalLogic AI is online.\n\n"
        "Send a match like:\n"
        "Chelsea vs Arsenal\n\n"
        "Or use:\n"
        "/analyze Chelsea vs Arsenal"
    )


async def apitest_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:
        openfoot_get(
            "/v1/search",
            {"q": "Arsenal"}
        )

        await update.message.reply_text(
            "✅ OPENFOOT TEST PASSED\n\n"
            "OpenFoot API is connected successfully."
        )

    except Exception as e:
        await update.message.reply_text(
            "❌ OPENFOOT TEST FAILED\n\n"
            f"{str(e)}"
        )


async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    text = " ".join(context.args).strip()

    if not text:
        await update.message.reply_text(
            "Use:\n"
            "/analyze Chelsea vs Arsenal"
        )
        return

    parts = re.split(
        r"\s+(?:vs?\.?|versus)\s+",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )

    if len(parts) != 2:
        await update.message.reply_text(
            "Please use:\n"
            "/analyze Chelsea vs Arsenal"
        )
        return

    team1 = parts[0].strip()
    team2 = parts[1].strip()

    status = await update.message.reply_text(
        "🔎 Analyzing recent OpenFoot data..."
    )

    try:
        result = analyze_match(
            team1,
            team2
        )

        await status.edit_text(result)

    except Exception as e:
        await status.edit_text(
            "❌ Analysis failed.\n\n"
            f"Error: {str(e)}"
        )


async def text_match_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    text = update.message.text.strip()

    if not re.search(
        r"\s+(?:vs?\.?|versus)\s+",
        text,
        re.IGNORECASE,
    ):
        return

    parts = re.split(
        r"\s+(?:vs?\.?|versus)\s+",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )

    if len(parts) != 2:
        return

    team1 = parts[0].strip()
    team2 = parts[1].strip()

    status = await update.message.reply_text(
        "🔎 Analyzing recent OpenFoot data..."
    )

    try:
        result = analyze_match(
            team1,
            team2
        )

        await status.edit_text(result)

    except Exception as e:
        await status.edit_text(
            "❌ Analysis failed.\n\n"
            f"Error: {str(e)}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing"
        )

    if not OPENFOOT_API_KEY:
        raise RuntimeError(
            "OPENFOOT_API_KEY is missing"
        )

    health_thread = threading.Thread(
        target=start_health_server,
        daemon=True,
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
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "apitest",
            apitest_command
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
            text_match_handler
        )
    )

    print("GoalLogic AI is running.")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
