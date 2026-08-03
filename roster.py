"""Roster import helpers.

The administrator uploads the project-defence roster as a CSV, TSV, XLSX or
Word (``.docx``) file; this module turns the raw rows into normalised defence
records ready to be inserted. Header detection is flexible so common column
names ("Student", "Project Title", "Session/Date", "Time Schedule", "Venue",
...) are recognised regardless of order, capitalisation or extra whitespace.
"""

import csv
import io
import re
from datetime import date, datetime

DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%d-%m-%y",
    "%d.%m.%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%d-%b-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%b %d %Y",
    "%d %B, %Y",
    "%Y/%m/%d",
]

# Ordered: earlier entries win when several headers match a column.
_COLUMN_ALIASES = {
    "student_name": [
        "student name", "student's name", "student", "candidate",
        "candidate name", "candidate's name", "full name", "fullname",
        "name of student", "names", "name",
    ],
    "project_title": [
        "project title", "project topic", "projectwork", "project work",
        "project", "title of project", "topic", "topics", "research title",
        "title",
    ],
    "venue": [
        "venue", "defence venue", "room", "hall", "location", "venue / room",
    ],
    "event_date": [
        "date", "defence date", "presentation date", "day", "date of defence",
        "date & time", "date/time", "datetime",
        "session/date", "session date", "session & date", "session and date",
    ],
    "start_time": [
        "start time", "time start", "start", "start at", "commencement time",
        "from", "time",
    ],
    "end_time": [
        "end time", "time end", "end", "end at", "finish time", "to",
    ],
    "time_schedule": [
        "time schedule", "schedule time", "time scheduled", "time slot",
        "time range", "start & end", "start and end", "start-end",
    ],
    "supervisor": [
        "supervisor", "project supervisor", "supervisor's name",
        "supervisor name", "supervisors",
    ],
}


def _norm_header(value):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(value or "").strip().lower()))


def _match_column(header):
    """Map a raw header string to a defence field name, or None."""
    normalised = _norm_header(header)
    words = normalised.replace("/", " ").split()
    for field, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            alias_norm = re.sub(r"[^a-z0-9 ]", " ", alias.lower())
            if alias_norm == normalised:
                return field
            # tolerate "date/time" split across words
            alias_words = alias_norm.split()
            if alias_words and words and words == alias_words:
                return field
    return None


def parse_date(value):
    """Parse a roster date value into an ISO 'YYYY-MM-DD' string, or None.

    The whole cell is tried against ``DATE_FORMATS`` first; if that fails the
    date is looked up anywhere inside the text, so headers like
    "Session 1: July 31 2026 (Morning)" still yield a date.
    """
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except (ValueError, TypeError):
            continue
    return _extract_date(text)


_MONTHS_FULL = {
    "jan": "January", "feb": "February", "mar": "March", "apr": "April",
    "may": "May", "jun": "June", "jul": "July", "aug": "August",
    "sep": "September", "sept": "September", "oct": "October",
    "nov": "November", "dec": "December",
}


def _month_word(word):
    return _MONTHS_FULL.get(word.lower(), word.capitalize())


def _parse_month_date(month_word, day, year, fmt):
    month = _month_word(month_word)
    candidate = ("%s %s %s" % (day, month, year)
                 if fmt == "%d %B %Y"
                 else "%s %s %s" % (month, day, year))
    try:
        return datetime.strptime(candidate, fmt).date().isoformat()
    except (ValueError, TypeError):
        return None


def _extract_date(text):
    """Find and parse a date embedded anywhere in ``text``."""
    match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if match:
        return "%s-%s-%s" % (
            match.group(1), match.group(2).zfill(2), match.group(3).zfill(2))

    match = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b", text)
    if match:
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y",
                    "%d.%m.%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(
                    "%s/%s/%s" % (match.group(1), match.group(2), match.group(3)),
                    fmt,
                ).date().isoformat()
            except (ValueError, TypeError):
                continue
        return None

    match = re.search(r"\b(\d{1,2})\s+([A-Za-z]+)[.,]?\s+(\d{2,4})\b", text)
    if match:
        return _parse_month_date(match.group(2), match.group(1),
                                 match.group(3), "%d %B %Y")

    match = re.search(r"\b([A-Za-z]+)\s+(\d{1,2})[.,]?\s+(\d{2,4})\b", text)
    if match:
        return _parse_month_date(match.group(1), match.group(2),
                                 match.group(3), "%B %d %Y")
    return None


def parse_time(value):
    """Parse a roster time value into an 'HH:MM' string, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if isinstance(value, (int, float)):
        # Excel may hand us a fraction of a day or a serial number.
        if 0 <= value <= 1:
            total = round(value * 24 * 60)
            return f"{total // 60:02d}:{total % 60:02d}"
        total = round((float(value) % 1) * 24 * 60)
        return f"{total // 60:02d}:{total % 60:02d}"
    text = str(value).strip().lower().replace(" ", "")
    if not text:
        return None
    match = re.match(r"^(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*(am|pm)?$", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = match.group(3)
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def parse_time_range(value):
    """Parse a cell holding a start–end range, e.g. '10:00 AM - 10:45 AM'.

    Accepts times separated by ``-``, en/em dashes, ``~`` or the word "to".
    Returns ``(start, end)`` as 'HH:MM' strings; ``end`` is ``None`` when the
    cell holds a single time. If only the last token carries AM/PM, the
    meridiem is applied to the first token too (so "1:00 - 2:00 PM" means
    13:00–14:00).
    """
    if value is None:
        return (None, None)
    text = str(value).strip()
    if not text:
        return (None, None)
    tokens = [
        t.strip()
        for t in re.findall(r"\d{1,2}(?::\d{2})?\s*(?:am|pm)?", text, flags=re.IGNORECASE)
        if t.strip()
    ]
    if not tokens:
        return (None, None)
    first = tokens[0]
    meridiem = re.search(r"(am|pm)", tokens[-1], flags=re.IGNORECASE)
    if meridiem and not re.search(r"(am|pm)", first, flags=re.IGNORECASE):
        first = first + " " + meridiem.group(1)
    start = parse_time(first)
    if start is None:
        return (None, None)
    if len(tokens) < 2:
        return (start, None)
    return (start, parse_time(tokens[-1]))


def parse_roster(filename, content, default_venue=None):
    """Parse an uploaded roster file.

    ``filename`` is used to detect the format; ``content`` is raw bytes.
    ``default_venue`` (optional) is applied to every row — use it when the
    whole file belongs to a single venue, e.g. the Hall A roster.
    Returns a dict with ``rows`` (normalised defence dicts), ``errors`` and
    ``warnings`` (human-readable messages), and ``summary``.
    """
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    header_row, data_rows = _read_table(filename, content)
    if not header_row:
        return {
            "rows": [], "errors": ["Could not read a header row from the file."],
            "warnings": [], "summary": None,
        }

    mapping = {}
    for index, header in enumerate(header_row):
        field = _match_column(header)
        if field and field not in mapping:
            mapping[index] = field

    warnings = []
    missing = [f for f in _COLUMN_ALIASES if f not in mapping.values()]
    if "time_schedule" in mapping.values():
        missing = [f for f in missing if f not in ("start_time", "end_time")]
    optional = [f for f in missing if f in ("venue", "supervisor")]
    required = [f for f in missing if f not in optional]
    if default_venue:
        optional = [f for f in optional if f != "venue"]
    if required:
        warnings.append(
            "Columns not found in the file: "
            + ", ".join(required) + ". Those fields will be left empty."
        )
    elif optional:
        warnings.append(
            "Optional columns not found in the file: "
            + ", ".join(optional) + ". Those fields will be left empty."
        )

    rows = []
    errors = []
    skipped = 0
    last_date = None
    for row_index, raw in enumerate(data_rows, start=2):
        cells = [str(c).strip() if c is not None else "" for c in raw]
        if not any(cells):
            continue
        if not any((k in mapping) for k in range(len(cells))):
            skipped += 1
            continue
        record = {}
        for index, field in mapping.items():
            value = cells[index] if index < len(cells) else ""
            record[field] = value

        has_name = bool((record.get("student_name") or "").strip())
        has_title = bool((record.get("project_title") or "").strip())
        if not has_name and not has_title:
            # Not a real defence entry (spacer row, section header, footnote) —
            # ignore it silently rather than failing the import.
            skipped += 1
            continue

        row_errors = []
        if not has_name:
            row_errors.append("missing student name")
        if not has_title:
            row_errors.append("missing project title")

        raw_date = record.get("event_date")
        event_date = parse_date(raw_date)
        if not event_date and raw_date and str(raw_date).strip():
            row_errors.append("unreadable date (%r)" % raw_date)
        if not event_date:
            # Merged/section-header cells leave later rows blank — inherit the
            # date from the previous row ("Session 1: July 31 2026" then blanks).
            event_date = last_date
        if event_date:
            last_date = event_date
        if not event_date:
            row_errors.append("no date for this row")

        raw_start = record.get("start_time")
        raw_end = record.get("end_time")
        if record.get("time_schedule"):
            range_start, range_end = parse_time_range(record.get("time_schedule"))
            if not raw_start:
                raw_start = range_start
            if not raw_end:
                raw_end = range_end

        start_time = parse_time(raw_start)
        if not start_time:
            # A plain "Time"/start column may still hold a range
            # ("1:30pm - 1:40pm") rather than a single time.
            range_start, range_end = parse_time_range(raw_start)
            if range_start:
                raw_start = range_start
                if not raw_end and range_end:
                    raw_end = range_end
                start_time = range_start
        if not start_time:
            row_errors.append(
                "unreadable start time (%r)"
                % (record.get("time_schedule") or record.get("start_time") or "")
            )
        end_time = parse_time(raw_end)
        if end_time and start_time and end_time < start_time:
            row_errors.append("end time is before start time")

        if row_errors:
            errors.append(f"Row {row_index}: " + "; ".join(row_errors) + ".")
            continue

        rows.append({
            "student_name": record.get("student_name") or "",
            "project_title": record.get("project_title") or "",
            "venue": default_venue if default_venue else (record.get("venue") or None),
            "supervisor": record.get("supervisor") or None,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
        })

    if skipped:
        warnings.append(
            f"Ignored {skipped} row(s) that didn't look like defence entries "
            "(no student name / project title)."
        )

    summary = None
    if rows:
        venues = sorted({r["venue"] for r in rows if r.get("venue")})
        dates = sorted({r["event_date"] for r in rows})
        by_date = {}
        for r in rows:
            by_date[r["event_date"]] = by_date.get(r["event_date"], 0) + 1
        summary = {
            "total": len(rows),
            "venues": venues,
            "date_range": [dates[0], dates[-1]] if dates else [],
            "by_date": [{"date": d, "count": by_date[d]} for d in dates],
        }

    return {"rows": rows, "errors": errors, "warnings": warnings, "summary": summary}


def _read_table(filename, content):
    """Return (header_row, data_rows) as lists of lists."""
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if ext == "xlsx":
        return _read_xlsx(content)
    if ext == "docx":
        return _read_docx(content)
    if ext == "tsv" or ext == "txt":
        delimiter = "\t"
    else:
        delimiter = ","
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    raw_rows = [list(r) for r in reader]
    return _split_header(raw_rows)


def _read_docx(content):
    """Read the roster out of a Word (``.docx``) document.

    A Word roster is a document containing tables. Every table is flattened
    into rows of cells (paragraph text joined with spaces) and the whole thing
    is treated as one table for header detection. Repeated header rows across
    multiple tables are dropped. Uses only the standard library.
    """
    import zipfile
    from xml.etree import ElementTree

    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError):
        return [], []
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return [], []

    raw_rows = []
    for tbl in root.iter(W + "tbl"):
        for tr in tbl.iter(W + "tr"):
            cells = []
            for tc in tr.iter(W + "tc"):
                paragraphs = []
                for p in tc.iter(W + "p"):
                    text = "".join(t.text or "" for t in p.iter(W + "t")).strip()
                    if text:
                        paragraphs.append(text)
                cells.append(" ".join(paragraphs))
            raw_rows.append(cells)

    header_row, data_rows = _split_header(raw_rows)
    if header_row:
        data_rows = [
            row for row in data_rows
            if [str(c).strip() if c is not None else "" for c in row] != header_row
        ]
    return header_row, data_rows


def _read_xlsx(content):
    import openpyxl  # noqa: WPS433 — optional dependency, imported lazily.

    workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    sheet = workbook.active
    raw_rows = []
    for row in sheet.iter_rows(values_only=True):
        raw_rows.append(list(row))
    workbook.close()
    return _split_header(raw_rows)


def _split_header(raw_rows):
    """Find the first plausible header row among the leading non-empty rows."""
    for offset, row in enumerate(raw_rows):
        non_empty = [str(c).strip() if c is not None else "" for c in row]
        if not any(non_empty):
            continue
        matched = sum(1 for c in non_empty if _match_column(c) is not None)
        if matched >= 2:
            return [c for c in non_empty if c != ""], raw_rows[offset + 1:]
    return [], []
