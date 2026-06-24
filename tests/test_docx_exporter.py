from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from autoperf.cli import build_parser, cmd_export_docx
from autoperf.docx_exporter import classify_result, collect_run_results, export_docx_report


DOC_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _write_run(
    root: Path,
    name: str,
    *,
    test_name: str,
    service_workers: int,
    service_threads: int,
    threads: int,
    duration: int,
) -> Path:
    run_dir = root / name
    monitor_dir = run_dir / "monitor"
    monitor_dir.mkdir(parents=True)
    (run_dir / "config.json").write_text(
        json.dumps(
            {
                "test_name": test_name,
                "service_workers": service_workers,
                "service_threads": service_threads,
                "threads": threads,
                "duration": duration,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "jmeter_aggregate_report.csv").write_text(
        "\n".join(
            [
                "label,samples,average_ms,p90_ms,min_ms,max_ms,error_pct,throughput_per_sec",
                f"{test_name},12,101.5,150.0,80.0,220.0,0.0,2.5",
                "TOTAL,12,101.5,150.0,80.0,220.0,0.0,2.5",
            ]
        ),
        encoding="utf-8",
    )
    (monitor_dir / "monitor.csv").write_text(
        "\n".join(
            [
                "timestamp,cpu_usage,mem_usage,npu_usage,npu_mem",
                "2026-05-15 10:00:00,10,2.5,30,5000",
                "2026-05-15 10:00:01,15,3.25,42,6144",
            ]
        ),
        encoding="utf-8",
    )
    return run_dir


def _write_docx(path: Path, body_xml: str) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
        )
        zf.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "word/document.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{DOC_NS}">
  <w:body>{body_xml}<w:sectPr/></w:body>
</w:document>""",
        )


def _read_document_xml(path: Path) -> str:
    with zipfile.ZipFile(path, "r") as zf:
        return zf.read("word/document.xml").decode("utf-8")


class DocxExporterTests(unittest.TestCase):
    def test_collect_run_results_reads_jmeter_and_monitor_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = _write_run(
                root,
                "baseline",
                test_name="财报识别",
                service_workers=1,
                service_threads=1,
                threads=1,
                duration=600,
            )

            results = collect_run_results(root)

            self.assertEqual(len(results), 1)
            result = results[0]
            self.assertEqual(result.path, run_dir)
            self.assertEqual(result.test_name, "财报识别")
            self.assertEqual(result.service_workers, 1)
            self.assertEqual(result.service_threads, 1)
            self.assertEqual(result.threads, 1)
            self.assertEqual(result.duration, 600)
            self.assertEqual(result.label, "财报识别")
            self.assertEqual(result.samples, 12)
            self.assertEqual(result.average_ms, 101.5)
            self.assertEqual(result.npu_usage_peak, 42.0)
            self.assertEqual(result.npu_mem_peak, 6144.0)
            self.assertEqual(result.mem_peak, 3.25)

    def test_classify_result_maps_runs_to_report_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run(root, "baseline", test_name="baseline", service_workers=1, service_threads=1, threads=1, duration=600)
            _write_run(root, "single", test_name="single", service_workers=1, service_threads=3, threads=3, duration=900)
            _write_run(root, "multi", test_name="multi", service_workers=3, service_threads=1, threads=3, duration=900)
            _write_run(root, "stable", test_name="stable", service_workers=1, service_threads=3, threads=10, duration=43200)

            by_name = {item.test_name: classify_result(item) for item in collect_run_results(root)}

            self.assertEqual(by_name["baseline"], "baseline")
            self.assertEqual(by_name["single"], "single_concurrency")
            self.assertEqual(by_name["multi"], "multi_process")
            self.assertEqual(by_name["stable"], "stability")

    def test_export_docx_replaces_marker_paragraphs_with_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run(root / "results", "baseline", test_name="财报识别", service_workers=1, service_threads=1, threads=1, duration=600)
            template = root / "template.docx"
            output = root / "output.docx"
            _write_docx(
                template,
                f'<w:p><w:r><w:t>{{{{AUTOPERF_BASELINE_TABLE}}}}</w:t></w:r></w:p>',
            )

            export_docx_report(root / "results", template, output)

            xml = _read_document_xml(output)
            self.assertIn("基准测试", xml)
            self.assertIn("财报识别", xml)
            self.assertIn("101.50", xml)
            self.assertIn("6144", xml)
            self.assertNotIn("AUTOPERF_BASELINE_TABLE", xml)

    def test_export_docx_appends_summary_when_template_has_no_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run(root / "results", "single", test_name="财报三表查询", service_workers=1, service_threads=3, threads=3, duration=900)
            template = root / "template.docx"
            output = root / "output.docx"
            _write_docx(template, '<w:p><w:r><w:t>原模板内容</w:t></w:r></w:p>')

            export_docx_report(root / "results", template, output)

            xml = _read_document_xml(output)
            self.assertIn("原模板内容", xml)
            self.assertIn("AutoPerf 自动汇总结果", xml)
            self.assertIn("单交易并发", xml)
            self.assertIn("财报三表查询", xml)

    def test_cli_parser_supports_export_docx_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["export-docx", "--results", "r", "--template", "t.docx", "--output", "o.docx"])

        self.assertIs(args.func, cmd_export_docx)
        self.assertEqual(args.results, "r")
        self.assertEqual(args.template, "t.docx")
        self.assertEqual(args.output, "o.docx")


if __name__ == "__main__":
    unittest.main()
