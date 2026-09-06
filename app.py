from flask import Flask, render_template, request
import requests

app = Flask(__name__)


# --------------------------------
# Get LIVE timetable from EduPage
# --------------------------------

def get_timetable():

    url = "https://iilmgn.edupage.org/timetable/server/regulartt.js?__func=regularttGetData"

    data = {
        "__args": [None, "37"],
        "__gsh": "00000000"
    }

    response = requests.post(url, json=data)

    return response.json()


# --------------------------------
# Home Page
# --------------------------------

@app.route("/", methods=["GET", "POST"])
def home():

    # Get LIVE timetable
    data = get_timetable()

    tables = data["r"]["dbiAccessorRes"]["tables"]

    # Find required tables
    for table in tables:

        if table["id"] == "cards":
            cards = table

        elif table["id"] == "classrooms":
            classrooms = table

        elif table["id"] == "periods":
            periods = table

        elif table["id"] == "lessons":
            lessons = table


    # --------------------------------
    # Room ID → Room Name
    # --------------------------------

    room_names = {}

    for room in classrooms["data_rows"]:
        room_names[room["id"]] = room["name"]


    # --------------------------------
    # Period → Time
    # --------------------------------

    period_times = {}

    for period in periods["data_rows"]:

        period_times[period["id"]] = (
            period["starttime"] + " - " + period["endtime"]
        )


    # --------------------------------
    # Lesson ID → Duration
    # --------------------------------

    lesson_duration = {}

    for lesson in lessons["data_rows"]:

        lesson_duration[lesson["id"]] = lesson["durationperiods"]


    # --------------------------------
    # Day Codes
    # --------------------------------

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


    # --------------------------------
    # Search
    # --------------------------------

    if request.method == "POST":

        selected_day = request.form["day"]
        selected_period = request.form["period"]

        day_code = day_codes[selected_day]

        occupied_rooms = []

        selected = int(selected_period)


        # Check every timetable card
        for card in cards["data_rows"]:

            card_days = card.get("days", "")

            if len(card_days) < 6:
                card_days = card_days.zfill(6)

            # Check if selected day is included
            if day_code not in card_days:
                continue


            start_period = int(card["period"])

            duration = lesson_duration.get(
                card["lessonid"],
                1
            )


            # Check multi-period lessons
            if start_period <= selected < start_period + duration:

                for room_id in card["classroomids"]:

                    if room_id in room_names:

                        occupied_rooms.append(
                            room_names[room_id]
                        )


        # Remove duplicates
        occupied_rooms = set(occupied_rooms)


        # Find vacant rooms
        for room in room_names.values():

            if room not in occupied_rooms:

                vacant_rooms.append(room)


        # Get period timing
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


# --------------------------------
# Start App
# --------------------------------

if __name__ == "__main__":
    app.run(debug=True)