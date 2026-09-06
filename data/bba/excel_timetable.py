from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import openpyxl


PERIOD_COLUMNS = {
    4: 1,
    5: 2,
    6: 3,
    8: 4,
    9: 5,
    10: 6,
}


DAY_MAP = {
    "mon": "monday",
    "monday": "monday",
    "tue": "tuesday",
    "tues": "tuesday",
    "tuesday": "tuesday",
    "wed": "wednesday",
    "wednesday": "wednesday",
    "thu": "thursday",
    "thur": "thursday",
    "thurs": "thursday",
    "thursday": "thursday",
    "fri": "friday",
    "friday": "friday",
    "sat": "saturday",
    "saturday": "saturday",
    "sun": "sunday",
    "sunday": "sunday",
}


def _clean(value: Any) -> str:
    if value is None:
        return ""

    return " ".join(str(value).split())


def _room_from_header(sheet) -> str:
    for row in range(1, 4):
        for col in range(1, 4):
            value = _clean(
                sheet.cell(row=row, column=col).value
            )

            match = re.search(
                r"Room\s*No\s*:\s*-?\s*([0-9A-Za-z]+)",
                value,
                re.IGNORECASE,
            )

            if match:
                return match.group(1)

    return ""


def _section_from_header(sheet) -> str:
    for row in range(1, 4):
        for col in range(1, 4):
            value = _clean(
                sheet.cell(row=row, column=col).value
            )

            match = re.search(
                r"Section\s*[-:]?\s*([A-Za-z0-9]+)",
                value,
                re.IGNORECASE,
            )

            if match:
                return match.group(1)

    return sheet.title


def _extract_room_for_subject(
    subject: str,
    note: str,
    default_room: str,
) -> str:

    subject = _clean(subject)
    note = _clean(note)

    if not note:
        return default_room

    # First try to find:
    # "SUBJECT in 303"
    #
    # This prevents unrelated "in" text from becoming
    # the room name.
    subject_pattern = re.escape(subject)

    match = re.search(
        rf"{subject_pattern}\s+in\s+([0-9]+)",
        note,
        re.IGNORECASE,
    )

    if match:
        return match.group(1)

    # Handle common combined notes such as:
    # "BM & OBGD in 207"
    subject_parts = [
        part.strip()
        for part in re.split(
            r"[/&]+",
            subject,
        )
        if part.strip()
    ]

    for part in subject_parts:
        match = re.search(
            rf"{re.escape(part)}\s+in\s+([0-9]+)",
            note,
            re.IGNORECASE,
        )

        if match:
            return match.group(1)

    # Special locations.
    if re.search(
        rf"{subject_pattern}\s+in\s+seminar",
        note,
        re.IGNORECASE,
    ):
        return "Seminar Hall"

    return default_room


def parse_excel_file(
    path: str | Path,
) -> list[dict]:

    path = Path(path)

    workbook = openpyxl.load_workbook(
        path,
        data_only=True,
    )

    records = []

    for sheet in workbook.worksheets:

        default_room = _room_from_header(sheet)

        if not default_room:
            continue

        section = _section_from_header(sheet)

        for row in range(
            4,
            sheet.max_row + 1,
        ):

            day_value = _clean(
                sheet.cell(
                    row=row,
                    column=2,
                ).value
            )

            day = DAY_MAP.get(
                day_value.lower()
            )

            if not day:
                continue

            note = _clean(
                sheet.cell(
                    row=row,
                    column=11,
                ).value
            )

            for column, period in PERIOD_COLUMNS.items():

                subject = _clean(
                    sheet.cell(
                        row=row,
                        column=column,
                    ).value
                )

                if not subject:
                    continue

                room = _extract_room_for_subject(
                    subject,
                    note,
                    default_room,
                )

                records.append(
                    {
                        "day": day,
                        "period": period,
                        "room": room,
                        "section": section,
                        "source": path.name,
                        "sheet": sheet.title,
                        "subject": subject,
                    }
                )

    return records
