"""
tests/test_tools.py

Pytest tests for the three FitFindr tools.

Each required failure mode has its own test. Additional tests cover
the happy-path contract so regressions in normal behaviour also surface.

LLM-backed tests (suggest_outfit, create_fit_card) make real Groq calls —
they verify the contract (non-empty string, correct error string) rather
than the exact wording of the response.
"""

import pytest

from tools import create_fit_card, search_listings, suggest_outfit
from utils.data_loader import get_empty_wardrobe, get_example_wardrobe


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def graphic_tee():
    """The top result for 'vintage graphic tee' — used across multiple tests."""
    results = search_listings("vintage graphic tee")
    assert results, "fixture: expected at least one result for 'vintage graphic tee'"
    return results[0]


@pytest.fixture
def outfit_suggestion(graphic_tee):
    """A real suggest_outfit response — feeds into create_fit_card tests."""
    return suggest_outfit(graphic_tee, get_example_wardrobe())


# ── search_listings ───────────────────────────────────────────────────────────

class TestSearchListings:

    def test_impossible_query_returns_empty_list(self):
        """Failure mode: nothing matches — must return [] not raise."""
        result = search_listings("designer ballgown", size="XXS", max_price=5.0)
        assert result == []

    def test_no_results_is_list_not_exception(self):
        """Returning [] (not raising) is part of the contract.

        Uses pure-gibberish tokens (no real English substrings) so that
        substring scoring cannot accidentally match any listing field.
        """
        result = search_listings("zxqkwv bfplmqr vvwwqzx")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_max_price_filter_respected(self):
        """Every returned item must have price <= max_price."""
        max_price = 25.0
        results = search_listings("vintage", max_price=max_price)
        assert results, "expected results for 'vintage' under $25"
        for item in results:
            assert item["price"] <= max_price, (
                f"{item['title']} costs ${item['price']} but max_price={max_price}"
            )

    def test_size_filter_is_case_insensitive_substring(self):
        """'M' should match listings sized 'M', 'S/M', 'M/L' etc."""
        results = search_listings("jacket", size="M")
        assert results, "expected at least one jacket in size M"
        for item in results:
            assert "m" in item["size"].lower(), (
                f"{item['title']} has size '{item['size']}' which doesn't contain 'M'"
            )

    def test_results_are_sorted_best_match_first(self):
        """A listing whose title contains all keywords should rank above one that matches fewer."""
        results = search_listings("graphic tee")
        assert results, "expected results for 'graphic tee'"
        top = results[0]
        assert "graphic" in top["title"].lower() or "graphic" in " ".join(top["style_tags"]).lower()

    def test_no_price_filter_returns_results(self):
        """Omitting max_price should not silently drop everything."""
        results = search_listings("vintage")
        assert len(results) > 0

    def test_returns_list_of_dicts_with_required_fields(self):
        """Each result must have the fields the rest of the agent depends on."""
        required = {"id", "title", "description", "price", "size", "platform", "style_tags"}
        results = search_listings("denim")
        assert results
        for item in results:
            missing = required - item.keys()
            assert not missing, f"{item.get('id')} is missing fields: {missing}"


# ── suggest_outfit ────────────────────────────────────────────────────────────

class TestSuggestOutfit:

    def test_empty_wardrobe_returns_nonempty_string(self, graphic_tee):
        """Failure mode: empty wardrobe — must return general styling advice, not ''."""
        result = suggest_outfit(graphic_tee, get_empty_wardrobe())
        assert isinstance(result, str)
        assert result.strip(), "suggest_outfit returned an empty string for an empty wardrobe"

    def test_empty_wardrobe_does_not_mention_specific_wardrobe_pieces(self, graphic_tee):
        """General-styling path should not hallucinate named wardrobe items."""
        result = suggest_outfit(graphic_tee, get_empty_wardrobe())
        wardrobe_names = [item["name"] for item in get_example_wardrobe()["items"]]
        for name in wardrobe_names:
            assert name not in result, (
                f"Empty-wardrobe path mentioned '{name}' — looks like wrong prompt branch"
            )

    def test_nonempty_wardrobe_returns_nonempty_string(self, graphic_tee):
        """Happy path: should always return a non-empty string."""
        result = suggest_outfit(graphic_tee, get_example_wardrobe())
        assert isinstance(result, str)
        assert result.strip()

    def test_nonempty_wardrobe_references_wardrobe_items(self, graphic_tee):
        """Specific-pairing path should name at least one item from the wardrobe."""
        result = suggest_outfit(graphic_tee, get_example_wardrobe())
        wardrobe_names = [item["name"] for item in get_example_wardrobe()["items"]]
        # Extract a short keyword per item that's unlikely to appear by coincidence
        keywords = [name.split(",")[0].split("—")[0].strip().lower() for name in wardrobe_names]
        assert any(kw in result.lower() for kw in keywords), (
            "suggest_outfit with a populated wardrobe didn't mention any wardrobe pieces"
        )


# ── create_fit_card ───────────────────────────────────────────────────────────

class TestCreateFitCard:

    def test_empty_outfit_returns_error_string_not_exception(self, graphic_tee):
        """Failure mode: empty outfit — must return an error string, never raise."""
        result = create_fit_card("", graphic_tee)
        assert isinstance(result, str)
        assert result == "Cannot create a fit card without an outfit suggestion."

    def test_whitespace_only_outfit_returns_error_string(self, graphic_tee):
        """Whitespace-only outfit is treated the same as empty."""
        result = create_fit_card("   \t\n  ", graphic_tee)
        assert isinstance(result, str)
        assert result == "Cannot create a fit card without an outfit suggestion."

    def test_valid_input_returns_nonempty_string(self, graphic_tee, outfit_suggestion):
        """Happy path: should always return a non-empty string."""
        result = create_fit_card(outfit_suggestion, graphic_tee)
        assert isinstance(result, str)
        assert result.strip()

    def test_caption_mentions_platform(self, graphic_tee, outfit_suggestion):
        """The platform (e.g. 'depop') should appear in the caption."""
        result = create_fit_card(outfit_suggestion, graphic_tee)
        assert graphic_tee["platform"].lower() in result.lower(), (
            f"Platform '{graphic_tee['platform']}' not found in fit card"
        )

    def test_caption_mentions_price(self, graphic_tee, outfit_suggestion):
        """The item price should appear in the caption."""
        result = create_fit_card(outfit_suggestion, graphic_tee)
        price_str = str(int(graphic_tee["price"]))  # "24" matches "$24" or "$24.00"
        assert price_str in result, (
            f"Price '${graphic_tee['price']}' not found in fit card"
        )
