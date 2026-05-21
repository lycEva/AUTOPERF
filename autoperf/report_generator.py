from __future__ import annotations

import csv
import html
import json
import statistics
from datetime import datetime
from pathlib import Path

from .utils import AutoPerfError


METRICS = [
    ("cpu_usage", "CPU Usage"),
    ("mem_usage", "Memory Usage"),
    ("npu_usage", "NPU Usage"),
    ("npu_mem", "NPU Memory"),
]

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _read_monitor_csv(csv_file: Path) -> list[dict]:
    if not csv_file.is_file():
        raise AutoPerfError(f"monitor.csv not found: {csv_file}")
    with csv_file.open("r", encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))
    if not rows:
        raise AutoPerfError(f"monitor.csv is empty: {csv_file}")
    parsed: list[dict] = []
    for row in rows:
        item = {"timestamp": row.get("timestamp", "")}
        for key, _ in METRICS:
            try:
                item[key] = float(row.get(key, 0) or 0)
            except ValueError:
                item[key] = 0.0
        parsed.append(item)
    return parsed


def _stats(rows: list[dict], key: str) -> dict[str, float]:
    values = [float(row[key]) for row in rows]
    return {
        "min": min(values),
        "max": max(values),
        "avg": statistics.fmean(values) if values else 0.0,
    }


def _peak(labels: list[float], values: list[float]) -> dict[str, object]:
    max_value = max(values)
    index = values.index(max_value)
    return {"index": index, "time": labels[index], "value": max_value}


def _format_elapsed(minutes: float) -> str:
    total_seconds = max(int(round(minutes * 60)), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes_part, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes_part:02d}:{seconds:02d}"


def _time_labels(rows: list[dict]) -> list[float]:
    parsed_times = []
    for row in rows:
        try:
            parsed_times.append(datetime.strptime(row["timestamp"], TIME_FORMAT))
        except ValueError:
            return [float(idx) for idx, _ in enumerate(rows)]

    if not parsed_times:
        return []

    start = parsed_times[0]
    return [round((current - start).total_seconds() / 60, 2) for current in parsed_times]


def generate_html_report(csv_file: Path, output_file: Path) -> Path:
    rows = _read_monitor_csv(csv_file)
    labels = _time_labels(rows)
    stats = {key: _stats(rows, key) for key, _ in METRICS}
    series = {key: [row[key] for row in rows] for key, _ in METRICS}
    peaks = {key: _peak(labels, values) for key, values in series.items()}
    metric_titles = {key: title for key, title in METRICS}
    payload = json.dumps({"labels": labels, "series": series, "peaks": peaks}, ensure_ascii=False)

    charts = []
    for key, title in METRICS:
        stat = stats[key]
        charts.append(
            f"""
<section class="panel">
  <h2>{html.escape(title)}</h2>
  <div class="stats">
    <span>min: {stat['min']:.2f}</span>
    <span>max: {stat['max']:.2f}</span>
    <span>avg: {stat['avg']:.2f}</span>
  </div>
  <canvas id="{key}" width="960" height="300"></canvas>
</section>"""
        )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AutoPerf Monitor Report</title>
<style>
body {{ margin: 0; font-family: Arial, sans-serif; background: #f7f8fa; color: #1f2933; }}
main {{ max-width: 1100px; margin: 24px auto; padding: 0 16px; }}
h1 {{ font-size: 24px; margin: 0 0 20px; }}
.panel {{ background: #fff; border: 1px solid #d8dee6; border-radius: 6px; padding: 16px; margin-bottom: 16px; }}
h2 {{ font-size: 18px; margin: 0 0 8px; }}
.stats {{ display: flex; gap: 18px; font-size: 13px; color: #52606d; margin-bottom: 10px; }}
canvas {{ width: 100%; height: 300px; border: 1px solid #cfd8e3; background: #eef6ff; }}
</style>
</head>
<body>
<main>
<h1>AutoPerf Monitor Report</h1>
{''.join(charts)}
</main>
<script>
const data = {payload};
const metrics = {json.dumps([key for key, _ in METRICS])};
const metricTitles = {json.dumps(metric_titles, ensure_ascii=False)};
function formatElapsed(minutes) {{
  const totalSeconds = Math.max(Math.round(minutes * 60), 0);
  const hours = String(Math.floor(totalSeconds / 3600)).padStart(2, '0');
  const mins = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0');
  const secs = String(totalSeconds % 60).padStart(2, '0');
  return `${{hours}}:${{mins}}:${{secs}}`;
}}
function drawLegend(ctx, title) {{
  ctx.fillStyle = '#ff40ff';
  ctx.fillRect(4, 6, 8, 8);
  ctx.fillStyle = '#1f2933';
  ctx.font = '11px Arial';
  ctx.fillText(`127.0.0.1 ${{title}}`, 16, 13);
}}
function drawChart(canvas, values, title) {{
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  const plot = {{left: 54, top: 24, right: 18, bottom: 34}};
  const plotW = w - plot.left - plot.right;
  const plotH = h - plot.top - plot.bottom;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#eef6ff';
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = '#d6dde8';
  ctx.lineWidth = 1;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = Math.max(max - min, 1);
  const xMax = Math.max(...data.labels, 0);
  const xSpan = xMax > 0 ? xMax : 1;
  ctx.setLineDash([2, 2]);
  ctx.fillStyle = '#1f2933';
  ctx.font = '10px Arial';
  for (let i = 0; i <= 10; i++) {{
    const y = plot.top + i * (plotH / 10);
    const value = max - i * (span / 10);
    ctx.beginPath(); ctx.moveTo(plot.left, y); ctx.lineTo(w - plot.right, y); ctx.stroke();
    ctx.fillText(value.toFixed(0), 22, y + 3);
  }}
  for (let i = 0; i <= 5; i++) {{
    const x = plot.left + i * (plotW / 5);
    ctx.beginPath(); ctx.moveTo(x, plot.top); ctx.lineTo(x, h - plot.bottom); ctx.stroke();
    ctx.fillText(formatElapsed((i / 5) * xMax), x - 18, h - 12);
  }}
  ctx.setLineDash([]);
  ctx.strokeStyle = '#b8c4d4';
  ctx.strokeRect(plot.left, plot.top, plotW, plotH);
  ctx.fillStyle = '#1f2933';
  ctx.font = '11px Arial';
  ctx.fillText('Performance Metrics', 4, Math.floor(h / 2));
  ctx.font = 'italic 10px Arial';
  ctx.fillText('Elapsed time', Math.floor(w / 2) - 28, h - 3);
  drawLegend(ctx, title);
  ctx.strokeStyle = '#ff40ff';
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  values.forEach((v, idx) => {{
    const x = plot.left + (data.labels[idx] / xSpan) * plotW;
    const y = plot.top + plotH - ((v - min) / span) * plotH;
    if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }});
  ctx.stroke();
  return {{min, span, xSpan, plot}};
}}
function drawPeak(canvas, peak, scale) {{
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const plot = scale.plot;
  const x = plot.left + (peak.time / scale.xSpan) * (w - plot.left - plot.right);
  const y = plot.top + (canvas.height - plot.top - plot.bottom) - ((peak.value - scale.min) / scale.span) * (canvas.height - plot.top - plot.bottom);
  ctx.fillStyle = '#dc2626';
  ctx.beginPath();
  ctx.arc(x, y, 4, 0, Math.PI * 2);
  ctx.fill();
  const label = `peak: ${{peak.value.toFixed(2)}}`;
  ctx.font = '12px Arial';
  const textWidth = ctx.measureText(label).width;
  const labelX = Math.min(Math.max(x + 8, 52), w - textWidth - 8);
  const labelY = Math.max(y - 8, 16);
  ctx.fillText(label, labelX, labelY);
}}
for (const key of metrics) {{
  const canvas = document.getElementById(key);
  const scale = drawChart(canvas, data.series[key], metricTitles[key]);
  drawPeak(canvas, data.peaks[key], scale);
}}
</script>
</body>
</html>
""",
        encoding="utf-8",
    )
    return output_file


def generate_png_reports(csv_file: Path, output_dir: Path) -> list[Path]:
    rows = _read_monitor_csv(csv_file)
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return []
    paths: list[Path] = []
    x_values = _time_labels(rows)
    for key, title in METRICS:
        values = [row[key] for row in rows]
        peak = _peak(x_values, values)
        fig, ax = plt.subplots(figsize=(10, 3.2), facecolor="#eef6ff")
        ax.set_facecolor("#eef6ff")
        ax.plot(x_values, values, color="#ff40ff", linewidth=1.0, label=f"127.0.0.1 {title}")
        ax.scatter([peak["time"]], [peak["value"]], color="#dc2626", zorder=3)
        ax.annotate(
            f"peak: {peak['value']:.2f}",
            xy=(peak["time"], peak["value"]),
            xytext=(8, 8),
            textcoords="offset points",
            color="#dc2626",
        )
        ax.grid(True, linestyle=":", linewidth=0.7, color="#c8d2df")
        ax.legend(loc="upper left", frameon=False, fontsize=8)
        ax.set_xlabel("Elapsed time")
        ax.set_ylabel("Performance Metrics")
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)
        ax.set_xticks(ax.get_xticks())
        ax.set_xticklabels([_format_elapsed(float(value)) for value in ax.get_xticks()], fontsize=7)
        ax.tick_params(axis="y", labelsize=7)
        plt.tight_layout()
        path = output_dir / f"{key}.png"
        fig.savefig(path)
        plt.close(fig)
        paths.append(path)
    return paths
