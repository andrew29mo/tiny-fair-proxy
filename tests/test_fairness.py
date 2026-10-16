"""Correctness of service shares under an explicitly shaped, saturated bottleneck.

Uses the same release executable and real-receiver workload as formal measurement.
Loose byte-window tolerances are contracts for this fixture, not performance gates.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from benchmark import run_trial


class LiveFairnessTests(unittest.TestCase):
    def test_tenant_weight_and_connection_count_in_both_directions(self):
        for direction in ['upload', 'download']:
            for weights in [[1,1], [1,3]]:
                with self.subTest(direction=direction, weights=weights):
                    t = run_trial('tenant_fair', weights, direction, 512*1024, 512*1024)
                    self.assertTrue(t['fairness_window_all_flows_active'])
                    self.assertLess(t['max_share_error'], .04)
                    # Receiver window can cross kernel/read boundaries; tolerate 64 KiB.
                    self.assertLessEqual(sum(t['receiver_window_bytes']), 512*1024 + 65536)
                    self.assertEqual(t['proxy_metrics']['completed'], 5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
