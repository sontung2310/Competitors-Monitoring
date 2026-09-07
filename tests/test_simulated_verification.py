from __future__ import annotations

import unittest

from backend.flask.website_monitoring.simulated_verification import (
    SimulatedVerificationError,
    simulate_product_mutation,
    simulate_blog_change,
    simulate_product_listing_change,
    simulate_text_change,
)


class _FakeProvider:
    def __init__(self, *, blog_output: str, product_plan: dict[str, object]):
        self.blog_output = blog_output
        self.product_plan = product_plan
        self.text_prompts: list[str] = []
        self.json_prompts: list[str] = []

    def generate(self, prompt, *, instructions, response_format=None):
        self.text_prompts.append(prompt)
        return self.blog_output

    def generate_json(self, prompt, *, instructions, response_format):
        self.json_prompts.append(prompt)
        return self.product_plan


class SimulatedVerificationTests(unittest.TestCase):
    def test_blog_simulation_uses_real_processor_and_emits_one_new_blog(self):
        raw = (
            "<html><body><main><h1>Latest marketing insights</h1>"
            "<article><h2>Existing post</h2><p>Existing post content.</p></article>"
            "</main></body></html>"
        )
        provider = _FakeProvider(
            blog_output=(
                "<article><h2>How Brands Can Grow in 2026</h2>"
                "<p>A plausible new editorial post with useful marketing guidance.</p>"
                "</article>"
            ),
            product_plan={},
        )

        result = simulate_blog_change(raw, provider)

        self.assertTrue(result.process_result.changed)
        self.assertEqual(len(result.process_result.change_events), 1)
        self.assertEqual(result.process_result.change_events[0]["change_type"], "NEW_BLOG")
        self.assertIn("How Brands Can Grow", result.mutated_content)
        self.assertEqual(len(provider.text_prompts), 1)

    def test_generic_text_simulation_reuses_text_blob_for_services(self):
        raw = (
            "<html><body><main><h1>Services</h1>"
            "<section><h2>Paid media</h2><p>Campaign strategy.</p></section>"
            "</main></body></html>"
        )
        provider = _FakeProvider(
            blog_output=(
                "<section><h2>Conversion-focused landing pages</h2>"
                "<p>A new service offering for growing brands.</p></section>"
            ),
            product_plan={},
        )

        result = simulate_text_change(raw, provider, page_type="SERVICES")

        self.assertEqual(result.page_type, "SERVICES")
        self.assertTrue(result.process_result.changed)
        self.assertEqual(
            result.process_result.change_events[0]["change_type"],
            "PAGE_UPDATE",
        )
        self.assertIn("Conversion-focused landing pages", result.mutated_content)

    def test_product_simulation_applies_llm_plan_in_code_and_emits_three_events(self):
        raw = """
        <ul>
          <li class="productListItem"><a class="itemImage" href="/product/one/1/">
            <span class="itemTitle">One Trainer</span><span class="itemPrice">Now $10.00</span>
          </a></li>
          <li class="productListItem"><a class="itemImage" href="/product/two/2/">
            <span class="itemTitle">Two Hoodie</span><span class="itemPrice">Now $20.00</span>
          </a></li>
          <li class="productListItem"><a class="itemImage" href="/product/three/3/">
            <span class="itemTitle">Three Cap</span><span class="itemPrice">Now $30.00</span>
          </a></li>
        </ul>
        """
        provider = _FakeProvider(
            blog_output="",
            product_plan={
                "new_product": {
                    "key": "/product/four/4",
                    "name": "Four Jacket",
                    "price": "40.00",
                },
                "removed_key": "/product/one/1",
                "price_change_key": "/product/two/2",
                "new_price": "18.00",
            },
        )

        result = simulate_product_listing_change(raw, provider)

        self.assertEqual(
            [event["change_type"] for event in result.events],
            ["NEW_PRODUCT", "PRODUCT_REMOVED", "PRICE_CHANGE"],
        )
        self.assertIn("Four Jacket", result.events[0]["summary"])
        self.assertIn("One Trainer", result.events[1]["summary"])
        self.assertIn("20.00 -> 18.00", result.events[2]["summary"])
        self.assertNotIn("/product/one/1", {product["key"] for product in result.mutated_products})
        self.assertEqual(len(provider.json_prompts), 1)
        self.assertIn('"key": "/product/one/1"', provider.json_prompts[0])

    def test_product_mutations_are_independently_reportable(self):
        raw = """
        <ul>
          <li class="productListItem"><a class="itemImage" href="/product/one/1/">
            <span class="itemTitle">One Trainer</span><span class="itemPrice">Now $10.00</span>
          </a></li>
          <li class="productListItem"><a class="itemImage" href="/product/two/2/">
            <span class="itemTitle">Two Hoodie</span><span class="itemPrice">Now $20.00</span>
          </a></li>
          <li class="productListItem"><a class="itemImage" href="/product/three/3/">
            <span class="itemTitle">Three Cap</span><span class="itemPrice">Now $30.00</span>
          </a></li>
        </ul>
        """
        plan = {
            "new_product": {
                "key": "/product/four/4",
                "name": "Four Jacket",
                "price": "40.00",
            },
            "removed_key": "/product/one/1",
            "price_change_key": "/product/two/2",
            "new_price": "18.00",
        }
        expected = {
            "NEW_PRODUCT": "Four Jacket",
            "PRODUCT_REMOVED": "One Trainer",
            "PRICE_CHANGE": "20.00 -> 18.00",
        }

        for mutation_type, expected_text in expected.items():
            result = simulate_product_mutation(
                raw,
                _FakeProvider(blog_output="", product_plan=plan),
                mutation_type=mutation_type,
            )
            self.assertEqual(len(result.events), 1)
            self.assertEqual(result.events[0]["change_type"], mutation_type)
            self.assertIn(expected_text, result.events[0]["summary"])
            self.assertEqual(result.mutation_type, mutation_type)

    def test_invalid_product_plan_is_rejected_before_any_persistence_boundary(self):
        raw = (
            '<li class="productListItem"><a class="itemImage" href="/product/one/1/">'
            '<span class="itemTitle">One</span><span class="itemPrice">Now $10.00</span>'
            "</a></li>"
            '<li class="productListItem"><a class="itemImage" href="/product/two/2/">'
            '<span class="itemTitle">Two</span><span class="itemPrice">Now $20.00</span>'
            "</a></li>"
        )
        provider = _FakeProvider(
            blog_output="",
            product_plan={
                "new_product": {"key": "/product/new", "name": "New", "price": "1.00"},
                "removed_key": "/product/missing",
                "price_change_key": "/product/one/1",
                "new_price": "9.00",
            },
        )

        with self.assertRaisesRegex(SimulatedVerificationError, "not in the real product sample"):
            simulate_product_listing_change(raw, provider)


if __name__ == "__main__":
    unittest.main()
