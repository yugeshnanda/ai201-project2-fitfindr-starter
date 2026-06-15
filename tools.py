"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    try:
        listings = load_listings()
    except Exception:
        return []

    if max_price is not None:
        listings = [l for l in listings if l["price"] <= max_price]

    if size is not None:
        size_lower = size.lower()
        listings = [l for l in listings if size_lower in l.get("size", "").lower()]

    keywords = [kw.lower() for kw in description.split() if kw]
    if not keywords:
        return listings

    scored = []
    for listing in listings:
        # Each keyword earns 1 point per field it appears in, so items where
        # the keyword shows up in both title and style_tags rank higher.
        searchable_fields = [
            listing.get("title", "").lower(),
            listing.get("description", "").lower(),
            " ".join(listing.get("style_tags", [])).lower(),
            listing.get("category", "").lower(),
            " ".join(listing.get("colors", [])).lower(),
        ]
        score = sum(
            1 for kw in keywords for field in searchable_fields if kw in field
        )
        if score > 0:
            scored.append((score, listing))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    try:
        client = _get_groq_client()
        items = wardrobe.get("items", [])

        item_summary = (
            f"{new_item.get('title', 'Unknown item')} — "
            f"{new_item.get('description', '')} "
            f"Colors: {', '.join(new_item.get('colors', []))}. "
            f"Style: {', '.join(new_item.get('style_tags', []))}."
        )

        if not items:
            prompt = (
                f"A user is thinking about buying this thrifted piece:\n{item_summary}\n\n"
                "They haven't shared their wardrobe yet. Give them 1–2 general styling ideas: "
                "what types of pieces (bottoms, layers, shoes) pair well with it, "
                "what aesthetic or occasion it suits, and what vibe to go for. "
                "Be specific about silhouettes and colors — not vague advice."
            )
        else:
            wardrobe_lines = []
            for w in items:
                name = w.get("name", "Unknown piece")
                tags = ", ".join(w.get("style_tags", []))
                colors = ", ".join(w.get("colors", []))
                notes = w.get("notes")
                line = f"- {name} (colors: {colors}; style: {tags})"
                if notes:
                    line += f" — {notes}"
                wardrobe_lines.append(line)

            prompt = (
                f"A user is thinking about buying this thrifted piece:\n{item_summary}\n\n"
                f"Their current wardrobe:\n" + "\n".join(wardrobe_lines) + "\n\n"
                "Suggest 1–2 complete outfits that pair the new item with specific named pieces "
                "from the wardrobe above. Call each piece by name. Be specific about the vibe, "
                "silhouette, and occasion for each outfit. Keep it concise."
            )

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=350,
            temperature=0.7,
        )
        result = response.choices[0].message.content.strip()
        return result or "No outfit suggestion could be generated — try again."

    except Exception:
        return "Could not generate outfit suggestion — try again shortly."


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    if not outfit or not outfit.strip():
        return "Cannot create a fit card without an outfit suggestion."

    try:
        client = _get_groq_client()

        title = new_item.get("title", "this thrifted find")
        price = new_item.get("price", "")
        platform = new_item.get("platform", "a thrift app")
        style_tags = ", ".join(new_item.get("style_tags", []))

        price_str = f"${price:.2f}" if isinstance(price, (int, float)) else str(price)

        prompt = (
            f"Write a 2–4 sentence Instagram caption for this thrifted outfit.\n\n"
            f"Item: {title}\n"
            f"Price: {price_str}\n"
            f"Found on: {platform}\n"
            f"Style tags: {style_tags}\n"
            f"Outfit: {outfit}\n\n"
            "Rules:\n"
            "- Write in casual first-person, like a real OOTD post — not a product description\n"
            "- Mention the item name, price, and platform exactly once each, woven in naturally\n"
            "- Name the specific vibe or aesthetic (e.g. grunge-streetwear, dark academia, y2k)\n"
            "- No hashtags, no emojis, no bullet points — just the caption text\n"
            "- 2–4 sentences only"
        )

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.9,
        )
        result = response.choices[0].message.content.strip()
        return result or "Could not generate fit card — try again shortly."

    except Exception:
        return "Could not generate fit card — try again shortly."
