from __future__ import annotations

import os
import time

import requests
from flask import Flask, render_template, request

from pdf_timetable import parse_pdf_bytes, parse_pdf_file
from data.bba.excel_timetable import parse_excel_file


app = Flask(__name__)


# ============================================================
# PDF TIMETABLE FILES
# ============================================================

DEFAULT_PDF_FILES = [
    os.path.join(
        "data",
        "biotechnology",
        "Biotechnology.pdf",
    ),
    os.path.join(
        "data",
        "bioinformatics",
        "Bioinformatics.pdf",
    ),
    os.path.join(
        "data",
        "food_technology",
        "Food_Technology.pdf",
    ),
]


def _csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]


PDF_FILES = (
    _csv_env("PDF_TIMETABLE_FILES")
    or DEFAULT_PDF_FILES
)

PDF_URLS = _csv_env("PDF_TIMETABLE_URLS")


# ============================================================
# EXCEL TIMETABLE FILES
# ============================================================

DEFAULT_EXCEL_FILES = [
    os.path.join(
        "data",
        "bba",
        "BBA Odd Sem .xlsx",
    ),
]

EXCEL_FILES = (
    _csv_env("EXCEL_TIMETABLE_FILES")
    or DEFAULT_EXCEL_FILES
)


# ============================================================
# CACHE
# ============================================================

CACHE_DURATION = 600

timetable_cache = None
cache_time = 0.0

pdf_cache: tuple[float, list[dict]] | None = None
excel_cache: tuple[float, list[dict]] | None = None


# ============================================================
# EDUPAGE
# ============================================================

EDUPAGE_URL = (
    "https://iilmgn.edupage.org/"
    "timetable/server/regulartt.js"
    "?__func=regularttGetData"
)

EDUPAGE_PAYLOAD = {
    "__args": [None, "37"],
    "__gsh": "00000000",
}


DAY_CODES = {
    "monday": "100000",
    "tuesday": "010000",
    "wednesday": "001000",
    "thursday": "000100",
    "friday": "000010",
    "saturday": "000001",
}


# ============================================================
# LOAD EDUPAGE DATA
# ============================================================

def get_timetable():
    global timetable_cache
    global cache_time

    current_time = time.time()

    if (
        timetable_cache is not None
        and current_time - cache_time < CACHE_DURATION
    ):
        return timetable_cache

    response = requests.post(
        EDUPAGE_URL,
        json=EDUPAGE_PAYLOAD,
        timeout=30,
    )

    response.raise_for_status()

    timetable_cache = response.json()
    cache_time = current_time

    return timetable_cache


# ============================================================
# EDUPAGE HELPERS
# ============================================================

def _period_time_from_edupage(
    data,
    selected_period,
):
    try:
        periods = data.get("r", {}).get("periods", [])

        period_number = int(selected_period)

        for period in periods:
            if str(
                period.get("id")
            ) == str(period_number):

                start = (
                    period.get("starttime")
                    or period.get("start")
                    or ""
                )

                end = (
                    period.get("endtime")
                    or period.get("end")
                    or ""
                )

                if start and end:
                    return f"{start} - {end}"

    except Exception:
        pass

    return ""


def _edupage_rooms_and_occupied(
    data,
    selected_day,
    selected_period,
):
    rooms = set()
    occupied = set()

    # --------------------------------------------------------
    # This section keeps the existing EduPage logic flexible.
    # --------------------------------------------------------

    try:
        timetable = data.get("r", {})

        # Collect rooms wherever EduPage exposes them.
        for room in timetable.get("rooms", []):
            if isinstance(room, dict):
                name = (
                    room.get("short")
                    or room.get("name")
                    or room.get("id")
                )

                if name:
                    rooms.add(str(name))

    except Exception:
        pass

    # --------------------------------------------------------
    # Parse lessons.
    # --------------------------------------------------------

    try:
        lessons = (
            data.get("r", {}).get("tt", [])
        )

        day_code = DAY_CODES.get(
            selected_day
        )

        for lesson in lessons:

            if not isinstance(
                lesson,
                dict,
            ):
                continue

            lesson_day = (
                lesson.get("day")
                or lesson.get("days")
                or lesson.get("daycode")
            )

            if (
                day_code
                and lesson_day
                and str(lesson_day) != day_code
                and str(lesson_day) != selected_day
            ):
                continue

            period = (
                lesson.get("period")
                or lesson.get("periodid")
                or lesson.get("hour")
            )

            try:
                period = int(period)
            except (
                TypeError,
                ValueError,
            ):
                continue

            if period != int(
                selected_period
            ):
                continue

            lesson_rooms = (
                lesson.get("rooms")
                or lesson.get("room")
                or []
            )

            if isinstance(
                lesson_rooms,
                str,
            ):
                lesson_rooms = [
                    lesson_rooms
                ]

            for room in lesson_rooms:

                if isinstance(
                    room,
                    dict,
                ):
                    room_name = (
                        room.get("short")
                        or room.get("name")
                        or room.get("id")
                    )
                else:
                    room_name = str(room)

                if room_name:
                    room_name = str(
                        room_name
                    ).strip()

                    rooms.add(room_name)
                    occupied.add(
                        room_name
                    )

    except Exception as exc:
        app.logger.warning(
            "Could not parse EduPage lessons: %s",
            exc,
        )

    return rooms, occupied


# ============================================================
# LOAD PDF TIMETABLES
# ============================================================

def _load_pdf_sources() -> list[dict]:
    records: list[dict] = []

    # Local PDFs
    for path in PDF_FILES:

        try:
            records.extend(
                parse_pdf_file(path)
            )

        except FileNotFoundError:

            app.logger.warning(
                "PDF timetable file not found: %s",
                path,
            )

        except Exception as exc:

            app.logger.exception(
                "Could not parse PDF timetable %s: %s",
                path,
                exc,
            )

    # Optional PDF URLs
    for url in PDF_URLS:

        try:
            response = requests.get(
                url,
                timeout=30,
            )

            response.raise_for_status()

            records.extend(
                parse_pdf_bytes(
                    response.content,
                    source_name=url,
                )
            )

        except Exception as exc:

            app.logger.exception(
                "Could not download/parse PDF timetable %s: %s",
                url,
                exc,
            )

    return records


def get_pdf_records() -> list[dict]:
    global pdf_cache

    current_time = time.time()

    if (
        pdf_cache is not None
        and current_time - pdf_cache[0]
        < CACHE_DURATION
    ):
        return pdf_cache[1]

    records = _load_pdf_sources()

    pdf_cache = (
        current_time,
        records,
    )

    return records


# ============================================================
# LOAD EXCEL TIMETABLES
# ============================================================

def _load_excel_sources() -> list[dict]:
    records: list[dict] = []

    for path in EXCEL_FILES:

        try:

            records.extend(
                parse_excel_file(path)
            )

        except FileNotFoundError:

            app.logger.warning(
                "Excel timetable file not found: %s",
                path,
            )

        except Exception as exc:

            app.logger.exception(
                "Could not parse Excel timetable %s: %s",
                path,
                exc,
            )

    return records


def get_excel_records() -> list[dict]:
    global excel_cache

    current_time = time.time()

    if (
        excel_cache is not None
        and current_time - excel_cache[0]
        < CACHE_DURATION
    ):
        return excel_cache[1]

    records = _load_excel_sources()

    excel_cache = (
        current_time,
        records,
    )

    return records


# ============================================================
# HOME
# ============================================================

@app.route(
    "/",
    methods=["GET", "POST"],
)
def home():

    selected_day = ""
    selected_period = ""
    time_label = ""

    vacant_rooms = []

    # --------------------------------------------------------
    # Load PDF records
    # --------------------------------------------------------

    pdf_records = get_pdf_records()

    pdf_rooms = {
        record["room"]
        for record in pdf_records
        if record.get("room")
    }

    # --------------------------------------------------------
    # Load Excel records
    # --------------------------------------------------------

    excel_records = get_excel_records()

    excel_rooms = {
        record["room"]
        for record in excel_records
        if record.get("room")
    }

    # --------------------------------------------------------
    # POST request
    # --------------------------------------------------------

    if request.method == "POST":

        selected_day = (
            request.form["day"]
            .lower()
        )

        selected_period = (
            request.form["period"]
        )

        selected_period_int = int(
            selected_period
        )

        # ----------------------------------------------------
        # EduPage
        # ----------------------------------------------------

        data = get_timetable()

        (
            edupage_rooms,
            edupage_occupied,
        ) = _edupage_rooms_and_occupied(
            data,
            selected_day,
            selected_period_int,
        )

        time_label = (
            _period_time_from_edupage(
                data,
                selected_period,
            )
        )

        # ----------------------------------------------------
        # ALL ROOMS
        # ----------------------------------------------------

        all_rooms = (
            edupage_rooms
            | pdf_rooms
            | excel_rooms
        )

        # ----------------------------------------------------
        # OCCUPIED ROOMS
        # ----------------------------------------------------

        occupied_rooms = set(
            edupage_occupied
        )

        # ----------------------------------------------------
        # PDF occupancy
        # ----------------------------------------------------

        for record in pdf_records:

            if (
                record.get("day")
                == selected_day
                and record.get("period")
                == selected_period_int
            ):

                room = record.get(
                    "room"
                )

                if room:
                    occupied_rooms.add(
                        room
                    )

        # ----------------------------------------------------
        # EXCEL occupancy
        # ----------------------------------------------------

        for record in excel_records:

            if (
                record.get("day")
                == selected_day
                and record.get("period")
                == selected_period_int
            ):

                room = record.get(
                    "room"
                )

                if room:
                    occupied_rooms.add(
                        room
                    )

        # ----------------------------------------------------
        # VACANT ROOMS
        # ----------------------------------------------------

        vacant_rooms = sorted(
            all_rooms - occupied_rooms
        )

    return render_template(
        "index.html",
        vacant_rooms=vacant_rooms,
        selected_day=selected_day,
        selected_period=selected_period,
        time=time_label,
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "5000",
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
    )
