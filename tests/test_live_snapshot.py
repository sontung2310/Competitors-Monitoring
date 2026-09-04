from __future__ import annotations

import os
import unittest

from tests.live_snapshot_verification import run_live_verification


@unittest.skipUnless(
    os.environ.get("RUN_LIVE_SNAPSHOT") == "1",
    "set RUN_LIVE_SNAPSHOT=1 to run real-network Atlas snapshot verification",
)
class LiveSnapshotTests(unittest.TestCase):
    def test_active_targets_create_persisted_snapshots(self):
        run_live_verification()


if __name__ == "__main__":
    unittest.main()
