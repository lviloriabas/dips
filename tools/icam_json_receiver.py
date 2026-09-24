"""Local-only receiver for read-only ICAM browser extraction."""

import json
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import openpyxl


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "02 - HISTORY - DIPs AUDIT (From 09Jul 15_45).xlsx"
OUTPUT = ROOT / "data" / "icam_dips.json"

sheet = openpyxl.load_workbook(SOURCE, read_only=True, data_only=True)["Datos"]
barcodes = []
for row in sheet.iter_rows(min_row=2, values_only=True):
    value = str(row[1] or "").strip()
    if re.fullmatch(r"[A-Z0-9]{10,15}", value):
        barcodes.append(value)
barcodes = list(dict.fromkeys(barcodes))


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        if self.path != "/api/batch" or self.headers.get("Origin") != "https://copa.ifs.cloud":
            self.send_error(403)
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "https://copa.ifs.cloud")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return
        existing = json.loads(OUTPUT.read_text(encoding="utf-8"))["records"] if OUTPUT.exists() else []
        needs_steps = [
            r["barcode"]
            for r in existing
            if re.search(r"Step \d+", r.get("sections", {}).get("TaskExecution", {}).get("steps", ""))
            and "Description:" not in r["sections"]["TaskExecution"]["steps"]
        ]
        page = (
            "<!doctype html><meta charset='utf-8'><title>ICAM local receiver</title>"
            "<script type='application/json' id='barcodes'>"
            + json.dumps(barcodes)
            + "</script><script type='application/json' id='completed'>"
            + json.dumps([r["barcode"] for r in existing])
            + "</script><script type='application/json' id='needs_steps'>"
            + json.dumps(needs_steps)
            + "</script><form method='post' action='/batch'>"
            "<textarea name='records' aria-label='records'></textarea>"
            "<button type='submit'>Save locally</button></form>"
        )
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path not in ("/batch", "/api/batch"):
            self.send_error(404)
            return
        from urllib.parse import parse_qs

        size = int(self.headers.get("Content-Length", "0"))
        if size > 20_000_000:
            self.send_error(413)
            return
        if self.path == "/api/batch":
            if self.headers.get("Origin") != "https://copa.ifs.cloud":
                self.send_error(403)
                return
            incoming = json.loads(self.rfile.read(size).decode("utf-8"))
        else:
            fields = parse_qs(self.rfile.read(size).decode("utf-8"))
            incoming = json.loads(fields["records"][0])
        if not isinstance(incoming, list):
            self.send_error(400)
            return
        if OUTPUT.exists():
            data = json.loads(OUTPUT.read_text(encoding="utf-8"))
        else:
            data = {"source": str(SOURCE.name), "total_barcodes": len(barcodes), "records": []}
        by_barcode = {r["barcode"]: r for r in data["records"]}
        def merge(old, new):
            if isinstance(old, dict) and isinstance(new, dict):
                result = old.copy()
                for key, value in new.items():
                    result[key] = merge(result.get(key), value)
                return result
            return new

        for record in incoming:
            if record.get("barcode") not in barcodes:
                self.send_error(400, "Unknown barcode")
                return
            by_barcode[record["barcode"]] = merge(by_barcode.get(record["barcode"], {}), record)
        data["records"] = [by_barcode[b] for b in barcodes if b in by_barcode]
        data["captured_at_utc"] = datetime.now(timezone.utc).isoformat()
        data["captured_count"] = len(data["records"])
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        temp = OUTPUT.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(OUTPUT)
        body = f"Saved {len(incoming)} records; total {len(data['records'])}.".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        if self.path == "/api/batch":
            self.send_header("Access-Control-Allow-Origin", "https://copa.ifs.cloud")
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
