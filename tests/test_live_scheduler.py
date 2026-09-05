import os
import unittest


@unittest.skipUnless(
    os.environ.get("RUN_LIVE_SCHEDULER") == "1",
    "set RUN_LIVE_SCHEDULER=1 for Atlas-backed scheduler verification",
)
class LiveSchedulerVerificationTests(unittest.TestCase):
    def test_live_scheduler_verification(self):
        from tests.live_scheduler_verification import run_live_verification

        report = run_live_verification()
        self.assertEqual(report["database"], "competitors_monitoring_test")
