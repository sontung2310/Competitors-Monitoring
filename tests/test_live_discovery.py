from __future__ import annotations

import os
import unittest

from tests.live_discovery_verification import run_live_verification


@unittest.skipUnless(
    os.environ.get("RUN_LIVE_DISCOVERY") == "1",
    "set RUN_LIVE_DISCOVERY=1 to run real-network Layer 1 verification",
)
class LiveDiscoveryTests(unittest.TestCase):
    def test_all_acceptance_sites(self):
        run_live_verification()


if __name__ == "__main__":
    unittest.main()
