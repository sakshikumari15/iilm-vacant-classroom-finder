from __future__ import annotations

import io
import os
import time

import requests
from flask import Flask, render_template, request

from pdf_timetable import parse_pdf_bytes, parse_pdf_file

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Timetable sources
# ---------------------------------------------------------------------------
# EduPage remains the live source already used by the original application.
# PDF files/URLs are additional sources. Their room occupancy is merged with
# EduPage occupancy, so adding a branch does not replace the existing data.
EDUPAGE_URL = "https://iilmgn.edupage.org/timetable/server/regulartt.js?__func=regularttGetData"
EDUPAGE_ARGS = {"__args": [None, "37"], "__gsh": "00000000"}

DEFAULT_PDF_FILES = [os.path.join("data", "Biotech tt.pdf")]


def _csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


PDF_FILES = _csv_env("PDF_TIMETABLE_FILES") or DEFAULT_PDF_FILES
PDF_URLS = _csv_env("PDF_TIMETABLE_URLS")

CACHE_DURATION = 600

timetable_cache = None
cache_time = 0.0
pdf_cache: tuple[float, list[dict]] | None = None


def get_timetable():
    global timetable_cache, cache_time

    current_time = time.time()
    if timetable_cache is not None and current_time - cache_time < CACHE_DURATION:
        return timetable_cache

    response = requests.post(EDUPAGE_URL, json=EDUPAGE_ARGS, timeout=15)
    response.raise_for_status()

    timetable_cache = response.json()
    cache_time = current_time
    return timetable_cache


def _load_pdf_sources() -> list[dict]:
    records: list[dict] = []

    for path in PDF_FILES:
        try:
            records.extend(parse_pdf_file(path))
        except FileNotFoundError:
            # A future branch can be configured only by URL; a missing optional
            # local file should not take the whole application down.
            continue
        except Exception as exc:
            app.logger.exception("Could not parse PDF timetable %s: %s", path, exc)

    for url in PDF_URLS:
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            records.extend(parse_pdf_bytes(response.content, source_name=url))
        except Exception as exc:
            app.logger.exception("Could not download/parse PDF timetable %s: %s", url, exc)

    return records


def get_pdf_records() -> list[dict]:
    global pdf_cache

    current_time = time.time()
    if pdf_cache is not None and current_time - pdf_cache[0] < CACHE_DURATION:
        return pdf_cache[1]

    records = _load_pdf_sources()
    pdf_cache = (current_time, records)
    return records


def _extract_edupage_parts(data):
    tables = data["r"]["dbiAccessorRes"]["tables"]
    parts = {}
    for table in tables:
        if table["id"] in {"cards", "classrooms", "periods", "lessons"}:
            parts[table["id"]] = table
    return parts


def _edupage_rooms_and_occupied(data, selected_day: str, selected_period: int):
    parts = _extract_edupage_parts(data)
    cards = parts.get("cards", {"data_rows": []})
    classrooms = parts.get("classrooms", {"data_rows": []})
    lessons = parts.get("lessons", {"data_rows": []})

    room_names = {
        room["id"]: room["name"]
        for room in classrooms["data_rows"]
        if room.get("name")
    }

    lesson_duration = {
        lesson["id"]: lesson.get("durationperiods", 1)
        for lesson in lessons["data_rows"]
    }

    day_codes = {
        "monday": "100000",
        "tuesday": "010000",
        "wednesday": "001000",
        "thursday": "000100",
        "friday": "000010",
        "saturday": "000001",
    }

    day_code = day_codes[selected_day]
    occupied = set()

    for card in cards["data_rows"]:
        card_days = card.get("days", "")
        if len(card_days) < 6:
            card_days = card_days.zfill(6)
        if day_code not in card_days:
            continue

        start_period = int(card.get("period", 0))
        duration = lesson_duration.get(card.get("lessonid"), 1)
        if not (start_period <= selected_period < start_period + duration):
            continue

        for room_id in card.get("classroomids", []):
            room = room_names.get(room_id)
            if room:
                occupied.add(room)

    return set(room_names.values()), occupied


def _period_time_from_edupage(data, selected_period: str) -> str:
    parts = _extract_edupage_parts(data)
    for period in parts.get("periods", {"data_rows": []})["data_rows"]:
        if str(period.get("id")) == str(selected_period):
            return f'{period.get("starttime", "")} - {period.get("endtime", "")}'

    fallback = {
        "1": "09:00 - 09:55",
        "2": "09:55 - 10:50",
        "3": "10:50 - 11:45",
        "4": "11:45 - 12:40",
        "5": "12:40 - 13:35",
        "6": "13:35 - 14:30",
        "7": "14:30 - 15:25",
        "8": "15:25 - 16:20",
        "9": "16:20 - 17:15",
    }
    return fallback.get(str(selected_period), "Unknown")


@app.route("/", methods=["GET", "POST"])
def home():
    selected_day = ""
    selected_period = ""
    time_label = ""
    vacant_rooms = []

    pdf_records = get_pdf_records()
    pdf_rooms = {record["room"] for record in pdf_records}

    if request.method == "POST":
        selected_day = request.form["day"].lower()
        selected_period = request.form["period"]
        selected_period_int = int(selected_period)

        # Keep the existing EduPage calculation intact.
        data = get_timetable()
        edupage_rooms, edupage_occupied = _edupage_rooms_and_occupied(
            data, selected_day, selected_period_int
        )
        time_label = _period_time_from_edupage(data, selected_period)

        # Merge all timetable sources. A room is occupied if ANY source says it
        # is occupied for the requested day/period.
        all_rooms = edupage_rooms | pdf_rooms
        occupied_rooms = set(edupage_occupied)

        for record in pdf_records:
            if (
                record["day"] == selected_day
                and record["period"] == selected_period_int
            ):
                occupied_rooms.add(record["room"])

        vacant_rooms = sorted(all_rooms - occupied_rooms)

    return render_template(
        "index.html",
        vacant_rooms=vacant_rooms,
        selected_day=selected_day,
        selected_period=selected_period,
        time=time_label,
    )


if __name__ == "__main__":
    app.run(debug=True)
