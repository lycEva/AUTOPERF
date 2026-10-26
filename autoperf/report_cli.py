from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .batch_report_cli import _request_ai_analysis, build_ai_config
from .performance_report import (
    ai_prompt,
    build_metrics,
    generate_html_report,
    generate_markdown_report,
    load_report_context,
    write_ai_prompt,
    write_metrics,
)
from .utils import AutoPerfError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m autoperf.report_cli",
        description="Generate HTML and Markdown performance reports from an AutoPerf run directory.",
    )
    parser.add_argument("--run-dir", required=True, help="completed AutoPerf run directory")
    parser.add_argument("--output", help="output HTML path, defaults to performance_report.html")
    parser.add_argument("--markdown", help="output Markdown path, defaults to performance_report.md")
    parser.add_argument("--metrics", help="normalized metrics JSON path")
    parser.add_argument("--ai-prompt", dest="ai_prompt", help="AI analysis prompt path")
    parser.add_argument("--context", help="optional report context JSON for product, hardware, and participant information")
    parser.add_argument("--title", help="report title")
    parser.add_argument("--ai", action="store_true", help="call an OpenAI-compatible API to generate the analysis")
    parser.add_argument("--ai-api-key", help="API key; prefer AUTOPERF_AI_API_KEY to avoid exposing it in shell history")
    parser.add_argument("--ai-base-url", help="API base URL, defaults to AUTOPERF_AI_BASE_URL or https://api.openai.com/v1")
    parser.add_argument("--ai-model", help="model name, defaults to AUTOPERF_AI_MODEL or gpt-4o-mini")
    parser.add_argument("--ai-timeout", type=int, help="API timeout in seconds, defaults to AUTOPERF_AI_TIMEOUT or 120")
    parser.add_argument("--ai-output", help="AI analysis Markdown path, defaults to ai_report.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_dir = Path(args.run_dir).resolve()
        ai_config = build_ai_config(args.ai_api_key, args.ai_base_url, args.ai_model, args.ai_timeout) if args.ai else None
        html_file = Path(args.output).resolve() if args.output else run_dir / "performance_report.html"
        markdown_file = Path(args.markdown).resolve() if args.markdown else run_dir / "performance_report.md"
        metrics_file = Path(args.metrics).resolve() if args.metrics else run_dir / "metrics.json"
        prompt_file = Path(args.ai_prompt).resolve() if args.ai_prompt else run_dir / "ai_report_prompt.txt"
        ai_output_file = Path(args.ai_output).resolve() if args.ai_output else run_dir / "ai_report.md"
        context = load_report_context(Path(args.context).resolve()) if args.context else {}
        generate_html_report(run_dir, html_file, args.title)
        generate_markdown_report(run_dir, markdown_file, args.title, context)
        write_metrics(run_dir, metrics_file)
        write_ai_prompt(run_dir, prompt_file)
        if ai_config:
            analysis = _request_ai_analysis(ai_prompt(build_metrics(run_dir)), ai_config)
            ai_output_file.parent.mkdir(parents=True, exist_ok=True)
            ai_output_file.write_text(analysis + "\n", encoding="utf-8")
        print(f"Performance report: {html_file}")
        print(f"Markdown report: {markdown_file}")
        print(f"Normalized metrics: {metrics_file}")
        print(f"AI report prompt: {prompt_file}")
        if ai_config:
            print(f"AI analysis: {ai_output_file}")
        return 0
    except AutoPerfError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
