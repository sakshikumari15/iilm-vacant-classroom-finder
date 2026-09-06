from flask import Flask, render_template, request
import requests
import time

app = Flask(__name__)

# Store timetable data temporarily
timetable_cache = None
cache_time = 0

# Refresh timetable every 10 minutes
CACHE_DURATION = 600


def get_timetable():
    global timetable_cache, cache_time

    current_time = time.time()

    # Use cached timetable if it is still fresh
    if timetable_cache is not None and current_time - cache_time < CACHE_DURATION:
        return timetable_cache

    url = "https://iilmgn.edupage.org/timetable/server/regulartt.js?__func=regularttGetData"

    data = {
        "__args": [None, "37"],
        "__gsh": "00000000"
    }

    response = requests.post(url, json=data, timeout=15)
    response.raise_for_status()

    timetable_cache = response.json()
    cache_time = current_time

    return timetable_cache


@app.route("/", methods=["GET", "POST"])
def home():

    data = get_timetable()

    tables = data["r"]["dbiAccessorRes"]["tables"]

    for table in tables:

        if table["id"] == "cards":
            cards = table

        elif table["id"] == "classrooms":
            classrooms = table

        elif table["id"] == "periods":
            periods = table

        elif table["id"] == "lessons":
            lessons = table


    # Classroom names

    room_names = {}

    for room in classrooms["data_rows"]:
        room_names[room["id"]] = room["name"]


    # Period timings

    period_times = {}

    for period in periods["data_rows"]:

        period_times[period["id"]] = (
            period["starttime"]
            + " - "
            + period["endtime"]
        )


    # Lesson duration

    lesson_duration = {}

    for lesson in lessons["data_rows"]:

        lesson_duration[lesson["id"]] = lesson["durationperiods"]


    # Day codes

    day_codes = {

        "monday": "100000",
        "tuesday": "010000",
        "wednesday": "001000",
        "thursday": "000100",
        "friday": "000010",
        "saturday": "000001"

    }


    vacant_rooms = []

    selected_day = ""
    selected_period = ""
    time = ""


    if request.method == "POST":

        selected_day = request.form["day"]

        selected_period = request.form["period"]

        day_code = day_codes[selected_day]

        occupied_rooms = []

        selected = int(selected_period)


        for card in cards["data_rows"]:

            card_days = card.get("days", "")

            if len(card_days) < 6:
                card_days = card_days.zfill(6)


            if day_code not in card_days:
                continue


            start_period = int(card["period"])

            duration = lesson_duration.get(
                card["lessonid"],
                1
            )


            if start_period <= selected < start_period + duration:

                for room_id in card["classroomids"]:

                    if room_id in room_names:

                        occupied_rooms.append(
                            room_names[room_id]
                        )


        occupied_rooms = set(occupied_rooms)


        for room in room_names.values():

            if room not in occupied_rooms:

                vacant_rooms.append(room)


        time = period_times.get(
            selected_period,
            "Unknown"
        )


    return render_template(

        "index.html",

        vacant_rooms=vacant_rooms,

        selected_day=selected_day,

        selected_period=selected_period,

        time=time

    )


if __name__ == "__main__":

    app.run(debug=True)