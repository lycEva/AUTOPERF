from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from autoperf.jmeter_aggregate import aggregate_jtl, generate_jmeter_aggregate_report
from autoperf.report_generator import _time_axis_limit, generate_html_report


class MonitorReportTimeAxisTests(unittest.TestCase):
    def test_html_report_uses_elapsed_minutes_as_time_axis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_file = tmp_path / "monitor.csv"
            output_file = tmp_path / "monitor_report.html"
            csv_file.write_text(
                "\n".join(
                    [
                        "timestamp,cpu_usage,mem_usage,npu_usage,npu_mem",
                        "2026-05-14 10:00:00,1,2,3,4",
                        "2026-05-14 10:01:00,2,3,4,5",
                        "2026-05-14 10:15:00,3,4,5,6",
                    ]
                ),
                encoding="utf-8",
            )

            generate_html_report(csv_file, output_file)

            html = output_file.read_text(encoding="utf-8")
            payload_match = re.search(r"const data = (\{.*?\});", html)
            self.assertIsNotNone(payload_match)
            payload = json.loads(payload_match.group(1))
            self.assertEqual(payload["labels"], [0.0, 1.0, 15.0])
            self.assertIn("Elapsed time", html)

    def test_html_report_uses_jmeter_style_chart_treatment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_file = tmp_path / "monitor.csv"
            output_file = tmp_path / "monitor_report.html"
            csv_file.write_text(
                "\n".join(
                    [
                        "timestamp,cpu_usage,mem_usage,npu_usage,npu_mem",
                        "2026-05-14 10:00:00,1,2,3,4",
                        "2026-05-14 10:00:01,2,3,4,5",
                    ]
                ),
                encoding="utf-8",
            )

            generate_html_report(csv_file, output_file)

            html = output_file.read_text(encoding="utf-8")
            self.assertIn("#eef6ff", html)
            self.assertIn("#ff40ff", html)
            self.assertIn("ctx.setLineDash([2, 2])", html)
            self.assertIn("drawLegend", html)
            self.assertIn("Elapsed time", html)

    def test_html_report_includes_peak_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_file = tmp_path / "monitor.csv"
            output_file = tmp_path / "monitor_report.html"
            csv_file.write_text(
                "\n".join(
                    [
                        "timestamp,cpu_usage,mem_usage,npu_usage,npu_mem",
                        "2026-05-14 10:00:00,1,2,3,4",
                        "2026-05-14 10:01:00,9,3,8,5",
                        "2026-05-14 10:02:00,4,6,5,7",
                    ]
                ),
                encoding="utf-8",
            )

            generate_html_report(csv_file, output_file)

            html = output_file.read_text(encoding="utf-8")
            payload_match = re.search(r"const data = (\{.*?\});", html)
            self.assertIsNotNone(payload_match)
            payload = json.loads(payload_match.group(1))
            self.assertEqual(payload["peaks"]["cpu_usage"], {"index": 1, "time": 1.0, "value": 9.0})
            self.assertIn("peak:", html)
            self.assertIn("drawPeak", html)

    def test_time_axis_limit_uses_actual_elapsed_span(self) -> None:
        self.assertEqual(_time_axis_limit([0.0, 0.25, 10.05]), 10.05)
        self.assertEqual(_time_axis_limit([0.0]), 1.0)


class JMeterAggregateReportTests(unittest.TestCase):
    def test_aggregate_jtl_calculates_jmeter_summary_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jtl_file = Path(tmp) / "result.jtl"
            jtl_file.write_text(
                "\n".join(
                    [
                        "timeStamp,elapsed,label,responseCode,success",
                        "1000,100,login,200,true",
                        "1300,300,login,200,true",
                        "1700,900,login,500,false",
                        "2200,200,query,200,true",
                    ]
                ),
                encoding="utf-8",
            )

            rows = aggregate_jtl(jtl_file)

            login = rows[0]
            total = rows[-1]
            self.assertEqual(login["label"], "login")
            self.assertEqual(login["samples"], 3)
            self.assertEqual(login["average_ms"], 433.33)
            self.assertEqual(login["p90_ms"], 900.0)
            self.assertEqual(login["min_ms"], 100.0)
            self.assertEqual(login["max_ms"], 900.0)
            self.assertEqual(login["error_pct"], 33.33)
            self.assertEqual(total["label"], "TOTAL")
            self.assertEqual(total["samples"], 4)
            self.assertEqual(total["throughput_per_sec"], 2.5)

    def test_generate_jmeter_aggregate_report_writes_html_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            jtl_file = tmp_path / "result.jtl"
            html_file = tmp_path / "jmeter_aggregate_report.html"
            csv_file = tmp_path / "jmeter_aggregate_report.csv"
            jtl_file.write_text(
                "\n".join(
                    [
                        "timeStamp,elapsed,label,success",
                        "1000,100,login,true",
                        "1200,200,login,false",
                    ]
                ),
                encoding="utf-8",
            )

            generate_jmeter_aggregate_report(jtl_file, html_file, csv_file)

            html = html_file.read_text(encoding="utf-8")
            csv_text = csv_file.read_text(encoding="utf-8")
            self.assertIn("JMeter Aggregate Report", html)
            self.assertIn("Transactions", html)
            self.assertIn("login", html)
            self.assertIn("label,samples,average_ms,p90_ms,min_ms,max_ms,error_pct,throughput_per_sec", csv_text)


if __name__ == "__main__":
    unittest.main()
