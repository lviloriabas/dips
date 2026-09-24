"""Build a self-contained read-only scraper for the signed-in ICAM tab."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
dataset = json.loads((ROOT / "data" / "dips_dataset.json").read_text(encoding="utf-8"))
existing = json.loads((ROOT / "data" / "icam_dips.json").read_text(encoding="utf-8"))
barcodes = [row["barcode"] for row in dataset["records"]]
completed = [row["barcode"] for row in existing["records"]]
template = (ROOT / "tools" / "icam_inpage_scraper.template.js").read_text(encoding="utf-8")
template = template.replace("__BARCODES__", json.dumps(barcodes, ensure_ascii=False))
template = template.replace("__COMPLETED__", json.dumps(completed, ensure_ascii=False))
output = ROOT / "data" / "icam_inpage_scraper.js"
output.write_text(template, encoding="utf-8")
print(f"{output}: {len(barcodes) - len(completed)} barcodes remaining")
