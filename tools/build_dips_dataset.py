"""Combine the audit workbook with read-only ICAM captures into one JSON file."""

import json
import re
from datetime import date, datetime, time
from pathlib import Path

import openpyxl


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "02 - HISTORY - DIPs AUDIT (From 09Jul 15_45).xlsx"
ICAM = ROOT / "data" / "icam_dips.json"
OUTPUT = ROOT / "data" / "dips_dataset.json"


def json_value(value):
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return value


MONTHS = {
    "JAN": 1, "JANUARY": 1, "ENE": 1, "ENERO": 1,
    "FEB": 2, "FEBRUARY": 2, "MAR": 3, "MARCH": 3, "MARZO": 3,
    "APR": 4, "APRIL": 4, "ABR": 4, "ABRIL": 4,
    "MAY": 5, "MAYO": 5, "JUN": 6, "JUNE": 6, "JUNIO": 6,
    "JUL": 7, "JULY": 7, "JULIO": 7, "AUG": 8, "AUGUST": 8, "AGO": 8, "AGOSTO": 8,
    "SEP": 9, "SEPT": 9, "SEPTEMBER": 9, "SEPTIEMBRE": 9,
    "OCT": 10, "OCTOBER": 10, "OCTUBRE": 10,
    "NOV": 11, "NOVEMBER": 11, "NOVIEMBRE": 11,
    "DEC": 12, "DECEMBER": 12, "DIC": 12, "DICIEMBRE": 12,
}
DATE_PATTERN = re.compile(r"\b(\d{1,2})[\s/-]+([A-Za-z]{3,12})[\s/-]+(\d{2,4})\b", re.I)
DATE_CATEGORIES = {
    "fumigation": re.compile(r"fumig|fumigaci[oó]n", re.I),
    "hydro_test": re.compile(r"hydro|hydrostatic|\bHT\b", re.I),
    "shelf_life": re.compile(r"shelf[ -]?life|shelf life expiry", re.I),
    "bottle_expiry": re.compile(r"bottle|botella|cylinder|extinguisher|halon|oxygen", re.I),
    "weight_due": re.compile(r"weight due|next weight", re.I),
    "kit_expiry": re.compile(r"\bFAK\b|first aid kit", re.I),
}
DATE_SIGNAL = re.compile(r"\bdue\b|expir|shelf[ -]?life|hydro|hydrostatic|\bHT\b|next weight|vencimiento|valid until|end of life", re.I)


def parse_date(raw):
    match = DATE_PATTERN.search(raw or "")
    if not match:
        return None
    day, month, year = match.groups()
    month_number = MONTHS.get(month.upper())
    if not month_number:
        return None
    year_number = int(year) + (2000 if len(year) == 2 else 0)
    try:
        return date(year_number, month_number, int(day)).isoformat()
    except ValueError:
        return None


def date_mentions(text, source, fallback_category=None):
    mentions = []
    for match in DATE_PATTERN.finditer(text or ""):
        iso = parse_date(match.group())
        if not iso:
            continue
        context = (text[max(0, match.start() - 110): min(len(text), match.end() + 110)]
                   .replace("\n", " ").strip())
        classification = text[max(0, match.start() - 55): min(len(text), match.end() + 15)]
        categories = [name for name, pattern in DATE_CATEGORIES.items() if pattern.search(classification)]
        if not DATE_SIGNAL.search(classification):
            categories = [name for name in categories if name not in {"bottle_expiry", "kit_expiry"}]
        if not categories and fallback_category:
            categories = [fallback_category]
        due_date = bool(DATE_SIGNAL.search(classification)) or source == "DIP title" and bool(categories)
        if re.search(r"\bREV(?:ISION)?\s*\d+\s*[,/-]?\s*$", text[max(0, match.start() - 22):match.start()], re.I):
            due_date = False
        mentions.append({"date": iso, "raw": match.group(), "source": source,
                         "categories": categories, "is_due_date": due_date, "context": context})
    return mentions


def date_audit(title, execution, inventory_details, intervals, has_icam):
    title_categories = [name for name, pattern in DATE_CATEGORIES.items() if pattern.search(title or "")]
    if not DATE_SIGNAL.search(title or ""):
        title_categories = [name for name in title_categories if name not in {"bottle_expiry", "kit_expiry"}]
    fallback = title_categories[0] if title_categories else None
    found = []
    found += date_mentions(title, "DIP title", fallback)
    found += date_mentions(execution.get("description", ""), "DIP description", fallback)
    found += date_mentions(execution.get("steps", ""), "DIP steps", fallback)
    for inventory in inventory_details:
        serial = inventory.get("serial_no")
        for mention in date_mentions(inventory.get("text", ""),
                                     f"Inventory {serial} details"):
            if not mention["is_due_date"]:
                continue
            mention["serial_no"] = serial
            mention["part_role"] = inventory.get("role")
            mention["inventory_url"] = inventory.get("url")
            found.append(mention)
        for field, category in [("shelf_life_expiry", "shelf_life"),
                                ("release_remarks", "hydro_test")]:
            for mention in date_mentions(inventory.get(field, ""),
                                         f"Inventory {serial} {field}", category):
                if field == "shelf_life_expiry":
                    mention["categories"] = ["shelf_life"]
                    mention["is_due_date"] = True
                elif not DATE_CATEGORIES["hydro_test"].search(mention["context"]):
                    continue
                else:
                    mention["is_due_date"] = True
                mention["serial_no"] = serial
                mention["part_role"] = inventory.get("role")
                mention["inventory_url"] = inventory.get("url")
                found.append(mention)
    seen = set()
    found = [item for item in found if not (item["date"], item["source"], item["context"]) in seen
             and not seen.add((item["date"], item["source"], item["context"]))]
    deadlines = [parse_date(str(interval.get("deadline") or interval.get("extended_deadline") or ""))
                 for interval in intervals]
    deadlines = [value for value in deadlines if value]
    relevant = [item for item in found if item["categories"] and item["is_due_date"]]
    matches = [item for item in relevant if item["date"] in deadlines]
    if not has_icam:
        status = "needs_icam"
    elif not title_categories and not relevant:
        status = "not_applicable"
    elif matches:
        status = "date_matches_interval"
    elif relevant and deadlines:
        status = "review_date_vs_interval"
    else:
        status = "needs_date_evidence"
    return {"status": status, "types": title_categories,
            "interval_deadlines": deadlines, "date_mentions": found,
            "matching_dates": sorted({item["date"] for item in matches}),
            "inventory_lookup_count": len(inventory_details),
            "inventory_lookup_errors": [item for item in inventory_details if item.get("error")]}


def table_data(rows, serial_column, part_column, kind):
    items = []
    for row in rows:
        if len(row) <= max(serial_column, part_column):
            continue
        serial = row[serial_column].strip()
        if not serial or serial.lower() in {"serial no", "serial no / batch no", "xxx", "n/a", "-"}:
            continue
        items.append({"kind": kind, "part_no": row[part_column].strip(), "serial_no": serial})
    return items


def part_serials(rows):
    header_index = next((i for i, row in enumerate(rows)
                         if sum("Serial No / Batch No" in cell for cell in row) >= 2), None)
    if header_index is None:
        return []
    header = rows[header_index]
    serial_columns = [i for i, cell in enumerate(header) if "Serial No / Batch No" in cell]
    result = []
    for row in rows[header_index + 1:]:
        for position, serial_column in enumerate(serial_columns[:2]):
            result += table_data([row], serial_column, serial_column - 1,
                                 "removed_part" if position == 0 else "installed_part")
    return result


def normalize(excel, icam):
    if not icam:
        excel_intervals = ([{"value": excel.get("DIP Interval"), "unit": excel.get("Interval Type"), "source": "Excel"}]
                           if excel.get("DIP Interval") not in (None, "") else [])
        return {
            "title": excel.get("Fault Name"),
            "description": None,
            "aircraft": excel.get("Aircraft"),
            "inventory": None,
            "intervals": excel_intervals,
            "references": None,
            "has_references": None,
            "attachments": None,
            "has_attachments": None,
            "serial_numbers": None,
            "steps_text": None,
            "has_steps": None,
            "date_audit": date_audit(excel.get("Fault Name"), {}, [], excel_intervals, False),
        }

    sections = icam["sections"]
    execution = sections["TaskExecution"]
    fault = sections["FaultInformation"]
    task = sections["TaskInformation"]
    schedule = sections["Scheduling"]
    intervals = []
    for row in schedule.get("intervals", []):
        if len(row) >= 16 and row[6].strip() not in ("", "Interval"):
            intervals.append({
                "parameter": row[2], "unit": row[3], "scheduled_from": row[4],
                "start": row[5], "value": row[6], "deadline": row[7],
                "extension": row[8], "extended_deadline": row[9],
                "usage_remaining": row[10], "estimated_date": row[11],
                "source": "ICAM",
            })
    if not intervals and excel.get("DIP Interval") not in (None, ""):
        intervals = [{"value": excel.get("DIP Interval"), "unit": excel.get("Interval Type"), "source": "Excel"}]

    mentioned = re.findall(
        r"\b(?:AMM\s+TASK|SRM|CMM|MEL|ECRA|EC/RA|JIC|TASK)\s*[A-Z0-9./-]+",
        (execution.get("description") or "") + "\n" + execution.get("steps", ""),
        flags=re.I,
    )
    references = list(dict.fromkeys(
        [x for x in [fault.get("selected_reference"), *task.get("technical_references", []), *mentioned] if x]
    ))
    attachment = task.get("attachments", {})
    attachment_count = attachment.get("count", 0)
    attachment_lines = [line.strip() for line in attachment.get("text", "").splitlines()[1:] if line.strip()]
    serials = []
    part_rows = execution.get("part_requirements", [])
    serials += part_serials(part_rows)
    serials += table_data(execution.get("tool_requirements", []), 3, 2, "tool")
    for match in re.finditer(r"\b(?:S\s*/\s*N|SN|SERIAL(?: NUMBER| NO)?)\s*[:#]?\s*([A-Z0-9-]{3,})",
                             execution.get("text", ""), re.I):
        serials.append({"kind": "mentioned_in_text", "part_no": None, "serial_no": match.group(1)})
    seen = set()
    serials = [s for s in serials if not (s["kind"], s["part_no"], s["serial_no"]) in seen
               and not seen.add((s["kind"], s["part_no"], s["serial_no"]))]

    title = re.sub(r"^Fault Details\s*-\s*", "", icam.get("page_title") or "")
    title = re.sub(r"\s*\[[A-Z0-9]+\]$", "", title)
    title = title or excel.get("Fault Name")
    inventory_details = icam.get("inventory_details", [])
    return {
        "title": title,
        "description": execution.get("description") or None,
        "aircraft": icam.get("aircraft") or excel.get("Aircraft"),
        "inventory": icam.get("inventory"),
        "intervals": intervals,
        "references": references,
        "has_references": bool(references),
        "attachments": {"count": attachment_count, "details": attachment_lines},
        "has_attachments": bool(attachment_count),
        "serial_numbers": serials,
        "steps_text": execution.get("steps", ""),
        "has_steps": bool(re.search(r"Step \d+", execution.get("steps", ""))),
        "inventory_details": inventory_details,
        "date_audit": date_audit(title, execution, inventory_details, intervals, True),
    }


sheet = openpyxl.load_workbook(SOURCE, read_only=True, data_only=True)["Datos"]
rows = sheet.iter_rows(values_only=True)
headers = list(next(rows))
names = []
for i, heading in enumerate(headers, 1):
    name = str(heading).strip() if heading else f"column_{i}"
    if name in names:
        name += f"_{i}"
    names.append(name)

icam_data = json.loads(ICAM.read_text(encoding="utf-8"))
icam_by_barcode = {r["barcode"]: r for r in icam_data["records"]}
result = []
for row in rows:
    barcode = str(row[1] or "").strip()
    if not re.fullmatch(r"[A-Z0-9]{10,15}", barcode):
        continue
    excel = {name: json_value(value) for name, value in zip(names, row) if value is not None}
    icam = icam_by_barcode.get(barcode)
    result.append({
        "barcode": barcode,
        "icam_capture_status": "six_tabs" if icam else "excel_only",
        "normalized": normalize(excel, icam),
        "excel_row": excel,
        "icam_detail": icam,
    })

output = {
    "source_excel": SOURCE.name,
    "source_icam": "https://copa.ifs.cloud/maintenix/",
    "captured_at_utc": icam_data.get("captured_at_utc"),
    "total_dips": len(result),
    "icam_complete_count": sum(r["icam_capture_status"] == "six_tabs" for r in result),
    "records": result,
}
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"{OUTPUT}: {output['total_dips']} DIPs, {output['icam_complete_count']} ICAM captures")
