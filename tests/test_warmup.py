import io
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

from autoperf.cli import _run_load
from autoperf.jmeter_aggregate import aggregate_jtl
from autoperf.jmeter_runner import run_jmeter
from autoperf.monitor import MonitorLoop
from autoperf.utils import AutoPerfError


class WarmupTests(unittest.TestCase):
    def test_request_start_boundaries_and_crossing_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            jtl = root / 'result.jtl'
            jtl.write_text('timeStamp,elapsed,label,success\n'
                           '1000,5000,warmup,false\n'
                           '2999,2000,warmup,false\n'
                           '3000,10,api,true\n'
                           '4999,20,api,true\n'
                           '5000,100,late,false\n', encoding='utf-8')
            config = root / 'config.json'
            config.write_text(json.dumps(dict(warmup=2, measurement_start_ms=3000,
                                              measurement_end_ms=5000)), encoding='utf-8')
            rows = aggregate_jtl(jtl)
            self.assertEqual([r['label'] for r in rows], ['api', 'TOTAL'])
            self.assertEqual(rows[-1]['samples'], 2)
            self.assertEqual(rows[-1]['average_ms'], 15)
            self.assertEqual(rows[-1]['error_pct'], 0)
            config.write_text('{"warmup": 0}', encoding='utf-8')
            self.assertEqual(aggregate_jtl(jtl)[-1]['samples'], 5)
            config.write_text('{"warmup": 2}', encoding='utf-8')
            with self.assertRaisesRegex(AutoPerfError, 'no measurement window'):
                aggregate_jtl(jtl)

    def test_runner_reports_jmeter_epoch_once(self):
        process = Mock()
        process.stdout = io.StringIO('JVM startup\nStarting standalone test @ date (100000)\n')
        process.wait.return_value = 0
        callback = Mock()
        with tempfile.TemporaryDirectory() as temp, \
                patch('autoperf.jmeter_runner.require_jmeter', return_value='jmeter'), \
                patch('autoperf.jmeter_runner.subprocess.Popen', return_value=process) as popen:
            root = Path(temp)
            self.assertEqual(run_jmeter(jmeter_bin='jmeter', jmx=root / 'a.jmx',
                                       result_jtl=root / 'result.jtl', jmeter_log=root / 'jmeter.log',
                                       logger=logging.getLogger('test'), on_test_start=callback), 0)
            callback.assert_called_once_with(100000)
            self.assertIn('-Jsampleresult.timestamp.start=true', popen.call_args.args[0])

    def test_load_shares_window_with_all_monitors_and_report_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = SimpleNamespace(warmup=120, duration=600, output_dir=root, jmeter_bin='jmeter',
                                  modified_jmx=root / 'a.jmx', jmeter_result_jtl=root / 'result.jtl')
            group = Mock(monitors=[Mock(), Mock()])
            data = {'warmup': 120}
            def run(**kwargs):
                group.start.assert_not_called()
                kwargs['on_test_start'](100000)
                return 0
            with patch('autoperf.cli.run_jmeter', side_effect=run):
                self.assertEqual(_run_load(cfg, group, data, logging.getLogger('test')), 0)
            group.start.assert_called_once()
            for monitor in group.monitors:
                self.assertEqual(monitor.measurement_start_ms, 220000)
                self.assertEqual(monitor.measurement_end_ms, 820000)
            saved = json.loads((root / 'config.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['measurement_start_ms'], 220000)
            self.assertEqual(saved['measurement_end_ms'], 820000)

    def test_stop_during_warmup_does_not_sample_or_write_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            csv_file = Path(temp) / 'monitor.csv'
            monitor = MonitorLoop(Path(temp), 'a', 1, 'device', csv_file, 1, logging.getLogger('test'))
            monitor.measurement_start_ms = 9999999999999
            monitor._stop.set()
            with patch('autoperf.monitor._run_monitor_scripts') as sample:
                monitor._run()
                sample.assert_not_called()
            self.assertFalse(csv_file.exists())


if __name__ == '__main__':
    unittest.main()
