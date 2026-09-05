from __future__ import annotations

import os
import unittest

from tests.live_concurrency_verification import run_live_verification


@unittest.skipUnless(
    os.environ.get("RUN_LIVE_CONCURRENCY") == "1",
    "set RUN_LIVE_CONCURRENCY=1 to run real-network Atlas concurrency verification",
)
class LiveConcurrencyTests(unittest.TestCase):
    def test_real_concurrency_isolation_staleness_and_regression(self):
        run_live_verification()


if __name__ == "__main__":
    unittest.main()
