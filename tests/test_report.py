import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from check_report import verify
from benchmark import render


class RetainedReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report=json.loads((ROOT/'results/native-macos-arm64/report.json').read_text())

    def test_all_retained_trials_and_html(self):
        self.assertEqual(verify(self.report),24)
        self.assertEqual((ROOT/'results/native-macos-arm64/report.html').read_text(),render(self.report))

    def test_reject_selective_pair_removal(self):
        report=copy.deepcopy(self.report)
        report['trials']=report['trials'][2:]
        with self.assertRaises(AssertionError):verify(report)

    def test_reject_forged_fairness_latency_rss_and_payload(self):
        for field in ['weighted_jain','elapsed_s','peak_sampled_proxy_rss_bytes']:
            report=copy.deepcopy(self.report)
            report['trials'][0][field]=0
            with self.subTest(field=field),self.assertRaises(AssertionError):verify(report)
        report=copy.deepcopy(self.report)
        report['trials'][0]['flows'][0]['sha256']='0'*64
        with self.assertRaises(AssertionError):verify(report)

    def test_reject_source_mismatch_and_dropped_receiver_bytes(self):
        report=copy.deepcopy(self.report)
        report['source_files']['src/main.rs']='0'*64
        with self.assertRaises(AssertionError):verify(report)
        report=copy.deepcopy(self.report)
        report['trials'][0]['receiver_traces'][0].pop()
        with self.assertRaises(AssertionError):verify(report)
