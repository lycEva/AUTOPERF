import json
import tempfile
import unittest
from pathlib import Path

from autoperf.batch_report_cli import build_parser, generate_batch_reports


class BatchReportTest(unittest.TestCase):
    def test_parser_accepts_context(self):
        args = build_parser().parse_args([
            "--result-root", "results",
            "--context", "context.json",
        ])
        self.assertEqual(args.context, "context.json")

    def test_context_is_applied_to_each_scenario_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scenario = root / "scenario-a"
            scenario.mkdir()
            (scenario / "config.json").write_text(
                json.dumps({"test_name": "1process-3threads", "container": "fs"}),
                encoding="utf-8",
            )
            (scenario / "jmeter_aggregate_report.csv").write_text(
                "label,samples,average_ms,p90_ms,min_ms,max_ms,error_pct,throughput_per_sec\n"
                "TOTAL,10,20,30,5,50,0,2\n"
                "api,10,20,30,5,50,0,2\n",
                encoding="utf-8",
            )
            context = {
                "product_name": "财报识别引擎",
                "version": "2.8.31",
                "scenario": "模板示例场景",
                "hardware": [{"name": "NPU服务器", "quantity": 1, "configuration": "测试配置"}],
            }

            result = generate_batch_reports(root, context=context)

            report = (scenario / "performance_report.md").read_text(encoding="utf-8")
            self.assertIn("# 财报识别引擎", report)
            self.assertIn("## 2.8.31 性能测试报告", report)
            self.assertIn("场景名称：1process-3threads", report)
            self.assertNotIn("模板示例场景", report)
            self.assertEqual(result["run_dirs"], [scenario])


if __name__ == "__main__":
    unittest.main()
