"""PDF timetable adapter for the IILM vacant classroom finder.

The parser is intentionally source-oriented: it converts each timetable PDF into
simple records of (day, period, room, section, source) so the Flask app can merge
PDF data with the existing EduPage timetable without changing the UI.
"""

from __future__ import annotations

import re
import statistics
from pathlib import Path
from typing import Iterable

import fitz  # PyMuPDF

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")

# Room names seen in the current Biotech/Bioinformatics/Food Technology PDF.
# New PDFs can add rooms without changing the rest of the application as long as
# the room appears in one of these recognizable forms. Add a pattern here if a
# future branch introduces a new naming convention.
ROOM_PATTERNS = (
    r"Foundation Block\s*90",
    r"EB\d+[A-Z]?",
    r"SVH\d+[A-Z]?",
    r"Food Technology Lab",
    r"Project Lab",
    r"PTC Lab",
    r"Immunology(?: - BT)? Lab",
    r"BioChemistry Lab",
    r"Biochemistry Lab",
    r"Plant Tissue Culture Lab",
    r"Genetic Engg\.? Lab",
    r"Genetic Engineering Lab",
    r"Microbiology/?Fermentation Lab\.?",
    r"Microbiology Lab",
    r"Physics Lab 2",
    r"Chemistry Lab - NR Block",
    r"Chemistry Lab",
)
ROOM_RE = re.compile("|".join(f"({p})" for p in ROOM_PATTERNS), re.IGNORECASE)

SECTION_RE = re.compile(r"[1-4](?:BT|BI|FT)\d*", re.IGNORECASE)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _cluster(values: Iterable[float], tolerance: float = 2.5) -> list[float]:
    groups: list[list[float]] = []
    for value in sorted(values):
        if not groups or value - groups[-1][-1] > tolerance:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [sum(group) / len(group) for group in groups]


def _canonical_room(room: str) -> str:
    room = _norm(room).rstrip(".")
    aliases = {
        "biochemistry lab": "Biochemistry Lab",
        "genetic engg lab": "Genetic Engineering Lab",
        "genetic engg. lab": "Genetic Engineering Lab",
        "genetic engineering lab": "Genetic Engineering Lab",
        "foundation block 90": "Foundation Block 90",
        "microbiology/fermentation lab": "Microbiology/Fermentation Lab",
    }
    return aliases.get(room.lower(), room)


def _section(page: fitz.Page) -> str:
    for block in page.get_text("blocks"):
        text = _norm(block[4])
        if block[1] < 190 and SECTION_RE.fullmatch(text):
            return text

    top_text = " ".join(
        _norm(block[4]) for block in page.get_text("blocks") if block[1] < 210
    )
    if "M.Tech. Biotechnology I Semester" in top_text:
        return "M.Tech Biotechnology I Semester"
    if "M.Tech. Bioinformatics I Semester" in top_text:
        return "M.Tech Bioinformatics I Semester"
    return f"PDF page {page.number + 1}"


def _period_bounds(page: fitz.Page) -> list[float] | None:
    """Return the 10 x-boundaries for the 9 timetable periods."""
    xs: list[float] = []

    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.x - p2.x) < 2 and 130 < p1.y < 900:
                    xs.append(p1.x)
            elif item[0] == "re":
                rect = item[1]
                if rect.width < 400 and 130 < rect.y0 < 900:
                    xs.extend((rect.x0, rect.x1))

    candidates = _cluster(xs)
    best: tuple[float, list[float]] | None = None

    for start in range(max(0, len(candidates) - 9)):
        run = candidates[start : start + 10]
        if len(run) != 10:
            continue
        gaps = [run[i + 1] - run[i] for i in range(9)]
        median_gap = statistics.median(gaps)
        if not 60 <= median_gap <= 160:
            continue
        score = sum(abs(gap - median_gap) for gap in gaps) / median_gap
        if best is None or score < best[0]:
            best = (score, run)

    if best is not None:
        return best[1]

    # Some PDF pages expose the entire period header as one text block instead
    # of separate cell boundaries. The header spans the nine periods evenly.
    header_blocks = [
        block
        for block in page.get_text("blocks")
        if "9:00 - 9:55" in _norm(block[4])
    ]
    if not header_blocks:
        header_blocks = [
            block
            for block in page.get_text("blocks")
            if _norm(block[4]).startswith("1 2 3 4 5 6 7 8 9")
        ]

    if header_blocks:
        block = header_blocks[0]
        left, right = block[0], block[2]
        return [left + i * (right - left) / 9 for i in range(10)]

    return None


def _day_bounds(page: fitz.Page) -> list[tuple[str, float, float]]:
    day_positions: dict[str, list[float]] = {}

    for block in page.get_text("blocks"):
        text = _norm(block[4])
        center_y = (block[1] + block[3]) / 2
        for day in DAYS:
            if re.search(rf"\b{day}\b", text):
                day_positions.setdefault(day, []).append(center_y)

    if not day_positions:
        return []

    medians = {
        day: statistics.median(values) for day, values in day_positions.items()
    }
    ordered = sorted(medians.items(), key=lambda item: item[1])
    result: list[tuple[str, float, float]] = []

    for index, (day, center) in enumerate(ordered):
        lower = (
            (ordered[index - 1][1] + center) / 2
            if index
            else center - 45
        )
        upper = (
            (center + ordered[index + 1][1]) / 2
            if index + 1 < len(ordered)
            else center + 45
        )
        result.append((day, lower, upper))

    return result


def parse_pdf_bytes(pdf_bytes: bytes, source_name: str = "PDF") -> list[dict]:
    """Parse a timetable PDF into normalized room-occupancy records."""
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    records: list[dict] = []

    try:
        for page in document:
            period_bounds = _period_bounds(page)
            day_bounds = _day_bounds(page)
            if not period_bounds or not day_bounds:
                continue

            section = _section(page)

            for block in page.get_text("blocks"):
                x0, y0, x1, y1, raw_text = block[:5]
                text = _norm(raw_text)
                if not text:
                    continue
                if "9:00 - 9:55" in text:
                    continue
                if "IILM University" in text or "School of Engineering" in text:
                    continue

                room_match = ROOM_RE.search(text)
                if not room_match:
                    continue

                room = _canonical_room(room_match.group(0))

                # A PDF exporter can merge adjacent timetable cells when their
                # formatting is identical. If a block spans multiple period
                # columns, the room is therefore occupied for every overlapped
                # period rather than only the block's center period.
                matching_days = [
                    day
                    for day, lower, upper in day_bounds
                    if y1 >= lower and y0 <= upper
                ]
                if not matching_days:
                    continue

                for day in matching_days[:1]:
                    for period in range(9):
                        if x1 < period_bounds[period] - 3:
                            continue
                        if x0 > period_bounds[period + 1] + 3:
                            continue

                        records.append(
                            {
                                "day": day.lower(),
                                "period": period + 1,
                                "room": room,
                                "section": section,
                                "source": source_name,
                                "page": page.number + 1,
                            }
                        )
    finally:
        document.close()

    # Exact duplicates are common because the PDF text layer can contain a
    # separate room line and a room+subject line for the same cell.
    unique = {
        (
            record["day"],
            record["period"],
            record["room"],
            record["section"],
            record["source"],
        ): record
        for record in records
    }
    return sorted(
        unique.values(),
        key=lambda record: (
            record["day"],
            record["period"],
            record["room"],
            record["section"],
        ),
    )


def parse_pdf_file(path: str | Path) -> list[dict]:
    path = Path(path)
    return parse_pdf_bytes(path.read_bytes(), source_name=path.name)
