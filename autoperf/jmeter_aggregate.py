from __future__ import annotations

import csv
import html
import math
import statistics
from pathlib import Path

from .utils import AutoPerfError


AGGREGATE_COLUMNS = [
    "label",
    "samples",
    "average_ms",
    "p90_ms",
    "min_ms",
    "max_ms",
    "error_pct",
    "throughput_per_sec",
]


def _bool_success(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "y", "success"}


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = max(0, math.ceil((percentile / 100) * len(sorted_values)) - 1)
    return sorted_values[min(index, len(sorted_values) - 1)]


def _read_jtl_csv(jtl_file: Path) -> list[dict]:
    if not jtl_file.is_file():
        raise AutoPerfError(f"JTL not found: {jtl_file}")
    with jtl_file.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        if not reader.fieldnames:
            raise AutoPerfError(f"JTL is empty: {jtl_file}")
        required = {"timeStamp", "elapsed", "label"}
        missing = sorted(required.difference(reader.fieldnames))
        if missing:
            raise AutoPerfError(f"JTL missing columns: {', '.join(missing)}")
        samples = []
        for row in reader:
            try:
                timestamp = float(row["timeStamp"])
                elapsed = float(row["elapsed"])
            except (TypeError, ValueError) as exc:
                raise AutoPerfError(f"invalid JTL timing row in {jtl_file}") from exc
            samples.append(
                {
                    "label": row.get("label") or "UNKNOWN",
                    "timestamp": timestamp,
                    "elapsed": elapsed,
                    "success": _bool_success(row.get("success", "true")),
                }
            )
    if not samples:
        raise AutoPerfError(f"JTL has no samples: {jtl_file}")
    return samples


def _summarize(label: str, samples: list[dict]) -> dict:
    elapsed_values = [sample["elapsed"] for sample in samples]
    start = min(sample["timestamp"] for sample in samples)
    end = max(sample["timestamp"] + sample["elapsed"] for sample in samples)
    duration_seconds = max((end - start) / 1000, 0.001)
    failures = sum(1 for sample in samples if not sample["success"])
    count = len(samples)
    return {
        "label": label,
        "samples": count,
        "average_ms": round(statistics.fmean(elapsed_values), 2),
        "p90_ms": round(_percentile(elapsed_values, 90), 2),
        "min_ms": round(min(elapsed_values), 2),
        "max_ms": round(max(elapsed_values), 2),
        "error_pct": round((failures / count) * 100, 2),
        "throughput_per_sec": round(count / duration_seconds, 2),
    }


def aggregate_jtl(jtl_file: Path) -> list[dict]:
    samples = _read_jtl_csv(jtl_file)
    by_label: dict[str, list[dict]] = {}
    for sample in samples:
        by_label.setdefault(sample["label"], []).append(sample)
    rows = [_summarize(label, by_label[label]) for label in sorted(by_label)]
    rows.append(_summarize("TOTAL", samples))
    return rows


def write_jmeter_aggregate_csv(rows: list[dict], output_file: Path) -> Path:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=AGGREGATE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return output_file


def generate_jmeter_aggregate_report(jtl_file: Path, html_file: Path, csv_file: Path | None = None) -> Path:
    rows = aggregate_jtl(jtl_file)
    if csv_file is not None:
        write_jmeter_aggregate_csv(rows, csv_file)
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{html.escape(str(row['label']))}</td>"
            f"<td>{row['samples']}</td>"
            f"<td>{row['average_ms']:.2f}</td>"
            f"<td>{row['p90_ms']:.2f}</td>"
            f"<td>{row['min_ms']:.2f}</td>"
            f"<td>{row['max_ms']:.2f}</td>"
            f"<td>{row['error_pct']:.2f}%</td>"
            f"<td>{row['throughput_per_sec']:.2f}</td>"
            "</tr>"
        )
    html_file.parent.mkdir(parents=True, exist_ok=True)
    html_file.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>JMeter Aggregate Report</title>
<style>
body {{ margin: 0; font-family: Arial, sans-serif; background: #f7f8fa; color: #1f2933; }}
main {{ max-width: 1100px; margin: 24px auto; padding: 0 16px; }}
h1 {{ font-size: 24px; margin: 0 0 16px; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d8dee6; }}
th, td {{ padding: 10px 12px; border-bottom: 1px solid #edf0f3; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ font-size: 13px; color: #52606d; background: #f2f5f8; }}
td {{ font-size: 14px; }}
tr:last-child td {{ font-weight: bold; border-bottom: 0; }}
</style>
</head>
<body>
<main>
<h1>JMeter Aggregate Report</h1>
<table>
<thead>
<tr>
  <th>Transactions</th>
  <th>Samples</th>
  <th>Average (ms)</th>
  <th>90% Line (ms)</th>
  <th>Min (ms)</th>
  <th>Max (ms)</th>
  <th>Error %</th>
  <th>Throughput (/sec)</th>
</tr>
</thead>
<tbody>
{''.join(body)}
</tbody>
</table>
</main>
</body>
</html>
""",
        encoding="utf-8",
    )
    return html_file
