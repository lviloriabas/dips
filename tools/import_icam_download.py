"""Merge a JSON download from the in-page ICAM scraper into local data."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "icam_dips.json"
SOURCE = ROOT / "data" / "dips_dataset.json"

if len(sys.argv) != 2:
    raise SystemExit("Usage: python tools/import_icam_download.py <downloaded JSON file>")

download = Path(sys.argv[1]).resolve()
incoming_data = json.loads(download.read_text(encoding="utf-8"))
incoming = incoming_data.get("records", [])
if not isinstance(incoming, list):
    raise SystemExit("The download does not contain a records list.")

source = json.loads(SOURCE.read_text(encoding="utf-8"))
barcodes = [row["barcode"] for row in source["records"]]
allowed = set(barcodes)
data = json.loads(OUTPUT.read_text(encoding="utf-8"))
saved = {row["barcode"]: row for row in data["records"]}

for record in incoming:
    barcode = record.get("barcode")
    if barcode not in allowed:
        raise SystemExit(f"Unknown barcode in download: {barcode}")
    if set(record.get("sections", {})) != {
        "TaskExecution", "FaultInformation", "TaskInformation", "Scheduling", "History", "Warranty"
    }:
        raise SystemExit(f"Incomplete six-tab record in download: {barcode}")
    saved[barcode] = record

data["records"] = [saved[barcode] for barcode in barcodes if barcode in saved]
data["captured_count"] = len(data["records"])
data["captured_at_utc"] = datetime.now(timezone.utc).isoformat()
temporary = OUTPUT.with_suffix(".json.tmp")
temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
temporary.replace(OUTPUT)
print(f"Imported {len(incoming)} DIPs; {len(data['records'])}/{len(barcodes)} now captured.")
