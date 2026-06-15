# FitFindr

A thrift-shopping assistant that takes a natural language query, searches a mock dataset of secondhand listings, suggests outfits using the user's wardrobe, and generates a shareable Instagram-style caption — all wired into a Gradio web UI.

---

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root with your Groq API key:

```
GROQ_API_KEY=your_key_here
```

Run the app:

```bash
python app.py
```

Then open the URL shown in your terminal (typically `http://127.0.0.1:7860`).

Run the test suite:

```bash
python -m pytest tests/ -v
```

---

## Tool Inventory

### Tool 1 — `search_listings`

**Purpose:** Searches the mock dataset of 40 thrift listings for items that match a free-text description, with optional size and price filters. No LLM is involved — this is pure Python keyword scoring.

**Inputs:**

| Parameter | Type | Description |
|---|---|---|
| `description` | `str` | Free-text keywords (e.g. `"vintage graphic tee"`). Matched case-insensitively against each listing's `title`, `description`, `category`, `style_tags`, and `colors` fields. |
| `size` | `str \| None` | Size string to filter by (e.g. `"M"`, `"US 8"`, `"W30"`). Applied as a case-insensitive substring match against the listing's `size` field, so `"M"` matches `"S/M"` and `"M/L"`. `None` skips size filtering. |
| `max_price` | `float \| None` | Price ceiling, inclusive. Only listings with `price <= max_price` are kept. `None` skips price filtering. |

**Output:** `list[dict]` — matching listing dicts sorted by relevance score, highest first. Each dict contains `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, and `platform`. Returns `[]` if nothing matches.

**Scoring logic:** For each keyword in `description`, the tool checks how many of the five searchable fields (`title`, `description`, `category`, `style_tags`, `colors`) contain that keyword as a substring, earning one point per field hit. This means an item where `"vintage"` appears in both `title` and `style_tags` scores higher than one where it only appears in `description`. Listings with a total score of zero are dropped.

---

### Tool 2 — `suggest_outfit`

**Purpose:** Calls the Groq LLM to suggest 1–2 complete outfits incorporating the thrifted item. Uses a different prompt depending on whether the user has a wardrobe on file.

**Inputs:**

| Parameter | Type | Description |
|---|---|---|
| `new_item` | `dict` | A listing dict from `search_listings()`. The prompt uses `title`, `description`, `colors`, and `style_tags`. |
| `wardrobe` | `dict` | A wardrobe dict with an `"items"` key containing a list of the user's existing pieces. Each piece has `name`, `category`, `colors`, `style_tags`, and an optional `notes` field. May be `{"items": []}` for a new user. |

**Output:** `str` — a non-empty string with outfit suggestions. If the wardrobe is populated, suggestions name specific pieces from the user's wardrobe by name. If the wardrobe is empty, the response gives general styling advice (what types of bottoms, layers, and shoes pair well, and what aesthetic the item suits).

**LLM details:** Uses `llama-3.1-8b-instant` via Groq, `max_tokens=350`, `temperature=0.7`.

---

### Tool 3 — `create_fit_card`

**Purpose:** Calls the Groq LLM to generate a 2–4 sentence casual Instagram/TikTok-style OOTD caption for the thrifted find. Temperature is set higher so the output sounds different each time.

**Inputs:**

| Parameter | Type | Description |
|---|---|---|
| `outfit` | `str` | The outfit suggestion string from `suggest_outfit()`. Used as the vibe and context for the caption. |
| `new_item` | `dict` | The listing dict. Used for `title` (item name), `price` (formatted as `$24.00`), `platform`, and `style_tags` (aesthetic cues). |

**Output:** `str` — a 2–4 sentence caption written in casual first-person. The item name, price, and platform each appear exactly once, woven in naturally. No hashtags, emojis, or bullet points. Returns an error message string (not an exception) if `outfit` is empty or whitespace-only.

**LLM details:** Uses `llama-3.1-8b-instant` via Groq, `max_tokens=150`, `temperature=0.9`.

---

## How the Planning Loop Works

`run_agent()` in `agent.py` runs a fixed seven-step linear sequence. There is no dynamic tool selection — the tools have a strict dependency chain (search must complete before outfit suggestion, which must complete before the fit card), so the order is hardcoded.

```
Step 1  Initialize a fresh session dict (_new_session)
Step 2  Parse the query with regex → {description, size, max_price}
Step 3  Call search_listings(description, size, max_price)
          └─ if results == [] → set session["error"], return early  ◄── BRANCH A
Step 4  Select the top result → session["selected_item"]
Step 5  Call suggest_outfit(selected_item, wardrobe)
          └─ internally branches on wardrobe["items"] == []          ◄── BRANCH B
Step 6  Call create_fit_card(outfit_suggestion, selected_item)
          └─ internally guards against empty outfit string            ◄── BRANCH C
Step 7  Return the completed session dict
```

**Query parsing** uses two compiled regexes:

- `_PRICE_RE` matches patterns like `"under $30"`, `"below $40"`, `"max $25"`, `"less than $10"`, `"< $5"`, and `"$30 or less"`. It anchors on a leading keyword rather than a bare `$` to avoid false matches on brand names or prices embedded in descriptions.
- `_SIZE_RE` matches `"size M"`, `"in size US 8"`, `"size W30"`, and standalone clothing-size tokens (`XS`, `S`, `M`, `L`, `XL`, `XXL`, `XXS`) with word boundaries.

After extracting price and size, the remaining text (with whitespace collapsed) becomes the `description` passed to `search_listings`.

**Branch A** is the only conditional in the main planning loop. If `search_listings` returns `[]`, the function sets `session["error"]` and returns immediately — `suggest_outfit` and `create_fit_card` are never called with empty input.

Branches B and C are internal to their respective tools, not in the planning loop.

---

## State Management

All state for a single interaction lives in the `session` dict created by `_new_session()`. Tools never communicate directly — each tool writes its result into the session, and the next step reads from it.

| Key | Written by | Read by | Contents |
|---|---|---|---|
| `query` | `_new_session` | Step 2 | Original user query string |
| `parsed` | Step 2 | Step 3 | `{"description": str, "size": str\|None, "max_price": float\|None}` |
| `search_results` | Step 3 | Steps 3 (branch check) and 4 | Full ranked list of matching listing dicts |
| `selected_item` | Step 4 | Steps 5 and 6 | The top-ranked listing dict |
| `wardrobe` | `_new_session` | Step 5 | Passed in by the caller; never modified |
| `outfit_suggestion` | Step 5 | Step 6 | Outfit suggestion string from `suggest_outfit()` |
| `fit_card` | Step 6 | `handle_query()` in `app.py` | Final caption string |
| `error` | Step 3 (Branch A) | `handle_query()` in `app.py` | Non-`None` signals early termination |

`app.py`'s `handle_query()` receives the returned session and checks `session["error"]` first. If set, the error message populates panel 1 and panels 2 and 3 return empty strings. Otherwise it formats `session["selected_item"]` into a multi-line listing card (title, price, size, condition, platform, description) and passes `session["outfit_suggestion"]` and `session["fit_card"]` to panels 2 and 3 directly.

---

## Error Handling Strategy

Each tool has a defined failure mode and a contract for how it signals failure — always as a return value, never as a raised exception.

### `search_listings` — no results

**Failure mode:** No listing in the dataset matches the combination of keywords, size, and price constraints.

**Tool behavior:** Returns `[]`. The entire function body is wrapped in `try/except Exception` so data-loading errors also return `[]` rather than crashing.

**Agent response:** `run_agent()` checks `if not session["search_results"]` immediately after the call and sets:
```
session["error"] = "No listings found matching your search. Try broader keywords or a higher price limit."
```
The function then returns without calling `suggest_outfit` or `create_fit_card`.

**Concrete example from testing:** `search_listings("designer ballgown", size="XXS", max_price=5.0)` returns `[]` — no listing costs under $5 while also fitting XXS. Verified in `test_impossible_query_returns_empty_list`.

**Edge case discovered during testing:** A gibberish query `"zxqwerty completely made up item 99999"` returned 5 results because `"made"` is a substring of `"handmade"` (in lst_023's description) and `"up"` appears in `"dressed up"` in several listings. This is correct behavior — substring scoring is intentionally broad. The test was updated to use pure-consonant tokens (`"zxqkwv bfplmqr vvwwqzx"`) that cannot substring-match any English word in the dataset.

---

### `suggest_outfit` — empty wardrobe

**Failure mode:** The user is new and has no wardrobe items (`wardrobe["items"] == []`).

**Tool behavior:** Detects the empty list before building the prompt and switches to a general-styling branch — asking the LLM what types of pieces pair well with the item and what aesthetic it suits, rather than referencing specific wardrobe pieces. Always returns a non-empty string.

**Concrete example from testing:** `suggest_outfit(graphic_tee, get_empty_wardrobe())` returns general advice about silhouettes and aesthetics without mentioning any of the 10 items in `example_wardrobe`. Verified in `test_empty_wardrobe_returns_nonempty_string` and `test_empty_wardrobe_does_not_mention_specific_wardrobe_pieces`.

**Additional guard:** The Groq call is wrapped in `try/except Exception`. On API failure the tool returns `"Could not generate outfit suggestion — try again shortly."` rather than propagating the error up to the agent.

---

### `create_fit_card` — empty outfit string

**Failure mode:** `outfit` is an empty string or contains only whitespace (which could happen if `suggest_outfit` returned its API-failure fallback and that string was passed through).

**Tool behavior:** The guard clause fires before the Groq client is initialized:
```python
if not outfit or not outfit.strip():
    return "Cannot create a fit card without an outfit suggestion."
```

**Concrete examples from testing:**
- `create_fit_card("", item)` → `"Cannot create a fit card without an outfit suggestion."` ✓
- `create_fit_card("   \t\n  ", item)` → `"Cannot create a fit card without an outfit suggestion."` ✓

Both verified in `test_empty_outfit_returns_error_string_not_exception` and `test_whitespace_only_outfit_returns_error_string`.

---

## Spec Reflection

### One way the planning document helped

Writing the error-handling table in `planning.md` before writing any code forced each tool's failure contract to be exact and testable before implementation began. For `create_fit_card`, the spec required returning the specific string `"Cannot create a fit card without an outfit suggestion."` — not just any truthy error value. Because that exact string was decided in advance in the planning doc, the pytest test could assert exact equality (`assert result == "Cannot create a fit card without an outfit suggestion."`) rather than a looser check like `assert "error" in result.lower()`. Without the spec, this precision wouldn't have existed before writing the test, and a weaker test would have passed even for incorrect behavior (like raising an exception that gets caught elsewhere).

### One way the implementation diverged from the spec

The spec described keyword scoring as "1 point per field the keyword appears in," implying word-level matching — checking whether a field *contains* this word as a whole token. The implementation uses Python's `in` operator on the lowercased field string (`kw in field`), which is substring matching. This means `"made"` matches `"handmade"`, `"tee"` matches `"tees"`, and `"cord"` would match `"corduroy"`.

The divergence was discovered during testing when a query containing the English word `"made"` returned 5 results instead of 0 (see the edge case in the `search_listings` error handling section above). The decision was to keep substring matching — it gives users more forgiving search behavior, and in a thrift-search context a user typing `"tee"` almost certainly wants `"tees"` to match too. The test was adjusted rather than the implementation, and the behavior is documented here.

---

## AI Usage

All implementation in this project was developed interactively with **Claude (claude-sonnet-4-6)** via Claude Code. The following two instances illustrate concretely what was given as input, what Claude produced, and what was changed before use.

---

### Instance 1 — `suggest_outfit` and the decommissioned model

**What I gave Claude as input:**
The Tool 2 spec from `planning.md` (the two-branch logic for empty vs. non-empty wardrobe, input parameter types, return value contract), the wardrobe item dict structure from `data/wardrobe_schema.json` (fields: `name`, `category`, `colors`, `style_tags`, `notes`), and the `_get_groq_client()` helper already present in `tools.py`.

**What Claude produced:**
A complete two-branch implementation that formatted each wardrobe item into a prompt line with name, colors, style tags, and notes, then called the Groq API with `model="llama3-8b-8192"`, `max_tokens=350`, `temperature=0.7`. The branching logic and prompt wording were correct.

**What I changed before using it:**
Running the function returned the fallback string `"Could not generate outfit suggestion — try again shortly."` for both branches. Removing the `try/except` to expose the real error revealed:

```
BadRequestError: The model `llama3-8b-8192` has been decommissioned and is no longer supported.
```

I checked Groq's deprecations page, confirmed that `llama-3.1-8b-instant` was the recommended replacement, verified it was available on my account with a quick one-line test call, and updated the `model=` argument. The rest of the generated implementation — the prompt structure, branching logic, fallback string, and `try/except` wrapper — was used as-is.

---

### Instance 2 — `test_tools.py` and the failing gibberish query

**What I gave Claude as input:**
The four required failure modes from the assignment spec, the tool signatures and docstrings (specifically the exact error string `"Cannot create a fit card without an outfit suggestion."`), and the wardrobe fixture structure from `utils/data_loader.py`.

**What Claude produced:**
16 pytest tests across three classes covering all required failure modes plus happy-path contracts. One of the tests, `test_no_results_is_list_not_exception`, used `"zxqwerty completely made up item 99999"` as the "impossible query" and asserted `len(result) == 0`.

**What I changed before using it:**
Running `pytest` showed that test failing: `AssertionError: assert 5 == 0`. The query contained the real English words `"made"` and `"up"`, which substring-matched `"handmade"` (in lst_023) and `"dressed up"` (in several listings) respectively. The implementation was correct — substring scoring is intentionally broad — so the test assumption was wrong, not the code.

I changed the query to `"zxqkwv bfplmqr vvwwqzx"` (pure consonant-cluster tokens with no plausible English substrings) and added a comment explaining the constraint. All 16 tests then passed. The failure also surfaced a real documentation gap: the substring-matching behavior wasn't mentioned anywhere, which is why it now appears in both the error handling section of this README and in the spec reflection above.
