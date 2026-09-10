"""Opt-in evidence that a real page's meta description reaches the classifier.

This uses a real Lyfe Marketing page fetch and a deterministic provider double
that changes its classification only when the extracted description is present.
It avoids making an uncontrolled external LLM call while exercising the same
OpenAIClassifier request boundary used in production.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.discovery.classification import (
    CandidateForClassification,
    OpenAIClassifier,
    classify_candidates,
)
from backend.flask.discovery.normalization import extract_meta_description
from backend.flask.website_monitoring.service import fetch_page


REAL_URL = "https://www.lyfemarketing.com/website-design-services-for-small-businesses"


class _MetaAwareProvider:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def generate_json(self, prompt, *, instructions, response_format):
        payload = json.loads(prompt)
        self.calls.append(payload)
        candidate = payload["candidates"][0]
        has_service_signal = "services" in (candidate.get("meta_description") or "").lower()
        return {
            "classifications": [
                {
                    "url": candidate["url"],
                    "page_type": "SERVICES" if has_service_signal else "OTHER",
                    "discovery_status": "SUGGESTED"
                    if has_service_signal
                    else "DISCARDED",
                }
            ]
        }


def run_live_verification() -> None:
    response = fetch_page(REAL_URL)
    description = extract_meta_description(response.content)
    if response.http_status is None or not 200 <= response.http_status < 400:
        raise AssertionError(f"real page did not return a usable response: {response}")
    if not description:
        raise AssertionError("real page did not expose a meta description")

    without_meta_provider = _MetaAwareProvider()
    without_meta = classify_candidates(
        (CandidateForClassification(REAL_URL, REAL_URL),),
        OpenAIClassifier(provider=without_meta_provider),
    )[0]
    with_meta_provider = _MetaAwareProvider()
    with_meta = classify_candidates(
        (
            CandidateForClassification(
                REAL_URL,
                REAL_URL,
                meta_description=description,
            ),
        ),
        OpenAIClassifier(provider=with_meta_provider),
    )[0]

    print(f"url={REAL_URL}")
    print(f"http_status={response.http_status}")
    print(f"meta_description={description!r}")
    print(
        f"without_meta={without_meta.page_type}/{without_meta.discovery_status} "
        f"with_meta={with_meta.page_type}/{with_meta.discovery_status}"
    )
    print(
        "provider_input_meta_description="
        f"{with_meta_provider.calls[0]['candidates'][0]['meta_description']!r}"
    )


if __name__ == "__main__":
    run_live_verification()
