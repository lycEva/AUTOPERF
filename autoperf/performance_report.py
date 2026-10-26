from __future__ import annotations

import csv
import html
import json
import math
import statistics
from datetime import datetime
from pathlib import Path

from .jmeter_aggregate import aggregate_jtl
from .report_generator import METRICS, _read_monitor_csv, _time_labels
from .utils import AutoPerfError


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile / 100 * len(ordered)) - 1)
    return ordered[min(index, len(ordered) - 1)]


def _read_config(run_dir: Path) -> dict:
    path = run_dir / "config.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AutoPerfError(f"invalid config.json: {path}") from exc
    return value if isinstance(value, dict) else {}


def _load_aggregate(run_dir: Path) -> list[dict]:
    aggregate_csv = run_dir / "jmeter_aggregate_report.csv"
    if aggregate_csv.is_file():
        with aggregate_csv.open("r", encoding="utf-8-sig", newline="") as fp:
            return list(csv.DictReader(fp))
    jtl = run_dir / "result.jtl"
    if jtl.is_file():
        return aggregate_jtl(jtl)
    return []


def _numeric(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _monitor_summary(run_dir: Path, path: Path | None = None) -> dict:
    path = path or run_dir / "monitor" / "monitor.csv"
    if not path.is_file():
        return {"available": False, "samples": 0, "metrics": {}, "series": {}}
    rows = _read_monitor_csv(path)
    labels = _time_labels(rows)
    metrics = {}
    series = {}
    for key, title in METRICS:
        values = [float(row[key]) for row in rows]
        metrics[key] = {
            "title": title,
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "avg": round(statistics.fmean(values), 2),
            "peak_at_minute": labels[values.index(max(values))] if labels else 0.0,
        }
        series[key] = {"labels": labels, "values": values}
    return {"available": True, "samples": len(rows), "metrics": metrics, "series": series}


def _jmeter_summary(rows: list[dict]) -> dict:
    total = next((row for row in rows if str(row.get("label", "")).upper() == "TOTAL"), None)
    if total is None:
        return {"available": False, "total": {}, "transactions": []}
    total_values = {key: _numeric(total.get(key)) for key in (
        "samples", "average_ms", "p90_ms", "p99_ms", "min_ms", "max_ms", "error_pct", "throughput_per_sec"
    )}
    transactions = []
    for row in rows:
        if str(row.get("label", "")).upper() == "TOTAL":
            continue
        item = dict(row)
        for key in item:
            if key != "label":
                item[key] = round(_numeric(item[key]), 2)
        transactions.append(item)
    return {"available": True, "total": total_values, "transactions": transactions}


def build_metrics(run_dir: Path) -> dict:
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise AutoPerfError(f"run directory not found: {run_dir}")
    jmeter = _jmeter_summary(_load_aggregate(run_dir))
    monitor = _monitor_summary(run_dir)
    config = _read_config(run_dir)
    container_monitors = {}
    for name, workers in config.get("monitor_containers", []):
        # Only read sampler output below this run directory.
        if not name or Path(name).name != name or name in {".", ".."} or "/" in name or "\\" in name:
            raise AutoPerfError(f"invalid monitor container name in config.json: {name!r}")
        container_monitors[name] = _monitor_summary(run_dir, run_dir / "monitor" / "containers" / name / "monitor.csv")
        container_monitors[name]["workers"] = workers
    total = jmeter.get("total", {})
    findings = []
    if total.get("error_pct", 0) > 0:
        findings.append(f"JMeter error rate is {total['error_pct']:.2f}%.")
    if total.get("p90_ms", 0) > 1000:
        findings.append(f"Total P90 response time is {total['p90_ms']:.2f} ms.")
    for key, label in (("cpu_usage", "CPU"), ("npu_usage", "NPU")):
        metric = monitor.get("metrics", {}).get(key)
        if metric and metric["max"] >= 90:
            findings.append(f"{label} peak usage reached {metric['max']:.2f}%.")
    for name, summary in container_monitors.items():
        for key, label in (("cpu_usage", "CPU"), ("npu_usage", "NPU")):
            metric = summary.get("metrics", {}).get(key)
            if metric and metric["max"] >= 90:
                findings.append(f"{name}: {label} peak usage reached {metric['max']:.2f}%.")
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "run_directory": str(run_dir),
        "config": config,
        "jmeter": jmeter,
        "monitor": monitor,
        "container_monitors": container_monitors,
        "findings": findings,
    }


def ai_prompt(metrics: dict) -> str:
    payload = json.dumps(metrics, ensure_ascii=False, indent=2)
    return (
        "你是性能测试分析师。请严格依据下方 JSON 生成中文测试报告。不得编造数据；无法证明根因时使用‘可能原因’。"
        "将结论分为事实、判断、建议，并引用具体指标。输出：1.测试摘要 2.总体结论 3.接口分析 4.资源分析 "
        "5.风险与瓶颈 6.优化建议 7.复测建议。\n\n数据：\n```json\n" + payload + "\n```"
    )


def _fmt(value: object, suffix: str = "") -> str:
    return f"{_numeric(value):,.2f}{suffix}"


def load_report_context(path: Path | None) -> dict:
    if path is None:
        return {}
    if not path.is_file():
        raise AutoPerfError(f"report context not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AutoPerfError(f"invalid report context JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AutoPerfError(f"report context must be a JSON object: {path}")
    return value


def _markdown(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def _context_items(context: dict, key: str) -> list[dict]:
    value = context.get(key, [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _duration_text(value: object) -> str:
    seconds = _numeric(value)
    if seconds <= 0:
        return "未采集"
    if seconds.is_integer() and int(seconds) % 60 == 0:
        return f"{int(seconds) // 60} 分钟"
    return f"{seconds:g} 秒"


def _resource_rows(metrics: dict) -> list[str]:
    monitor = metrics["monitor"]
    rows = []
    for key, title in METRICS:
        item = monitor.get("metrics", {}).get(key)
        if item is None:
            continue
        unit = "%" if key in {"cpu_usage", "npu_usage"} else " GiB" if key == "mem_usage" else " MiB"
        rows.append(
            f"| {_markdown(title)} | {_fmt(item['min'], unit)} | {_fmt(item['avg'], unit)} "
            f"| {_fmt(item['max'], unit)} | {_fmt(item['peak_at_minute'], ' 分钟')} |"
        )
    return rows


def generate_markdown_report(
    run_dir: Path,
    output_file: Path,
    title: str | None = None,
    context: dict | None = None,
) -> Path:
    """Generate a Word-style Markdown report from one AutoPerf result directory."""
    metrics = build_metrics(run_dir)
    context = context or {}
    config = metrics["config"]
    title = title or str(context.get("product_name") or config.get("test_name") or run_dir.name)
    version = str(context.get("version") or "未提供版本信息")
    generated_at = datetime.fromisoformat(metrics["generated_at"]).strftime("%Y年%m月%d日")
    purpose = str(
        context.get("test_purpose")
        or "验证系统在设定压力场景下的接口性能、资源使用情况和运行稳定性。"
    )
    scenario = str(context.get("scenario") or config.get("test_name") or run_dir.name)
    workers = config.get("service_workers", config.get("workers", "未采集"))
    service_threads = config.get("service_threads", "未采集")
    hardware = _context_items(context, "hardware")
    participants = _context_items(context, "participants")

    lines = [
        f"# {_markdown(title)}",
        "",
        f"## {_markdown(version)} 性能测试报告",
        "",
        f"> 生成日期：{generated_at}  ",
        f"> 结果目录：`{_markdown(metrics['run_directory'])}`",
        "",
        "## 1. 引言",
        "",
        "### 1.1 测试目的",
        "",
        _markdown(purpose),
        "",
        "## 2. 性能测试环境",
        "",
        "### 2.1 软硬件配置",
        "",
        "#### 硬件配置",
        "",
        "| 序号 | 设备名称 | 数量 | 硬件配置 |",
        "| --- | --- | --- | --- |",
    ]
    if hardware:
        for index, item in enumerate(hardware, start=1):
            lines.append(
                f"| {index} | {_markdown(item.get('name', '未提供'))} | "
                f"{_markdown(item.get('quantity', '未提供'))} | {_markdown(item.get('configuration', '未提供'))} |"
            )
    else:
        lines.append("| 1 | 未提供 | 未提供 | 硬件信息未随本次压测采集，请通过报告上下文补充。 |")

    lines.extend(
        [
            "",
            "#### 软件及测试配置",
            "",
            "| 项目 | 配置 |",
            "| --- | --- |",
            f"| 被测服务 | {_markdown(config.get('container', '未采集'))} |",
            f"| 服务进程数 | {_markdown(workers)} |",
            f"| 服务内部线程数 | {_markdown(service_threads)} |",
            f"| JMeter 并发用户数 | {_markdown(config.get('threads', '未采集'))} |",
            f"| 压测时长 | {_duration_text(config.get('duration'))} |",
            f"| 监控采样间隔 | {_markdown(config.get('interval', '未采集'))} 秒 |",
            "",
            "## 3. 测试实施情况",
            "",
            "### 3.1 测试参与人员",
            "",
            "| 序号 | 角色 | 人员 | 工作内容 |",
            "| --- | --- | --- | --- |",
        ]
    )
    if participants:
        for index, item in enumerate(participants, start=1):
            lines.append(
                f"| {index} | {_markdown(item.get('role', '未提供'))} | {_markdown(item.get('name', '未提供'))} | "
                f"{_markdown(item.get('responsibility', '性能测试'))} |"
            )
    else:
        lines.append("| 1 | 未提供 | 未提供 | 本次压测由 AutoPerf 自动执行，参与人信息未提供。 |")

    lines.extend(
        [
            "",
            "## 4. 测试结果及分析",
            "",
            "### 4.1 测试场景",
            "",
            f"- 场景名称：{_markdown(scenario)}",
            f"- 测试目录：`{_markdown(run_dir.name)}`",
            "",
            "### 4.2 接口性能测试结果",
            "",
            "| 任务 | 事务数 | 平均值(ms) | 90% 百分位(ms) | 最小值(ms) | 最大值(ms) | 异常率 | 吞吐量 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    transactions = metrics["jmeter"].get("transactions", [])
    if transactions:
        for item in transactions:
            lines.append(
                f"| {_markdown(item.get('label', '未命名任务'))} | {_fmt(item.get('samples'))} | "
                f"{_fmt(item.get('average_ms'))} | {_fmt(item.get('p90_ms'))} | "
                f"{_fmt(item.get('min_ms'))} | {_fmt(item.get('max_ms'))} | "
                f"{_fmt(item.get('error_pct'), '%')} | {_fmt(item.get('throughput_per_sec'), '/s')} |"
            )
    else:
        lines.append("| 未发现 JMeter 聚合数据 | - | - | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "### 4.3 服务器资源使用情况",
            "",
            "| 指标 | 最小值 | 平均值 | 峰值 | 峰值时间 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(_resource_rows(metrics) or ["| 未发现监控数据 | - | - | - | - |"])
    for name, summary in metrics["container_monitors"].items():
        lines.extend([
            "", f"#### 依赖容器：{_markdown(name)}", "",
            "| 指标 | 最小值 | 平均值 | 峰值 | 峰值时间 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ])
        lines.extend(_resource_rows({"monitor": summary}) or ["| 未发现监控数据 | - | - | - | - |"])
        directory = run_dir / "monitor" / "containers" / name
        for key, _ in METRICS:
            path = directory / f"{key}.png"
            if path.is_file():
                relative = path.relative_to(output_file.parent) if output_file.parent in path.parents else path
                lines.extend(["", f"![{_markdown(name)} {_markdown(key)}]({_markdown(relative.as_posix())})"])

    chart_paths = [run_dir / "monitor" / f"{key}.png" for key, _ in METRICS]
    available_charts = [path for path in chart_paths if path.is_file()]
    if available_charts:
        lines.extend(["", "#### 监控趋势图", ""])
        for path in available_charts:
            relative = path.relative_to(output_file.parent) if output_file.parent in path.parents else path
            lines.append(f"![{_markdown(path.stem)}]({_markdown(relative.as_posix())})")

    lines.extend(["", "## 5. 测试结论", ""])
    total = metrics["jmeter"].get("total", {})
    if total:
        lines.append(
            f"- 本次共完成 {_fmt(total.get('samples'))} 个事务，总错误率 {_fmt(total.get('error_pct'), '%')}，"
            f"P90 响应时间 {_fmt(total.get('p90_ms'), ' ms')}，吞吐量 {_fmt(total.get('throughput_per_sec'), '/s')}。"
        )
    if metrics["findings"]:
        lines.append("- 自动规则提示：")
        lines.extend(f"  - {_markdown(item)}" for item in metrics["findings"])
    else:
        lines.append("- 自动规则未发现错误率、P90 或资源峰值方面的预设风险。")
    if context.get("conclusion"):
        lines.extend(["", "### 5.1 人工结论", "", _markdown(context["conclusion"])])

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_file


def generate_html_report(run_dir: Path, output_file: Path, title: str | None = None) -> Path:
    metrics = build_metrics(run_dir)
    title = title or str(metrics["config"].get("test_name") or run_dir.name)
    total = metrics["jmeter"].get("total", {})
    cards = [
        ("Samples", _fmt(total.get("samples"))),
        ("Throughput", _fmt(total.get("throughput_per_sec"), "/s")),
        ("P90", _fmt(total.get("p90_ms"), " ms")),
        ("Error rate", _fmt(total.get("error_pct"), "%")),
    ]
    card_html = "".join(f'<div class="card"><b>{html.escape(k)}</b><strong>{html.escape(v)}</strong></div>' for k, v in cards)
    rows = []
    for item in metrics["jmeter"].get("transactions", []):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('label', '')))}</td>"
            f"<td>{_fmt(item.get('samples'))}</td>"
            f"<td>{_fmt(item.get('average_ms'))}</td>"
            f"<td>{_fmt(item.get('p90_ms'))}</td>"
            f"<td>{_fmt(item.get('error_pct'), '%')}</td>"
            f"<td>{_fmt(item.get('throughput_per_sec'), '/s')}</td></tr>"
        )
    monitor_payload = json.dumps(metrics["monitor"].get("series", {}), ensure_ascii=False)
    findings = "".join(f"<li>{html.escape(item)}</li>" for item in metrics["findings"]) or "<li>No automatic rule-based findings.</li>"
    chart_paths = [run_dir / "monitor" / f"{key}.png" for key, _ in METRICS]
    chart_html = "".join(f'<figure><figcaption>{html.escape(title)}</figcaption><img src="monitor/{html.escape(path.name)}" alt="{html.escape(title)}"></figure>' for path, (_, title) in zip(chart_paths, METRICS) if path.is_file()) or "<p>PNG monitor charts are unavailable; see monitor_report.html.</p>"
    for name, summary in metrics["container_monitors"].items():
        chart_html += f"<h3>{html.escape(name)}</h3>"
        chart_html += "<table><tr><th>Metric</th><th>Min</th><th>Average</th><th>Max</th></tr>"
        for key, item in summary.get("metrics", {}).items():
            chart_html += (
                f"<tr><td>{html.escape(item['title'])}</td><td>{_fmt(item['min'])}</td>"
                f"<td>{_fmt(item['avg'])}</td><td>{_fmt(item['max'])}</td></tr>"
            )
        chart_html += "</table>"
        for key, metric_title in METRICS:
            path = run_dir / "monitor" / "containers" / name / f"{key}.png"
            if path.is_file():
                source = path.relative_to(output_file.parent) if output_file.parent in path.parents else path
                chart_html += f'<figure><figcaption>{html.escape(name)}: {html.escape(metric_title)}</figcaption><img src="{html.escape(source.as_posix())}" alt="{html.escape(metric_title)}"></figure>'
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>{html.escape(title)}</title>
<style>body{{font-family:Arial,sans-serif;background:#f5f7fa;color:#1f2933;margin:0}}main{{max-width:1180px;margin:28px auto;padding:0 20px}}h1{{margin-bottom:6px}}.muted{{color:#667085}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0}}.card,section{{background:#fff;border:1px solid #dbe2ea;border-radius:6px;padding:16px}}.card strong{{display:block;font-size:24px;margin-top:8px}}section{{margin:14px 0}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid #edf0f3;text-align:right}}th:first-child,td:first-child{{text-align:left}}canvas{{width:100%;height:260px;margin-top:10px}}</style></head>
<body><main><h1>{html.escape(title)}</h1><div class='muted'>AutoPerf performance report · {html.escape(metrics['generated_at'])}</div><div class='cards'>{card_html}</div>
<section><h2>总体结论</h2><ul>{findings}</ul></section><section><h2>接口指标</h2><table><thead><tr><th>Label</th><th>Samples</th><th>Average (ms)</th><th>P90 (ms)</th><th>Error</th><th>Throughput</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="6">No JMeter aggregate data</td></tr>'}</tbody></table></section>
<section><h2>资源趋势</h2><div class='charts'>{chart_html}</div></section><section><h2>AI 分析输入</h2><p>可将下方提示词和同目录 metrics.json 一起提交给企业内部大模型：</p><pre>{html.escape(ai_prompt(metrics))}</pre></section>
</main></body></html>""",
        encoding="utf-8",
    )
    return output_file


def write_metrics(run_dir: Path, output_file: Path) -> Path:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(build_metrics(run_dir), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_file


def write_ai_prompt(run_dir: Path, output_file: Path) -> Path:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(ai_prompt(build_metrics(run_dir)) + "\n", encoding="utf-8")
    return output_file
