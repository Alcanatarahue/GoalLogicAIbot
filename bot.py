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


# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

PORT = int(os.getenv("PORT", "10000"))

OPENFOOT_BASE = "https://openfootapi.com"

CURRENT_SEASON = "2026/27"

# Premier League
EPL_ID = "comp_premier_league_eng"


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

    print(f"GoalLogic AI is running on port {PORT}.", flush=True)

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

    url = OPENFOOT_BASE + endpoint

    try:
        response = requests.get(
            url,
            headers=openfoot_headers(),
            params=params or {},
            timeout=25
        )

        print(
            f"OpenFoot GET {response.url} -> {response.status_code}",
            flush=True
        )

        if response.status_code != 200:
            print(
                f"OpenFoot error: {response.text}",
                flush=True
            )
            return []

        payload = response.json()

        return payload.get("data", [])

    except Exception as exc:

        print(
            f"OpenFoot request error: {exc}",
            flush=True
        )

        return []


# ============================================================
# API TEST
# ============================================================

def test_openfoot():

    try:

        response = requests.get(
            OPENFOOT_BASE + "/v1/health",
            headers=openfoot_headers(),
            timeout=20
        )

        if response.status_code == 200:
            return True

    except Exception:
        pass

    return False


# ============================================================
# TEAM SEARCH
# ============================================================

def search_team(team_name):

    results = openfoot_get(
        "/v1/search",
        {
            "q": team_name
        }
    )

    if not results:
        return None

    target = team_name.lower().strip()

    # Exact name
    for item in results:

        name = str(
            item.get("name", "")
        ).lower().strip()

        if name == target:
            return item

    # Partial name
    for item in results:

        name = str(
            item.get("name", "")
        ).lower()

        if target in name or name in target:
            return item

    return results[0]


# ============================================================
# SCORE EXTRACTION
# ============================================================

def get_score(match):

    score = match.get("score")

    if isinstance(score, dict):

        home = score.get("home")
        away = score.get("away")

        if isinstance(home, dict):
            home = (
                home.get("current")
                if home.get("current") is not None
                else home.get("display")
            )

        if isinstance(away, dict):
            away = (
                away.get("current")
                if away.get("current") is not None
                else away.get("display")
            )

        if home is not None and away is not None:

            try:
                return int(home), int(away)
            except Exception:
                pass

    home = match.get("homeScore")
    away = match.get("awayScore")

    if home is not None and away is not None:

        try:
            return int(home), int(away)
        except Exception:
            pass

    return None


# ============================================================
# MATCH DATE
# ============================================================

def match_date(match):

    value = (
        match.get("kickoffAt")
        or match.get("date")
        or match.get("startTime")
        or match.get("scheduledAt")
        or ""
    )

    return str(value)


# ============================================================
# TEAM NAME FROM MATCH
# ============================================================

def get_team_name(match, home=True):

    side = "home" if home else "away"

    team = match.get(side)

    if isinstance(team, dict):

        return (
            team.get("name")
            or team.get("shortName")
            or team.get("displayName")
            or ""
        )

    key = (
        "homeTeamName"
        if home
        else "awayTeamName"
    )

    return str(match.get(key, ""))


def get_team_id_from_match(match, home=True):

    side = "home" if home else "away"

    team = match.get(side)

    if isinstance(team, dict):

        return (
            team.get("id")
            or team.get("teamId")
            or ""
        )

    key = (
        "homeTeamId"
        if home
        else "awayTeamId"
    )

    return str(match.get(key, ""))


# ============================================================
# COMPLETED MATCH CHECK
# ============================================================

def is_finished(match):

    status = str(
        match.get("status", "")
    ).lower().strip()

    status_code = str(
        match.get("statusCode", "")
    ).lower().strip()

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
        "closed",
    }

    if status in finished_statuses:
        return True

    if status_code in finished_statuses:
        return True

    # A valid final score is enough for our historical dataset.
    if get_score(match) is not None:
        return True

    return False


# ============================================================
# GET EPL SEASON MATCHES
# ============================================================

def get_epl_matches():

    matches = openfoot_get(
        "/v1/matches",
        {
            "competition": EPL_ID,
            "season": CURRENT_SEASON,
        }
    )

    print(
        f"EPL matches returned: {len(matches)}",
        flush=True
    )

    finished = []

    for match in matches:

        if is_finished(match):
            finished.append(match)

    finished.sort(
        key=match_date,
        reverse=True
    )

    print(
        f"EPL completed matches: {len(finished)}",
        flush=True
    )

    return finished


# ============================================================
# GET TEAM HISTORY FROM EPL DATA
# ============================================================

def get_team_matches(team_id, team_name):

    all_matches = get_epl_matches()

    if not all_matches:
        return []

    team_id = str(team_id).lower().strip()
    team_name_lower = team_name.lower().strip()

    selected = []

    for match in all_matches:

        home_id = str(
            get_team_id_from_match(
                match,
                True
            )
        ).lower().strip()

        away_id = str(
            get_team_id_from_match(
                match,
                False
            )
        ).lower().strip()

        home_name = get_team_name(
            match,
            True
        ).lower().strip()

        away_name = get_team_name(
            match,
            False
        ).lower().strip()

        found = False

        if team_id:
            if (
                team_id == home_id
                or team_id == away_id
            ):
                found = True

        if not found and team_name_lower:
            if (
                team_name_lower == home_name
                or team_name_lower == away_name
                or team_name_lower in home_name
                or team_name_lower in away_name
            ):
                found = True

        if found:
            selected.append(match)

    selected.sort(
        key=match_date,
        reverse=True
    )

    print(
        f"{team_name}: {len(selected)} completed matches found.",
        flush=True
    )

    return selected


# ============================================================
# DETERMINE TEAM RESULT
# ============================================================

def team_result(match, team_name):

    score = get_score(match)

    if score is None:
        return None

    home_goals, away_goals = score

    home_name = get_team_name(
        match,
        True
    ).lower()

    team_name_lower = team_name.lower()

    if (
        team_name_lower in home_name
        or home_name in team_name_lower
    ):
        gf = home_goals
        ga = away_goals
    else:
        gf = away_goals
        ga = home_goals

    if gf > ga:
        result = "W"
    elif gf == ga:
        result = "D"
    else:
        result = "L"

    return {
        "gf": gf,
        "ga": ga,
        "result": result,
        "total": gf + ga,
    }


# ============================================================
# CALCULATE STATS
# ============================================================

def calculate_stats(matches, team_name):

    rows = []

    for match in matches:

        result = team_result(
            match,
            team_name
        )

        if result:
            rows.append(result)

    if not rows:
        return None

    sample = len(rows)

    wins = sum(
        1 for x in rows
        if x["result"] == "W"
    )

    draws = sum(
        1 for x in rows
        if x["result"] == "D"
    )

    losses = sum(
        1 for x in rows
        if x["result"] == "L"
    )

    goals_for = sum(
        x["gf"] for x in rows
    )

    goals_against = sum(
        x["ga"] for x in rows
    )

    over05 = sum(
        x["total"] > 0
        for x in rows
    ) / sample * 100

    over15 = sum(
        x["total"] > 1
        for x in rows
    ) / sample * 100

    over25 = sum(
        x["total"] > 2
        for x in rows
    ) / sample * 100

    under35 = sum(
        x["total"] < 4
        for x in rows
    ) / sample * 100

    btts = sum(
        x["gf"] > 0 and x["ga"] > 0
        for x in rows
    ) / sample * 100

    scoring = sum(
        x["gf"] > 0
        for x in rows
    ) / sample * 100

    clean = sum(
        x["ga"] == 0
        for x in rows
    ) / sample * 100

    conceding = sum(
        x["ga"] > 0
        for x in rows
    ) / sample * 100

    two_to_four = sum(
        2 <= x["total"] <= 4
        for x in rows
    ) / sample * 100

    return {
        "sample": sample,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "gf": goals_for,
        "ga": goals_against,
        "avg_gf": mean(
            x["gf"] for x in rows
        ),
        "avg_ga": mean(
            x["ga"] for x in rows
        ),
        "avg_total": mean(
            x["total"] for x in rows
        ),
        "over05": over05,
        "over15": over15,
        "over25": over25,
        "under35": under35,
        "btts": btts,
        "scoring": scoring,
        "clean": clean,
        "conceding": conceding,
        "two_to_four": two_to_four,
        "form": "".join(
            x["result"] for x in rows
        ),
        "rows": rows,
    }


# ============================================================
# VENUE FILTER
# ============================================================

def get_venue_matches(
    matches,
    team_name,
    home=True
):

    selected = []

    team_name_lower = team_name.lower()

    for match in matches:

        home_name = get_team_name(
            match,
            True
        ).lower()

        away_name = get_team_name(
            match,
            False
        ).lower()

        if home:

            if (
                team_name_lower in home_name
                or home_name in team_name_lower
            ):
                selected.append(match)

        else:

            if (
                team_name_lower in away_name
                or away_name in team_name_lower
            ):
                selected.append(match)

    return selected


# ============================================================
# FORMAT TEAM BLOCK
# ============================================================

def team_block(
    title,
    stats
):

    return f"""
{title}

Form: {stats["form"]}
W/D/L: {stats["wins"]}/{stats["draws"]}/{stats["losses"]}

Goals scored: {stats["gf"]}
Goals conceded: {stats["ga"]}

Avg scored: {stats["avg_gf"]:.2f}
Avg conceded: {stats["avg_ga"]:.2f}
Avg total goals: {stats["avg_total"]:.2f}

Over 0.5: {stats["over05"]:.0f}%
Over 1.5: {stats["over15"]:.0f}%
Over 2.5: {stats["over25"]:.0f}%

Under 3.5: {stats["under35"]:.0f}%
BTTS: {stats["btts"]:.0f}%

Scoring consistency: {stats["scoring"]:.0f}%
Clean sheets: {stats["clean"]:.0f}%

Sample: {stats["sample"]} matches
"""


# ============================================================
# CONFIDENCE HELPERS
# ============================================================

def grade(confidence):

    if confidence >= 80:
        return "🔥 STRONG"

    if confidence >= 70:
        return "🟢 GOOD"

    if confidence >= 60:
        return "🟡 MODERATE"

    return "🔴 AVOID"


def advice(confidence):

    if confidence >= 70:
        return "BET"

    if confidence >= 60:
        return "CAUTION"

    return "AVOID"


# ============================================================
# MARKET CONFIDENCE
# ============================================================

def market_confidence(
    market,
    a,
    b,
    home_stats,
    away_stats
):

    venue_a = home_stats
    venue_b = away_stats

    reliability = min(
        100,
        (
            min(a["sample"], 5) / 5 * 100
            + min(b["sample"], 5) / 5 * 100
        ) / 2
    )

    # ----------------------------------------
    # OVER 0.5
    # ----------------------------------------

    if market == "Over 0.5 Goals":

        raw = mean([
            a["over05"],
            b["over05"],
            venue_a["over05"],
            venue_b["over05"],
        ])

        confidence = (
            raw * 0.75
            + reliability * 0.25
        )

        return confidence

    # ----------------------------------------
    # OVER 1.5
    # ----------------------------------------

    if market == "Over 1.5 Goals":

        raw = mean([
            a["over15"],
            b["over15"],
            venue_a["over15"],
            venue_b["over15"],
        ])

        confidence = (
            raw * 0.65
            + reliability * 0.20
            + min(
                100,
                (a["avg_total"] + b["avg_total"]) / 4 * 100
            ) * 0.15
        )

        return confidence

    # ----------------------------------------
    # OVER 2.5
    # ----------------------------------------

    if market == "Over 2.5 Goals":

        raw = mean([
            a["over25"],
            b["over25"],
            venue_a["over25"],
            venue_b["over25"],
        ])

        confidence = (
            raw * 0.70
            + reliability * 0.20
            + min(
                100,
                (a["avg_total"] + b["avg_total"]) / 5 * 100
            ) * 0.10
        )

        return confidence

    # ----------------------------------------
    # UNDER 3.5
    # ----------------------------------------

    if market == "Under 3.5 Goals":

        raw = mean([
            a["under35"],
            b["under35"],
            venue_a["under35"],
            venue_b["under35"],
        ])

        high_goal_counter = mean([
            a["avg_total"],
            b["avg_total"],
            venue_a["avg_total"],
            venue_b["avg_total"],
        ])

        confidence = (
            raw * 0.70
            + reliability * 0.20
            + max(
                0,
                100 - high_goal_counter * 20
            ) * 0.10
        )

        return max(
            0,
            min(100, confidence)
        )

    # ----------------------------------------
    # BTTS
    # ----------------------------------------

    if market == "BTTS — Yes":

        raw = mean([
            a["btts"],
            b["btts"],
            venue_a["btts"],
            venue_b["btts"],
        ])

        clean_counter = mean([
            a["clean"],
            b["clean"],
            venue_a["clean"],
            venue_b["clean"],
        ])

        confidence = (
            raw * 0.75
            + reliability * 0.15
            + max(
                0,
                100 - clean_counter
            ) * 0.10
        )

        return max(
            0,
            min(100, confidence)
        )

    # ----------------------------------------
    # TEAM 1 TO SCORE
    # ----------------------------------------

    if market == "TEAM1_TO_SCORE":

        raw = mean([
            a["scoring"],
            venue_a["scoring"],
            b["conceding"],
            away_stats["conceding"],
        ])

        confidence = (
            raw * 0.80
            + reliability * 0.20
        )

        return min(
            100,
            confidence
        )

    # ----------------------------------------
    # TEAM 2 TO SCORE
    # ----------------------------------------

    if market == "TEAM2_TO_SCORE":

        raw = mean([
            b["scoring"],
            venue_b["scoring"],
            a["conceding"],
            home_stats["conceding"],
        ])

        confidence = (
            raw * 0.80
            + reliability * 0.20
        )

        return min(
            100,
            confidence
        )

    # ----------------------------------------
    # 2-4 TOTAL GOALS
    # ----------------------------------------

    if market == "2–4 Total Goals":

        raw = mean([
            a["two_to_four"],
            b["two_to_four"],
            venue_a["two_to_four"],
            venue_b["two_to_four"],
        ])

        confidence = (
            raw * 0.75
            + reliability * 0.25
        )

        return confidence

    return 50


# ============================================================
# MARKET REASON
# ============================================================

def market_reason(
    market,
    a,
    b,
    home_stats,
    away_stats
):

    if market == "Over 0.5 Goals":
        return (
            f"{a['over05']:.0f}% of {a['sample']} recent "
            f"matches for {TEAM1_NAME}; "
            f"{b['over05']:.0f}% for {TEAM2_NAME}."
        )

    if market == "Over 1.5 Goals":
        return (
            f"{TEAM1_NAME}: {a['over15']:.0f}% recent Over 1.5; "
            f"{TEAM2_NAME}: {b['over15']:.0f}%; "
            f"combined average total goals: "
            f"{(a['avg_total'] + b['avg_total']) / 2:.2f}."
        )

    if market == "Over 2.5 Goals":
        return (
            f"{TEAM1_NAME}: {a['over25']:.0f}% Over 2.5; "
            f"{TEAM2_NAME}: {b['over25']:.0f}%; "
            f"home/away rates: "
            f"{home_stats['over25']:.0f}% / "
            f"{away_stats['over25']:.0f}%."
        )

    if market == "Under 3.5 Goals":
        return (
            f"Recent Under 3.5 rates: "
            f"{TEAM1_NAME} {a['under35']:.0f}%, "
            f"{TEAM2_NAME} {b['under35']:.0f}%; "
            f"home/away: "
            f"{home_stats['under35']:.0f}% / "
            f"{away_stats['under35']:.0f}%."
        )

    if market == "BTTS — Yes":
        return (
            f"BTTS rates: "
            f"{TEAM1_NAME} {a['btts']:.0f}%, "
            f"{TEAM2_NAME} {b['btts']:.0f}%; "
            f"home/away: "
            f"{home_stats['btts']:.0f}% / "
            f"{away_stats['btts']:.0f}%."
        )

    if market == "TEAM1_TO_SCORE":
        return (
            f"{TEAM1_NAME} scoring rate: "
            f"{a['scoring']:.0f}%; "
            f"recent home scoring: "
            f"{home_stats['scoring']:.0f}%; "
            f"{TEAM2_NAME} conceding rate: "
            f"{b['conceding']:.0f}%."
        )

    if market == "TEAM2_TO_SCORE":
        return (
            f"{TEAM2_NAME} scoring rate: "
            f"{b['scoring']:.0f}%; "
            f"recent away scoring: "
            f"{away_stats['scoring']:.0f}%; "
            f"{TEAM1_NAME} conceding rate: "
            f"{a['conceding']:.0f}%."
        )

    if market == "2–4 Total Goals":
        return (
            f"{TEAM1_NAME}: {a['two_to_four']:.0f}% "
            f"of recent matches had 2–4 goals; "
            f"{TEAM2_NAME}: {b['two_to_four']:.0f}%."
        )

    return ""


# ============================================================
# GLOBAL TEAM NAMES USED BY MARKET REASONS
# ============================================================

TEAM1_NAME = ""
TEAM2_NAME = ""


# ============================================================
# ANALYSIS ENGINE
# ============================================================

def analyze_match(team1_name, team2_name):

    global TEAM1_NAME
    global TEAM2_NAME

    TEAM1_NAME = team1_name
    TEAM2_NAME = team2_name

    # Search teams
    team1 = search_team(team1_name)
    team2 = search_team(team2_name)

    if not team1:
        return f"❌ I couldn't find {team1_name} in OpenFoot."

    if not team2:
        return f"❌ I couldn't find {team2_name} in OpenFoot."

    team1_id = (
        team1.get("id")
        or team1.get("teamId")
        or ""
    )

    team2_id = (
        team2.get("id")
        or team2.get("teamId")
        or ""
    )

    print(
        f"TEAM 1: {team1_name} -> {team1_id}",
        flush=True
    )

    print(
        f"TEAM 2: {team2_name} -> {team2_id}",
        flush=True
    )

    # Get completed EPL history
    team1_matches = get_team_matches(
        team1_id,
        team1_name
    )

    team2_matches = get_team_matches(
        team2_id,
        team2_name
    )

    if len(team1_matches) < 3:

        return (
            f"⚠️ OpenFoot returned only "
            f"{len(team1_matches)} usable completed "
            f"matches for {team1_name}.\n\n"
            f"Team ID: {team1_id}\n"
            f"Competition: {EPL_ID}\n"
            f"Season: {CURRENT_SEASON}"
        )

    if len(team2_matches) < 3:

        return (
            f"⚠️ OpenFoot returned only "
            f"{len(team2_matches)} usable completed "
            f"matches for {team2_name}.\n\n"
            f"Team ID: {team2_id}\n"
            f"Competition: {EPL_ID}\n"
            f"Season: {CURRENT_SEASON}"
        )

    # Last five
    team1_last5 = team1_matches[:5]
    team2_last5 = team2_matches[:5]

    team1_stats = calculate_stats(
        team1_last5,
        team1_name
    )

    team2_stats = calculate_stats(
        team2_last5,
        team2_name
    )

    # Venue
    team1_home_matches = get_venue_matches(
        team1_matches,
        team1_name,
        home=True
    )[:5]

    team2_away_matches = get_venue_matches(
        team2_matches,
        team2_name,
        home=False
    )[:5]

    team1_home_stats = calculate_stats(
        team1_home_matches,
        team1_name
    )

    team2_away_stats = calculate_stats(
        team2_away_matches,
        team2_name
    )

    # Fallback if venue sample is too small
    if not team1_home_stats:
        team1_home_stats = team1_stats

    if not team2_away_stats:
        team2_away_stats = team2_stats

    # Goal intelligence
    combined_attack = mean([
        team1_stats["avg_gf"],
        team2_stats["avg_gf"]
    ])

    combined_conceded = mean([
        team1_stats["avg_ga"],
        team2_stats["avg_ga"]
    ])

    combined_goal_environment = (
        combined_attack
        + combined_conceded
    )

    # Markets
    markets = [
        "Over 0.5 Goals",
        "Over 1.5 Goals",
        "Over 2.5 Goals",
        "Under 3.5 Goals",
        "BTTS — Yes",
        "TEAM1_TO_SCORE",
        "TEAM2_TO_SCORE",
        "2–4 Total Goals",
    ]

    market_results = []

    for market in markets:

        confidence = market_confidence(
            market,
            team1_stats,
            team2_stats,
            team1_home_stats,
            team2_away_stats
        )

        confidence = max(
            0,
            min(
                99,
                round(confidence)
            )
        )

        if market == "TEAM1_TO_SCORE":
            display_market = (
                f"{team1_name} to Score"
            )

        elif market == "TEAM2_TO_SCORE":
            display_market = (
                f"{team2_name} to Score"
            )

        else:
            display_market = market

        market_results.append({
            "name": market,
            "display": display_market,
            "confidence": confidence,
            "grade": grade(confidence),
            "advice": advice(confidence),
            "reason": market_reason(
                market,
                team1_stats,
                team2_stats,
                team1_home_stats,
                team2_away_stats
            ),
        })

    # Better primary-signal logic
    preferred = [
        x for x in market_results
        if x["name"] != "Over 0.5 Goals"
        and x["confidence"] >= 60
    ]

    if preferred:
        primary = max(
            preferred,
            key=lambda x: x["confidence"]
        )
    else:
        primary = max(
            market_results,
            key=lambda x: x["confidence"]
        )

    # Form comparison
    if (
        team1_stats["wins"]
        > team2_stats["wins"]
    ):
        form_text = (
            f"{team1_name} has the stronger "
            f"recent win record."
        )

    elif (
        team2_stats["wins"]
        > team1_stats["wins"]
    ):
        form_text = (
            f"{team2_name} has the stronger "
            f"recent win record."
        )

    else:
        form_text = (
            "The teams have similar recent "
            "win records."
        )

    # Build output
    text = f"""
⚽ GOALLOGIC AI — ADVANCED ANALYSIS

{team1_name} vs {team2_name}
Competition: Premier League
Season: {CURRENT_SEASON}

{team_block(
    f"📊 {team1_name.upper()} — LAST 5",
    team1_stats
)}

{team_block(
    f"📊 {team2_name.upper()} — LAST 5",
    team2_stats
)}

{team_block(
    f"🏠 {team1_name.upper()} — RECENT HOME",
    team1_home_stats
)}

{team_block(
    f"✈️ {team2_name.upper()} — RECENT AWAY",
    team2_away_stats
)}

🔥 GOAL INTELLIGENCE

Average attacking output:
{combined_attack:.2f} goals

Average goals conceded:
{combined_conceded:.2f} goals

Combined goal environment:
{combined_goal_environment:.2f}

{form_text}

📊 MARKET SIGNALS
"""

    for result in market_results:

        text += f"""
{result["display"]} — Confidence {result["confidence"]}%
Grade: {result["grade"]}
Advice: {result["advice"]}
Reason: {result["reason"]}
"""

    text += f"""
⭐ PRIMARY STATISTICAL SIGNAL

{primary["display"]}
Confidence: {primary["confidence"]}%
Grade: {primary["grade"]}
Advice: {primary["advice"]}

📌 DATA QUALITY

{team1_name}: {len(team1_last5)} recent matches
{team2_name}: {len(team2_last5)} recent matches
{team1_name} home sample: {len(team1_home_matches)}
{team2_name} away sample: {len(team2_away_matches)}

⚠️ Statistical analysis is not a guarantee of the match outcome.
Confidence figures are indicators based on available historical data, not certainty.
"""

    return text


# ============================================================
# PARSE MATCH
# ============================================================

def parse_match(text):

    text = text.strip()

    if text.lower().startswith("/analyze"):
        text = text[len("/analyze"):].strip()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    patterns = [
        r"(.+?)\s+vs\.?\s+(.+)",
        r"(.+?)\s+v\s+(.+)",
    ]

    for pattern in patterns:

        match = re.match(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            team1 = match.group(1).strip()
            team2 = match.group(2).strip()

            return team1, team2

    return None, None


# ============================================================
# TELEGRAM HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "⚽ Welcome to GoalLogic AI.\n\n"
        "Send a match like:\n\n"
        "/analyze Chelsea vs Arsenal"
    )


async def apitest(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not OPENFOOT_API_KEY:

        await update.message.reply_text(
            "❌ OPENFOOT_API_KEY is missing."
        )

        return

    if test_openfoot():

        await update.message.reply_text(
            "✅ OPENFOOT TEST PASSED\n\n"
            "OpenFoot API is connected successfully."
        )

    else:

        await update.message.reply_text(
            "❌ OPENFOOT TEST FAILED\n\n"
            "OpenFoot could not be reached."
        )


async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text or ""

    team1, team2 = parse_match(text)

    if not team1 or not team2:

        await update.message.reply_text(
            "⚽ Send a match like:\n\n"
            "/analyze Chelsea vs Arsenal"
        )

        return

    await update.message.reply_text(
        f"🔎 Analyzing {team1} vs {team2}..."
    )

    try:

        result = analyze_match(
            team1,
            team2
        )

        await update.message.reply_text(
            result
        )

    except Exception as exc:

        print(
            f"Analysis error: {exc}",
            flush=True
        )

        await update.message.reply_text(
            "❌ An error occurred while "
            "analyzing this match."
        )


async def normal_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text or ""

    if (
        " vs " in text.lower()
        or " v " in text.lower()
        or " v. " in text.lower()
    ):

        await analyze_command(
            update,
            context
        )

    else:

        await update.message.reply_text(
            "⚽ Send a match like:\n\n"
            "/analyze Chelsea vs Arsenal"
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
            filters.TEXT & ~filters.COMMAND,
            normal_message
        )
    )

    print(
        "GoalLogic AI Telegram bot is running.",
        flush=True
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
