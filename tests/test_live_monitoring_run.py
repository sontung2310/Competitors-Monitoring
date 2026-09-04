from __future__ import annotations

import os
import unittest

from tests.live_monitoring_run_verification import run_live_verification


@unittest.skipUnless(
    os.environ.get("RUN_LIVE_MONITORING") == "1",
    "set RUN_LIVE_MONITORING=1 to run real-network Atlas monitoring verification",
)
class LiveMonitoringRunTests(unittest.TestCase):
    def test_lyfe_success_and_failure_lifecycle(self):
        run_live_verification()


if __name__ == "__main__":
    unittest.main()
