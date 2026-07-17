#!/usr/bin/env python3
"""Build the public academic-travels JSON from the confirmed XLSX workbook.

This script intentionally uses only the Python 3 standard library, so it can be
run without installing a spreadsheet package.

Usage:
    python3 tools/build_academic_travels_data.py SOURCE.xlsx [OUTPUT.json]

When OUTPUT.json is omitted, the script writes
``assets/data/academic-travels.json`` relative to the repository root.
"""

import datetime as dt
import json
import math
import os
import posixpath
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET


SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT = REPOSITORY_ROOT / "assets" / "data" / "academic-travels.json"

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOCUMENT_REL_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
MAIN = "{%s}" % MAIN_NS
DOCUMENT_REL = "{%s}" % DOCUMENT_REL_NS
PACKAGE_REL = "{%s}" % PACKAGE_REL_NS

REQUIRED_EVENT_FIELDS = (
    "event_id",
    "event_name",
    "start_date",
    "end_date",
    "event_type",
    "host_organization",
    "venue",
    "city",
    "country",
    "latitude",
    "longitude",
    "location_precision",
)

REQUIRED_TALK_FIELDS = ("event_id", "talk_order", "talk_title")

CELL_REFERENCE = re.compile(r"^\$?([A-Z]+)\$?([1-9][0-9]*)$", re.IGNORECASE)
INTEGER = re.compile(r"^[+-]?[0-9]+$")
ISO_DATE = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})(?:T.*)?$"
)

HOST_NAME_REPLACEMENTS = {
    "Australian Institute of Physics (NSW Branch)": "Australian Institute of Physics",
    "International Society for Relativistic Quantum Information (ISRQI)": (
        "International Society for Relativistic Quantum Information"
    ),
}

# These editorial corrections were agreed after the confirmed workbook was
# produced. Keeping them here ensures a future rebuild from that workbook does
# not silently restore the superseded labels.
EVENT_EDITORIAL_OVERRIDES = {
    "2018-amsi-winter-school-curvature-brisbane": {
        "host_organization": "Australian Mathematical Sciences Institute",
    },
    "2019-ens-lyon-theory-seminar": {
        "venue": "École normale supérieure de Lyon",
    },
    "2024-aip-congress-melbourne": {
        "venue": "Melbourne Convention and Exhibition Centre",
    },
    "2024-cfps-seminar-prague": {
        "event_name": "FZU Seminar — Cosmology, Fundamental Physics, and Strings",
    },
    "2025-gr24-glasgow": {
        "host_organization": (
            "University of Glasgow; "
            "International Society on General Relativity and Gravitation"
        ),
    },
}

POSTER_CONTRIBUTIONS = {
    ("2018-aip-congress-perth", 1),
    ("2024-vienna-quantum-foundations", 1),
}

TALK_RECORDING_OVERRIDES = {
    ("2025-gr24-glasgow", 1): "https://youtu.be/UOE1d95je1I?t=1860",
}

# Per-talk publication links. The first tuple item is the button label and the
# second is the destination. DOI links are labelled "Publication"; the single
# work that remains a preprint is labelled "Preprint".
PUBLICATION_LINKS = {
    ("2026-rqi-circuit-postdoc-meeting-villamartin", 1): (
        "Preprint",
        "https://arxiv.org/abs/2506.15291",
    ),
    ("2025-relativity-seminar-charles-prague", 1): (
        "Publication",
        "https://doi.org/10.1142/S0218271822300154",
    ),
    ("2023-tohoku-seminar-sendai", 1): (
        "Publication",
        "https://doi.org/10.1142/S0218271822300154",
    ),
    ("2022-northern-sydney-astronomical-society", 1): (
        "Publication",
        "https://doi.org/10.1142/S0218271822300154",
    ),
    ("2025-quantum-gravity-penn-state", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.110.044064",
    ),
    ("2025-gr24-glasgow", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.110.044064",
    ),
    ("2024-cfps-seminar-prague", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.110.044064",
    ),
    ("2025-rqi-north-naples", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.111.044001",
    ),
    ("2024-aip-congress-melbourne", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.111.044001",
    ),
    ("2024-rqi-north-prague", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.111.044001",
    ),
    ("2024-marcel-grossmann-17-pescara", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.111.044001",
    ),
    ("2024-vienna-quantum-foundations", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevA.109.062224",
    ),
    ("2024-dice-castiglioncello", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevA.109.062224",
    ),
    ("2024-black-holes-cosmology-nassau", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.108.124007",
    ),
    ("2024-rqi-south-brisbane", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.108.124007",
    ),
    ("2024-gravity-cosmology-kyoto", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.108.124007",
    ),
    ("2023-minkowski-meeting-albena", 1): (
        "Publication",
        "https://doi.org/10.1142/S0218271823420129",
    ),
    ("2023-rqi-north-chania", 1): (
        "Publication",
        "https://doi.org/10.1142/S0218271823420129",
    ),
    ("2023-quantum-gravity-nijmegen", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.108.044002",
    ),
    ("2022-aip-congress-adelaide", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.105.124032",
    ),
    ("2022-aip-congress-adelaide", 2): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.105.044051",
    ),
    ("2020-aip-postgraduate-awards", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.105.044051",
    ),
    ("2019-gr22-valencia", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.100.064054",
    ),
    ("2019-gr22-valencia", 2): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.99.124014",
    ),
    ("2019-ens-lyon-theory-seminar", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.100.064054",
    ),
    ("2019-rqi-south-brisbane", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.100.064054",
    ),
    ("2018-aip-congress-perth", 1): (
        "Publication",
        "https://doi.org/10.1103/PhysRevD.99.124014",
    ),
}


class BuildError(Exception):
    """A concise, user-facing workbook or data validation error."""


def usage() -> str:
    return "\n".join(
        (
            "Usage:",
            "  python3 tools/build_academic_travels_data.py "
            "<source.xlsx> [output.json]",
        )
    )


def is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def clean_text(value: Any) -> Optional[str]:
    return None if is_blank(value) else str(value).strip()


def required_text(row: Mapping[str, Any], field: str, row_label: str) -> str:
    value = clean_text(row.get(field))
    if value is None:
        raise BuildError("{}: required field '{}' is blank".format(row_label, field))
    return value


def normalize_host_organizations(value: Any, row_label: str) -> str:
    text = clean_text(value)
    if text is None:
        raise BuildError(
            "{}: required field 'host_organization' is blank".format(row_label)
        )

    hosts: List[str] = []
    for raw_host in text.split(";"):
        host = raw_host.strip()
        if not host:
            raise BuildError(
                "{}: 'host_organization' contains an empty semicolon-delimited host".format(
                    row_label
                )
            )
        host = HOST_NAME_REPLACEMENTS.get(host, host)
        if host not in hosts:
            hosts.append(host)
    return "; ".join(hosts)


def validate_iso_date(value: str, row_label: str, field: str) -> str:
    match = ISO_DATE.fullmatch(value)
    if match is None or "T" in value:
        raise BuildError("{}: '{}' is not an ISO date: {}".format(row_label, field, value))

    try:
        dt.date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError:
        raise BuildError("{}: '{}' is not a valid date: {}".format(row_label, field, value))
    return value


def excel_serial_to_iso_date(
    serial: Any, row_label: str, field: str, date_1904: bool
) -> str:
    if isinstance(serial, bool) or not isinstance(serial, (int, float)):
        raise BuildError("{}: '{}' is not a finite Excel date".format(row_label, field))
    if not math.isfinite(serial):
        raise BuildError("{}: '{}' is not a finite Excel date".format(row_label, field))

    # Math.floor(x + 0.5) matches JavaScript's Math.round for Excel's ordinary
    # non-negative date serials. The 1899-12-30 epoch preserves Excel's 1900
    # leap-year compatibility convention.
    whole_days = math.floor(serial + 0.5)
    epoch = dt.date(1904, 1, 1) if date_1904 else dt.date(1899, 12, 30)
    try:
        parsed = epoch + dt.timedelta(days=whole_days)
    except (OverflowError, ValueError):
        raise BuildError("{}: '{}' is not a valid Excel date".format(row_label, field))
    return parsed.isoformat()


def normalize_date(
    value: Any,
    row_label: str,
    field: str,
    date_1904: bool,
    optional: bool = False,
) -> Optional[str]:
    if is_blank(value):
        if optional:
            return None
        raise BuildError("{}: required field '{}' is blank".format(row_label, field))

    if isinstance(value, bool):
        raise BuildError(
            "{}: '{}' has unsupported date value '{}'".format(row_label, field, value)
        )

    if isinstance(value, (int, float)):
        parsed = excel_serial_to_iso_date(value, row_label, field, date_1904)
        return validate_iso_date(parsed, row_label, field)

    text = str(value).strip()
    match = ISO_DATE.fullmatch(text)
    if match is not None:
        parsed = "{}-{}-{}".format(
            match.group("year"), match.group("month"), match.group("day")
        )
        return validate_iso_date(parsed, row_label, field)

    raise BuildError(
        "{}: '{}' has unsupported date value '{}'".format(row_label, field, text)
    )


def normalize_number(value: Any, row_label: str, field: str) -> Any:
    if is_blank(value):
        raise BuildError("{}: required field '{}' is blank".format(row_label, field))

    if isinstance(value, bool):
        raise BuildError("{}: '{}' is not numeric: {}".format(row_label, field, value))

    if isinstance(value, (int, float)):
        numeric = value
    else:
        try:
            numeric = float(str(value).strip())
        except ValueError:
            raise BuildError(
                "{}: '{}' is not numeric: {}".format(row_label, field, value)
            )

    if not math.isfinite(numeric):
        raise BuildError("{}: '{}' is not numeric: {}".format(row_label, field, value))

    if isinstance(numeric, float) and numeric.is_integer():
        return int(numeric)
    return numeric


def normalize_positive_integer(value: Any, row_label: str, field: str) -> int:
    numeric = normalize_number(value, row_label, field)
    if not isinstance(numeric, int) or numeric < 1:
        raise BuildError(
            "{}: '{}' must be a positive integer".format(row_label, field)
        )
    return numeric


def normalize_url(value: Any, row_label: str, field: str) -> Optional[str]:
    text = clean_text(value)
    if text is None:
        return None

    if any(character.isspace() for character in text):
        raise BuildError("{}: '{}' is not a valid URL: {}".format(row_label, field, text))

    try:
        parsed = urlsplit(text)
        hostname = parsed.hostname
        # Accessing port also validates a malformed or out-of-range port.
        parsed.port
    except ValueError:
        raise BuildError("{}: '{}' is not a valid URL: {}".format(row_label, field, text))

    if parsed.scheme.lower() not in ("http", "https"):
        raise BuildError(
            "{}: '{}' must use http or https: {}".format(row_label, field, text)
        )
    if not parsed.netloc or hostname is None:
        raise BuildError("{}: '{}' is not a valid URL: {}".format(row_label, field, text))
    return text


def compact_object(value: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: entry for key, entry in value.items() if entry is not None}


def column_number(reference: str) -> Tuple[int, int]:
    match = CELL_REFERENCE.fullmatch(reference)
    if match is None:
        raise BuildError("Invalid worksheet cell reference '{}'".format(reference))

    number = 0
    for character in match.group(1).upper():
        number = number * 26 + ord(character) - ord("A") + 1
    return number, int(match.group(2))


def rich_text(element: Optional[ET.Element]) -> str:
    if element is None:
        return ""

    parts: List[str] = []
    for child in element:
        if child.tag == MAIN + "t":
            parts.append(child.text or "")
        elif child.tag == MAIN + "r":
            text = child.find(MAIN + "t")
            if text is not None:
                parts.append(text.text or "")
    return "".join(parts)


def parse_number(text: str, sheet_name: str, reference: str) -> Any:
    if INTEGER.fullmatch(text):
        try:
            return int(text)
        except ValueError:
            pass

    try:
        value = float(text)
    except ValueError:
        raise BuildError(
            "Worksheet '{}' cell {} has invalid numeric value '{}'".format(
                sheet_name, reference, text
            )
        )

    if math.isfinite(value) and value.is_integer():
        return int(value)
    return value


def parse_cell_value(
    cell: ET.Element,
    shared_strings: Sequence[str],
    sheet_name: str,
    reference: str,
) -> Any:
    cell_type = cell.get("t")
    value_element = cell.find(MAIN + "v")
    value_text = None if value_element is None else value_element.text

    if cell_type == "inlineStr":
        return rich_text(cell.find(MAIN + "is"))
    if value_text is None:
        return None
    if cell_type == "s":
        try:
            index = int(value_text)
            return shared_strings[index]
        except (ValueError, IndexError):
            raise BuildError(
                "Worksheet '{}' cell {} has an invalid shared-string index".format(
                    sheet_name, reference
                )
            )
    if cell_type in ("str", "d", "e"):
        return value_text
    if cell_type == "b":
        if value_text == "1":
            return True
        if value_text == "0":
            return False
        raise BuildError(
            "Worksheet '{}' cell {} has invalid boolean value '{}'".format(
                sheet_name, reference, value_text
            )
        )
    if cell_type not in (None, "n"):
        raise BuildError(
            "Worksheet '{}' cell {} uses unsupported cell type '{}'".format(
                sheet_name, reference, cell_type
            )
        )
    return parse_number(value_text, sheet_name, reference)


def records_from_rows(
    rows: Mapping[int, Mapping[int, Any]], sheet_name: str
) -> Tuple[List[Tuple[int, Dict[str, Any]]], List[str]]:
    populated = [
        (row_number, column, value)
        for row_number, row in rows.items()
        for column, value in row.items()
        if not is_blank(value)
    ]
    if not populated:
        raise BuildError("Worksheet '{}' is empty".format(sheet_name))

    first_row = min(row_number for row_number, _, _ in populated)
    last_row = max(row_number for row_number, _, _ in populated)
    first_column = min(column for _, column, _ in populated)
    last_column = max(column for _, column, _ in populated)

    header_row = rows.get(first_row, {})
    headers = [
        clean_text(header_row.get(column))
        for column in range(first_column, last_column + 1)
    ]
    if any(header is None for header in headers):
        raise BuildError("Worksheet '{}' contains a blank header".format(sheet_name))

    text_headers = [header for header in headers if header is not None]
    seen = set()
    duplicates = []
    for header in text_headers:
        if header in seen and header not in duplicates:
            duplicates.append(header)
        seen.add(header)
    if duplicates:
        raise BuildError(
            "Worksheet '{}' contains duplicate headers: {}".format(
                sheet_name, ", ".join(duplicates)
            )
        )

    records: List[Tuple[int, Dict[str, Any]]] = []
    for row_number in range(first_row + 1, last_row + 1):
        row = rows.get(row_number, {})
        values = [row.get(column) for column in range(first_column, last_column + 1)]
        if all(is_blank(value) for value in values):
            continue
        records.append((row_number, dict(zip(text_headers, values))))

    return records, text_headers


def assert_headers(
    records: Sequence[Tuple[int, Mapping[str, Any]]],
    headers: Sequence[str],
    fields: Sequence[str],
    sheet_name: str,
) -> None:
    if not records:
        raise BuildError("Worksheet '{}' has no records".format(sheet_name))

    present = set(headers)
    missing = [field for field in fields if field not in present]
    if missing:
        raise BuildError(
            "Worksheet '{}' is missing required columns: {}".format(
                sheet_name, ", ".join(missing)
            )
        )


class XlsxWorkbook:
    """Minimal OOXML reader for worksheet values needed by this build."""

    def __init__(self, source_path: Path):
        self.source_path = source_path
        self.date_1904 = False
        self.sheets: Dict[str, Dict[int, Dict[int, Any]]] = {}

    @staticmethod
    def _xml(archive: zipfile.ZipFile, member: str) -> ET.Element:
        try:
            source = archive.read(member)
        except KeyError:
            raise BuildError("XLSX archive is missing '{}'".format(member))
        try:
            return ET.fromstring(source)
        except ET.ParseError as error:
            raise BuildError("XLSX part '{}' is not valid XML: {}".format(member, error))

    @staticmethod
    def _part_path(base_part: str, target: str) -> str:
        if target.startswith("/"):
            candidate = posixpath.normpath(target.lstrip("/"))
        else:
            candidate = posixpath.normpath(
                posixpath.join(posixpath.dirname(base_part), target)
            )
        if candidate == ".." or candidate.startswith("../"):
            raise BuildError("XLSX relationship target leaves the archive")
        return candidate

    @staticmethod
    def _shared_strings(archive: zipfile.ZipFile) -> List[str]:
        try:
            root = XlsxWorkbook._xml(archive, "xl/sharedStrings.xml")
        except BuildError as error:
            if "is missing" in str(error):
                return []
            raise
        return [rich_text(item) for item in root.findall(MAIN + "si")]

    @staticmethod
    def _sheet_rows(
        archive: zipfile.ZipFile,
        member: str,
        shared_strings: Sequence[str],
        sheet_name: str,
    ) -> Dict[int, Dict[int, Any]]:
        root = XlsxWorkbook._xml(archive, member)
        rows: Dict[int, Dict[int, Any]] = {}
        previous_row = 0

        sheet_data = root.find(MAIN + "sheetData")
        if sheet_data is None:
            return rows

        for row_element in sheet_data.findall(MAIN + "row"):
            row_text = row_element.get("r")
            if row_text is None:
                row_number = previous_row + 1
            else:
                try:
                    row_number = int(row_text)
                except ValueError:
                    raise BuildError(
                        "Worksheet '{}' has an invalid row number '{}'".format(
                            sheet_name, row_text
                        )
                    )
            if row_number < 1 or row_number in rows:
                raise BuildError(
                    "Worksheet '{}' has duplicate or invalid row {}".format(
                        sheet_name, row_number
                    )
                )

            values: Dict[int, Any] = {}
            next_column = 1
            for cell in row_element.findall(MAIN + "c"):
                reference = cell.get("r")
                if reference is None:
                    column = next_column
                    reference = "column {} row {}".format(column, row_number)
                else:
                    column, reference_row = column_number(reference)
                    if reference_row != row_number:
                        raise BuildError(
                            "Worksheet '{}' cell {} is stored in row {}".format(
                                sheet_name, reference, row_number
                            )
                        )
                if column in values:
                    raise BuildError(
                        "Worksheet '{}' contains duplicate cell {}".format(
                            sheet_name, reference
                        )
                    )
                values[column] = parse_cell_value(
                    cell, shared_strings, sheet_name, reference
                )
                next_column = column + 1

            rows[row_number] = values
            previous_row = row_number
        return rows

    def load(self) -> "XlsxWorkbook":
        if not self.source_path.is_file():
            raise BuildError("Source workbook does not exist: {}".format(self.source_path))

        try:
            with zipfile.ZipFile(str(self.source_path), "r") as archive:
                workbook_part = "xl/workbook.xml"
                workbook = self._xml(archive, workbook_part)
                relationships = self._xml(
                    archive, "xl/_rels/workbook.xml.rels"
                )
                shared_strings = self._shared_strings(archive)

                workbook_properties = workbook.find(MAIN + "workbookPr")
                if workbook_properties is not None:
                    self.date_1904 = workbook_properties.get("date1904", "0").lower() in (
                        "1",
                        "true",
                    )

                targets = {}
                for relationship in relationships.findall(PACKAGE_REL + "Relationship"):
                    if relationship.get("TargetMode") == "External":
                        continue
                    relationship_id = relationship.get("Id")
                    target = relationship.get("Target")
                    if relationship_id and target:
                        targets[relationship_id] = self._part_path(
                            workbook_part, target
                        )

                sheets_element = workbook.find(MAIN + "sheets")
                if sheets_element is None:
                    raise BuildError("Workbook contains no worksheets")

                requested = {"Events", "Talks"}
                for sheet in sheets_element.findall(MAIN + "sheet"):
                    name = sheet.get("name")
                    if name not in requested:
                        continue
                    relationship_id = sheet.get(DOCUMENT_REL + "id")
                    target = targets.get(relationship_id)
                    if target is None:
                        raise BuildError(
                            "Worksheet '{}' has no valid workbook relationship".format(name)
                        )
                    if name in self.sheets:
                        raise BuildError("Workbook contains duplicate '{}' sheets".format(name))
                    self.sheets[name] = self._sheet_rows(
                        archive, target, shared_strings, name
                    )
        except zipfile.BadZipFile:
            raise BuildError("Source is not a valid XLSX/ZIP file: {}".format(self.source_path))
        except OSError as error:
            raise BuildError("Could not read source workbook: {}".format(error))

        for required_sheet in ("Events", "Talks"):
            if required_sheet not in self.sheets:
                raise BuildError("Workbook is missing worksheet '{}'".format(required_sheet))
        return self


def build_data(workbook: XlsxWorkbook) -> Dict[str, Any]:
    event_records, event_headers = records_from_rows(
        workbook.sheets["Events"], "Events"
    )
    talk_records, talk_headers = records_from_rows(workbook.sheets["Talks"], "Talks")
    assert_headers(
        event_records, event_headers, REQUIRED_EVENT_FIELDS, "Events"
    )
    assert_headers(talk_records, talk_headers, REQUIRED_TALK_FIELDS, "Talks")

    events_by_id: Dict[str, Dict[str, Any]] = {}
    for worksheet_row, row in event_records:
        row_label = "Events row {}".format(worksheet_row)
        event_id = required_text(row, "event_id", row_label)
        if event_id in events_by_id:
            raise BuildError("{}: duplicate event_id '{}'".format(row_label, event_id))

        start_date = normalize_date(
            row.get("start_date"),
            row_label,
            "start_date",
            workbook.date_1904,
        )
        end_date = normalize_date(
            row.get("end_date"), row_label, "end_date", workbook.date_1904
        )
        if end_date < start_date:
            raise BuildError("{}: end_date precedes start_date".format(row_label))

        latitude = normalize_number(row.get("latitude"), row_label, "latitude")
        longitude = normalize_number(row.get("longitude"), row_label, "longitude")
        if latitude < -90 or latitude > 90:
            raise BuildError("{}: latitude is outside -90..90".format(row_label))
        if longitude < -180 or longitude > 180:
            raise BuildError("{}: longitude is outside -180..180".format(row_label))

        # Precision is required editorial metadata in the source workbook. It is
        # validated here but deliberately not published in the website JSON.
        required_text(row, "location_precision", row_label)

        overrides = EVENT_EDITORIAL_OVERRIDES.get(event_id, {})
        host_organization = overrides.get(
            "host_organization",
            required_text(row, "host_organization", row_label),
        )
        venue = overrides.get("venue", required_text(row, "venue", row_label))

        event = compact_object(
            {
                "id": event_id,
                "name": overrides.get(
                    "event_name", required_text(row, "event_name", row_label)
                ),
                "startDate": start_date,
                "endDate": end_date,
                "year": int(start_date[:4]),
                "type": required_text(row, "event_type", row_label),
                "hostOrganization": normalize_host_organizations(
                    host_organization, row_label
                ),
                "venue": venue,
                "location": compact_object(
                    {
                        "address": clean_text(row.get("precise_location_or_address")),
                        "city": required_text(row, "city", row_label),
                        "region": clean_text(row.get("region")),
                        "country": required_text(row, "country", row_label),
                        "latitude": latitude,
                        "longitude": longitude,
                    }
                ),
                "url": normalize_url(row.get("event_url"), row_label, "event_url"),
                "talks": [],
            }
        )
        events_by_id[event_id] = event

    talk_order_keys = set()
    for worksheet_row, row in talk_records:
        row_label = "Talks row {}".format(worksheet_row)
        event_id = required_text(row, "event_id", row_label)
        event = events_by_id.get(event_id)
        if event is None:
            raise BuildError(
                "{}: orphan talk references unknown event_id '{}'".format(
                    row_label, event_id
                )
            )

        order = normalize_positive_integer(row.get("talk_order"), row_label, "talk_order")
        order_key = (event_id, order)
        if order_key in talk_order_keys:
            raise BuildError(
                "{}: duplicate talk_order {} for '{}'".format(
                    row_label, order, event_id
                )
            )
        talk_order_keys.add(order_key)

        if order_key in POSTER_CONTRIBUTIONS:
            contribution_type = "Poster"
        elif event["type"] == "Seminar":
            contribution_type = "Seminar talk"
        else:
            contribution_type = "Talk"
        publication = PUBLICATION_LINKS.get(order_key)
        recording_url = normalize_url(
            TALK_RECORDING_OVERRIDES.get(order_key, row.get("recording_url")),
            row_label,
            "recording_url",
        )
        publication_url = (
            normalize_url(publication[1], row_label, "publication_url")
            if publication
            else None
        )

        presentation_date = normalize_date(
            row.get("presentation_date"),
            row_label,
            "presentation_date",
            workbook.date_1904,
            optional=True,
        )
        if presentation_date is not None and not (
            event["startDate"] <= presentation_date <= event["endDate"]
        ):
            raise BuildError(
                "{}: presentation_date falls outside the event dates".format(row_label)
            )

        event["talks"].append(
            compact_object(
                {
                    "order": order,
                    "title": required_text(row, "talk_title", row_label),
                    "contributionType": contribution_type,
                    "presentationDate": presentation_date,
                    "recordingUrl": recording_url,
                    "slidesUrl": normalize_url(
                        row.get("slides_url"), row_label, "slides_url"
                    ),
                    "publicationLabel": publication[0] if publication else None,
                    "publicationUrl": publication_url,
                }
            )
        )

    editorial_talk_keys = (
        POSTER_CONTRIBUTIONS
        | set(TALK_RECORDING_OVERRIDES)
        | set(PUBLICATION_LINKS)
    )
    unknown_editorial_talk_keys = editorial_talk_keys - talk_order_keys
    if unknown_editorial_talk_keys:
        formatted_keys = ", ".join(
            "{} (talk {})".format(event_id, order)
            for event_id, order in sorted(unknown_editorial_talk_keys)
        )
        raise BuildError(
            "Editorial talk metadata references unknown contributions: {}".format(
                formatted_keys
            )
        )

    events = list(events_by_id.values())
    for event in events:
        if not event["talks"]:
            raise BuildError("Event '{}' has no linked talks".format(event["id"]))
        event["talks"].sort(key=lambda talk: talk["order"])

    # Stable two-pass sort gives descending dates with ascending IDs for ties.
    events.sort(key=lambda event: event["id"])
    events.sort(key=lambda event: event["startDate"], reverse=True)

    event_count = len(events)
    talk_count = sum(len(event["talks"]) for event in events)

    years = sorted({event["year"] for event in events}, reverse=True)
    return {
        "metadata": {
            "schemaVersion": "1.2.0",
            "eventCount": event_count,
            "talkCount": talk_count,
            "years": years,
        },
        "events": events,
    }


def write_json(output_path: Path, data: Mapping[str, Any]) -> None:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as error:
        raise BuildError("Could not write output JSON: {}".format(error))


def run(arguments: Sequence[str]) -> int:
    if len(arguments) == 1 and arguments[0] in ("-h", "--help"):
        print(usage())
        return 0
    if len(arguments) not in (1, 2):
        print(usage(), file=sys.stderr)
        return 1

    source_path = Path(arguments[0]).expanduser().resolve()
    output_path = (
        Path(arguments[1]).expanduser().resolve()
        if len(arguments) == 2
        else DEFAULT_OUTPUT
    )

    workbook = XlsxWorkbook(source_path).load()
    data = build_data(workbook)
    write_json(output_path, data)

    try:
        displayed_path = os.path.relpath(str(output_path), os.getcwd())
    except ValueError:
        displayed_path = str(output_path)
    print("Wrote {}".format(displayed_path))
    print(
        "Validated {} events and {} talks".format(
            data["metadata"]["eventCount"], data["metadata"]["talkCount"]
        )
    )
    print("Years: {}".format(", ".join(str(year) for year in data["metadata"]["years"])))
    return 0


def main() -> int:
    try:
        return run(sys.argv[1:])
    except BuildError as error:
        print("Academic-travels data build failed: {}".format(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
