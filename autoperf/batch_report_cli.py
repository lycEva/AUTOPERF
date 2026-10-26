from __future__ import annotations

import argparse
import base64
import html
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .performance_report import (
    _fmt,
    build_metrics,
    generate_html_report,
    generate_markdown_report,
    load_report_context,
    write_ai_prompt,
    write_metrics,
)
from .utils import AutoPerfError


@dataclass(frozen=True)
class AIConfig:
    api_key: str
    base_url: str
    model: str
    timeout: int


def build_ai_config(
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout: int | None = None,
) -> AIConfig:
    api_key = (api_key or os.getenv("AUTOPERF_AI_API_KEY") or "").strip()
    if not api_key:
        raise AutoPerfError("AI analysis requires --ai-api-key or AUTOPERF_AI_API_KEY")
    try:
        timeout = int(timeout if timeout is not None else os.getenv("AUTOPERF_AI_TIMEOUT", "120"))
    except (TypeError, ValueError) as exc:
        raise AutoPerfError("AI timeout must be a positive integer") from exc
    if timeout <= 0:
        raise AutoPerfError("AI timeout must be a positive integer")
    base_url = (base_url or os.getenv("AUTOPERF_AI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = (model or os.getenv("AUTOPERF_AI_MODEL") or "gpt-4o-mini").strip()
    if not base_url:
        raise AutoPerfError("AI base URL must not be empty")
    if not model:
        raise AutoPerfError("AI model must not be empty")
    return AIConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
    )


def _ai_endpoint(base_url: str) -> str:
    return base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"


def _request_ai_analysis(prompt: str, config: AIConfig) -> str:
    payload = json.dumps(
        {
            "model": config.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是性能测试分析助手。严格依据输入数据分析，不要编造不存在的指标。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        _ai_endpoint(config.base_url),
        data=payload,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except OSError:
            detail = ""
        raise AutoPerfError(f"AI request failed with HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AutoPerfError(f"AI request failed: {exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AutoPerfError("AI response was not valid JSON") from exc

    try:
        content = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AutoPerfError("AI response did not contain choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise AutoPerfError("AI response contained an empty analysis")
    return content.strip()


def discover_run_dirs(root: Path) -> list[Path]:
    root = root.resolve()
    if not root.is_dir():
        raise AutoPerfError(f"result root not found: {root}")
    candidates: set[Path] = set()
    for path in root.rglob("result.jtl"):
        candidates.add(path.parent)
    for path in root.rglob("jmeter_aggregate_report.csv"):
        candidates.add(path.parent)
    for path in root.rglob("monitor.csv"):
        if path.parent.name == "monitor":
            candidates.add(path.parent.parent)
    return sorted(candidates, key=lambda item: str(item).lower())


def _scenario_name(root: Path, run_dir: Path) -> str:
    try:
        return run_dir.relative_to(root).as_posix()
    except ValueError:
        return run_dir.name


def _summary_item(root: Path, run_dir: Path) -> dict:
    metrics = build_metrics(run_dir)
    return {
        "name": _scenario_name(root, run_dir),
        "run_directory": str(run_dir),
        "config": metrics.get("config", {}),
        "jmeter": metrics.get("jmeter", {}).get("total", {}),
        "monitor": metrics.get("monitor", {}).get("metrics", {}),
        "findings": metrics.get("findings", []),
    }


def build_batch_metrics(root: Path, run_dirs: list[Path] | None = None) -> dict:
    root = root.resolve()
    runs = run_dirs if run_dirs is not None else discover_run_dirs(root)
    scenarios, errors = [], []
    for run_dir in runs:
        try:
            scenarios.append(_summary_item(root, run_dir))
        except AutoPerfError as exc:
            errors.append({"run_directory": str(run_dir), "error": str(exc)})
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "result_root": str(root),
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "errors": errors,
    }


def batch_ai_prompt(metrics: dict) -> str:
    payload = json.dumps(metrics, ensure_ascii=False, indent=2)
    return (
        "你是性能测试负责人。请根据下方多个场景的结构化数据生成一份中文汇总报告。"
        "不得编造数据；请横向比较不同并发数、worker 数或场景的吞吐量、P90、错误率和资源峰值。"
        "输出：1.整体结论 2.场景对比 3.容量拐点 4.资源瓶颈 5.风险与建议 6.下一轮复测方案。"
        "每条判断引用场景名称和具体指标。\n\n数据：\n```json\n" + payload + "\n```"
    )


def _detail_html(root: Path, run_dir: Path, output_file: Path) -> str:
    metrics = build_metrics(run_dir)
    jmeter, monitor = metrics.get("jmeter", {}), metrics.get("monitor", {})
    total = jmeter.get("total", {})
    scenario = html.escape(_scenario_name(root, run_dir))
    cards = "".join(
        f"<div class='metric'><b>{label}</b><strong>{value}</strong></div>"
        for label, value in (("Samples", _fmt(total.get("samples"))), ("Throughput", _fmt(total.get("throughput_per_sec"), "/s")), ("P90", _fmt(total.get("p90_ms"), " ms")), ("Error rate", _fmt(total.get("error_pct"), "%")))
    )
    interface_rows = "".join(
        "<tr>" + f"<td>{html.escape(str(item.get('label', '')))}</td>" + f"<td>{_fmt(item.get('samples'))}</td>" + f"<td>{_fmt(item.get('average_ms'))}</td>" + f"<td>{_fmt(item.get('p90_ms'))}</td>" + f"<td>{_fmt(item.get('error_pct'), '%')}</td>" + f"<td>{_fmt(item.get('throughput_per_sec'), '/s')}</td></tr>"
        for item in jmeter.get("transactions", [])
    ) or '<tr><td colspan="6">无 JMeter 聚合数据</td></tr>'
    resource_rows = "".join(
        "<tr>" + f"<td>{html.escape(str(item.get('title', key)))}</td>" + f"<td>{_fmt(item.get('min'))}</td>" + f"<td>{_fmt(item.get('avg'))}</td>" + f"<td>{_fmt(item.get('max'))}</td>" + f"<td>{_fmt(item.get('peak_at_minute'), ' min')}</td></tr>"
        for key, item in monitor.get("metrics", {}).items()
    ) or '<tr><td colspan="5">无监控数据</td></tr>'
    findings = "".join(f"<li>{html.escape(item)}</li>" for item in metrics.get("findings", [])) or "<li>未触发规则型风险提示。</li>"
    charts = []
    for key, title in (("cpu_usage", "CPU Usage"), ("mem_usage", "Memory Usage"), ("npu_usage", "NPU Usage"), ("npu_mem", "NPU Memory")):
        image = run_dir / "monitor" / f"{key}.png"
        if image.is_file():
            encoded = base64.b64encode(image.read_bytes()).decode("ascii")
            charts.append(f"<figure><figcaption>{title}</figcaption><img src='data:image/png;base64,{encoded}' alt='{title}'></figure>")
    chart_html = "".join(charts) or "<p>PNG 监控图不可用，请查看场景目录中的 monitor_report.html。</p>"
    standalone = Path(os.path.relpath(run_dir / "performance_report.html", output_file.parent)).as_posix()
    return f"""<article class='scenario'><div class='scenario-heading'><h2>{scenario}</h2><a href='{html.escape(standalone)}'>打开独立报告</a></div><div class='metrics'>{cards}</div><h3>自动结论</h3><ul>{findings}</ul><h3>接口详细指标</h3><table><thead><tr><th>Label</th><th>Samples</th><th>Average (ms)</th><th>P90 (ms)</th><th>Error</th><th>Throughput</th></tr></thead><tbody>{interface_rows}</tbody></table><h3>资源详细指标</h3><table><thead><tr><th>Metric</th><th>Min</th><th>Average</th><th>Max</th><th>Peak time</th></tr></thead><tbody>{resource_rows}</tbody></table><div class='charts'>{chart_html}</div></article>"""


def generate_batch_html(
    root: Path,
    metrics: dict,
    output_file: Path,
    ai_analysis: str | None = None,
) -> Path:
    rows = []
    for item in metrics["scenarios"]:
        jmeter, monitor = item.get("jmeter", {}), item.get("monitor", {})
        rows.append("<tr>" + f"<td>{html.escape(item['name'])}</td>" + f"<td>{_fmt(jmeter.get('samples'))}</td>" + f"<td>{_fmt(jmeter.get('throughput_per_sec'), '/s')}</td>" + f"<td>{_fmt(jmeter.get('p90_ms'), ' ms')}</td>" + f"<td>{_fmt(jmeter.get('error_pct'), '%')}</td>" + f"<td>{_fmt(monitor.get('cpu_usage', {}).get('max', '-'), '%')}</td>" + f"<td>{_fmt(monitor.get('npu_usage', {}).get('max', '-'), '%')}</td>" + f"<td>{html.escape('; '.join(item.get('findings', [])) or '-')}</td></tr>")
    rows = rows or ['<tr><td colspan="8">未发现包含 AutoPerf 产物的场景目录</td></tr>']
    details = "".join(_detail_html(root, Path(item["run_directory"]), output_file) for item in metrics["scenarios"])
    ai_section = (
        f"<section><h2>AI 汇总分析</h2><pre>{html.escape(ai_analysis)}</pre></section>"
        if ai_analysis
        else ""
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>AutoPerf 场景汇总</title><style>body{{font-family:Arial,sans-serif;background:#f5f7fa;color:#1f2933;margin:0}}main{{max-width:1500px;margin:28px auto;padding:0 20px}}section,.scenario{{background:#fff;border:1px solid #dbe2ea;border-radius:6px;padding:16px;margin:14px 0}}h1{{margin-bottom:6px}}h2{{margin-top:0}}h3{{margin:20px 0 10px}}.muted{{color:#667085}}.scenario-heading{{display:flex;justify-content:space-between;align-items:center;gap:16px;border-bottom:1px solid #edf0f3}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}}.metric{{border:1px solid #e4e7ec;padding:12px;border-radius:4px}}.metric strong{{display:block;font-size:22px;margin-top:6px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid #edf0f3;text-align:right;vertical-align:top}}th:first-child,td:first-child,td:last-child{{text-align:left}}th{{background:#f7f8fa}}pre{{white-space:pre-wrap;max-height:420px;overflow:auto}}a{{color:#1769aa}}.charts{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:16px}}figure{{margin:0;border:1px solid #edf0f3;padding:8px}}figure img{{width:100%;height:auto;display:block}}figcaption{{font-weight:600;margin-bottom:6px}}</style></head><body><main><h1>AutoPerf 多场景性能测试汇总</h1><div class='muted'>结果根目录：{html.escape(str(root))} · 场景数：{metrics['scenario_count']} · 生成时间：{html.escape(metrics['generated_at'])}</div><section><h2>场景对比</h2><table><thead><tr><th>场景</th><th>Samples</th><th>Throughput</th><th>P90</th><th>Error</th><th>CPU Peak</th><th>NPU Peak</th><th>自动发现</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section><section><h2>所有场景详细报告</h2>{details or '<p>无场景详细数据。</p>'}</section>{ai_section}</main></body></html>""", encoding="utf-8")
    return output_file


def generate_batch_reports(
    root: Path,
    output_file: Path | None = None,
    *,
    ai_config: AIConfig | None = None,
    context: dict | None = None,
) -> dict:
    root = root.resolve()
    context = context or {}
    run_dirs = discover_run_dirs(root)
    metrics = build_batch_metrics(root, run_dirs)
    for run_dir in run_dirs:
        generate_html_report(run_dir, run_dir / "performance_report.html")
        report_context = dict(context)
        # A batch report must retain each run's actual scenario name.
        config = build_metrics(run_dir).get("config", {})
        report_context["scenario"] = config.get("test_name") or run_dir.name
        generate_markdown_report(run_dir, run_dir / "performance_report.md", context=report_context)
        write_metrics(run_dir, run_dir / "metrics.json")
        write_ai_prompt(run_dir, run_dir / "ai_report_prompt.txt")
    output_file = output_file or root / "performance_summary.html"
    metrics_file, prompt_file = output_file.with_name("performance_summary.json"), output_file.with_name("ai_summary_prompt.txt")
    metrics_file.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompt_file.write_text(batch_ai_prompt(metrics) + "\n", encoding="utf-8")
    ai_analysis = _request_ai_analysis(batch_ai_prompt(metrics), ai_config) if ai_config else None
    ai_summary_file = None
    if ai_analysis:
        ai_summary_file = output_file.with_name("ai_summary.md")
        ai_summary_file.write_text(ai_analysis + "\n", encoding="utf-8")
    generate_batch_html(root, metrics, output_file, ai_analysis=ai_analysis)
    return {
        "root": root,
        "run_dirs": run_dirs,
        "summary_html": output_file,
        "summary_metrics": metrics_file,
        "summary_prompt": prompt_file,
        "ai_summary": ai_summary_file,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m autoperf.batch_report_cli", description="Generate one detailed report from multiple AutoPerf scenario folders.")
    parser.add_argument("--result-root", required=True, help="root directory containing multiple test scenario folders")
    parser.add_argument("--output", help="summary HTML path, defaults to performance_summary.html under result root")
    parser.add_argument("--context", help="optional report context JSON applied to each scenario Markdown report")
    parser.add_argument("--ai", action="store_true", help="call an OpenAI-compatible API to generate the summary")
    parser.add_argument("--ai-api-key", help="API key; prefer AUTOPERF_AI_API_KEY to avoid exposing it in shell history")
    parser.add_argument("--ai-base-url", help="API base URL, defaults to AUTOPERF_AI_BASE_URL or https://api.openai.com/v1")
    parser.add_argument("--ai-model", help="model name, defaults to AUTOPERF_AI_MODEL or gpt-4o-mini")
    parser.add_argument("--ai-timeout", type=int, help="API timeout in seconds, defaults to AUTOPERF_AI_TIMEOUT or 120")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ai_config = build_ai_config(args.ai_api_key, args.ai_base_url, args.ai_model, args.ai_timeout) if args.ai else None
        context = load_report_context(Path(args.context).resolve()) if args.context else {}
        result = generate_batch_reports(
            Path(args.result_root),
            Path(args.output).resolve() if args.output else None,
            ai_config=ai_config,
            context=context,
        )
        print(f"Discovered scenarios: {len(result['run_dirs'])}")
        print(f"Summary report: {result['summary_html']}")
        print(f"Summary metrics: {result['summary_metrics']}")
        print(f"AI summary prompt: {result['summary_prompt']}")
        if result["ai_summary"]:
            print(f"AI summary: {result['ai_summary']}")
        return 0
    except AutoPerfError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
