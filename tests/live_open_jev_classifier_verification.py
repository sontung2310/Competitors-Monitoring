"""Opt-in smoke verification for a running Open-Jev HTTP service.

Run from the repository root with the Flask environment loaded:

    RUN_LIVE_OPEN_JEV=1 python -u tests/live_open_jev_classifier_verification.py

The script intentionally exercises the classifier adapter only. It does not
install Open-Jev or any model dependencies in the Flask environment.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.discovery.classification import (
    CandidateForClassification,
    OpenJevClassifier,
)


def main() -> None:
    if os.environ.get("RUN_LIVE_OPEN_JEV") != "1":
        raise SystemExit(
            "Refusing live Open-Jev verification; set RUN_LIVE_OPEN_JEV=1"
        )

    candidate = CandidateForClassification(
        raw_url="https://example.com/opaque-discovery-candidate",
        url="https://example.com/opaque-discovery-candidate",
        title="Opaque discovery candidate",
        meta_description="A representative unresolved candidate for classifier verification.",
        sources=("SITEMAP", "LINKS"),
    )
    result = OpenJevClassifier.from_env().classify((candidate,))[0]
    if result.classification_method != "JEV":
        raise RuntimeError(f"unexpected classification method: {result}")
    if result.page_type not in {
        "BLOG",
        "NEWS",
        "PRICING",
        "PRODUCTS",
        "SERVICES",
        "PRESS",
        "OTHER",
    }:
        raise RuntimeError(f"unexpected page type: {result.page_type}")
    if result.discovery_status not in {"SUGGESTED", "DISCARDED"}:
        raise RuntimeError(f"unexpected discovery status: {result.discovery_status}")

    print(
        json.dumps(
            {
                "url": result.url,
                "page_type": result.page_type,
                "discovery_status": result.discovery_status,
                "classification_method": result.classification_method,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
