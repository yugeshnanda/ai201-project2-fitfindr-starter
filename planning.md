# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Loads all 40 listings from `data/listings.json` via `load_listings()`, filters them by optional size and price constraints, then scores each remaining listing by keyword overlap with the user's description and returns the matches sorted best-first. No LLM is involved — this is pure Python string matching.

**Input parameters:**
- `description` (str): Free-text keywords from the user's query (e.g., `"vintage graphic tee"`). Matched case-insensitively against each listing's `title`, `description`, `category`, `style_tags` (list), and `colors` (list).
- `size` (str | None): Size string to filter by (e.g., `"M"`, `"S/M"`, `"US 8"`). If provided, only listings whose `size` field contains this string (case-insensitive substring match) are kept. `None` skips size filtering entirely.
- `max_price` (float | None): Maximum price, inclusive. Only listings with `price <= max_price` are kept. `None` skips price filtering.

**What it returns:**
A list of listing dicts sorted by descending relevance score (highest overlap first). Each dict has the fields: `id` (str), `title` (str), `description` (str), `category` (str), `style_tags` (list[str]), `size` (str), `condition` (str — `"excellent"`, `"good"`, or `"fair"`), `price` (float), `colors` (list[str]), `brand` (str or None), `platform` (str — `"depop"`, `"thredUp"`, or `"poshmark"`). Listings with a score of 0 (zero keyword matches) are excluded. Returns `[]` if nothing matches.

**What happens if it fails or returns nothing:**
Returns an empty list — never raises. The planning loop in `run_agent()` checks for an empty list after this call and sets `session["error"]` to a user-facing message like `"No listings found matching your search. Try broader keywords or a higher price limit."` before returning early, skipping all downstream tools.

---

### Tool 2: suggest_outfit

**What it does:**
Calls the Groq LLM to suggest 1–2 complete outfits that incorporate the thrifted item being considered. If the wardrobe is non-empty, the suggestions reference specific named pieces from the user's wardrobe items. If the wardrobe is empty, the LLM offers general styling advice for the item instead.

**Input parameters:**
- `new_item` (dict): A single listing dict from `search_listings()` — the item the user is considering buying. Relevant fields used in the prompt: `title`, `description`, `category`, `style_tags`, `colors`, `price`, `platform`.
- `wardrobe` (dict): A wardrobe dict with an `"items"` key containing a list of wardrobe item dicts. Each wardrobe item has: `id`, `name`, `category`, `colors` (list), `style_tags` (list), `notes` (str or None). May be `{"items": []}` for a new user.

**What it returns:**
A non-empty string containing 1–2 outfit suggestions. When wardrobe items are present, suggestions name specific pieces (e.g., "Pair with your baggy straight-leg jeans and chunky white sneakers"). When the wardrobe is empty, the response describes what types of pieces would pair well and what aesthetic the item suits.

**What happens if it fails or returns nothing:**
If `wardrobe["items"]` is empty, the tool does not error — it switches to a general-styling prompt instead of a pairing prompt. The Groq call is wrapped in a try/except; on API failure, returns a fallback string like `"Could not generate outfit suggestion — try again shortly."` rather than raising.

---

### Tool 3: create_fit_card

**What it does:**
Calls the Groq LLM at higher temperature to generate a 2–4 sentence casual, shareable caption in the style of an Instagram or TikTok OOTD post. The caption names the item, its price, and the platform it was found on, and captures the outfit vibe described in the `outfit` string.

**Input parameters:**
- `outfit` (str): The outfit suggestion string returned by `suggest_outfit()`. Used as the core context for the caption's vibe and specific pieces.
- `new_item` (dict): The listing dict for the thrifted item. Fields used: `title` (item name), `price` (float), `platform` (str), `style_tags` (for tone/aesthetic cues).

**What it returns:**
A 2–4 sentence string written in a casual first-person voice — not a product description. Mentions the item name, price, and platform naturally once each. Sounds distinct for different inputs because temperature is set higher (e.g., 0.9–1.0).

**What happens if it fails or returns nothing:**
If `outfit` is empty or whitespace-only, returns the error string `"Cannot create a fit card without an outfit suggestion."` without calling the LLM. On Groq API failure, returns `"Could not generate fit card — try again shortly."` rather than raising.

---

### Additional Tools (if any)

None beyond the required three.

---

## Planning Loop

**How does your agent decide which tool to call next?**

The loop is a fixed linear sequence — not a dynamic planner. There is no LLM deciding which tool to call; the sequence is hardcoded because the tools have a strict dependency chain: search must precede outfit suggestion, which must precede the fit card. The loop uses the session dict as a shared state store and has two early-exit branches.

```
Step 1 — Initialize session
    _new_session(query, wardrobe) → session dict with all fields set to None/[]

Step 2 — Parse the query
    Use regex to extract:
      - max_price: look for patterns like "under $30", "< $40", "max $25", "$30 or less"
      - size: look for "size M", "size XL", standalone size tokens (S, M, L, XL, XS, XXS,
              W28, W30, US 7, US 8, etc.)
      - description: everything remaining after stripping price/size tokens
    Store as session["parsed"] = {"description": ..., "size": ..., "max_price": ...}

Step 3 — Search listings
    Call search_listings(description, size, max_price)
    Store result in session["search_results"]

    BRANCH A — no results:
        session["error"] = "No listings found matching your search. Try broader keywords or a higher price limit."
        return session   ← early exit, outfit/fit_card stay None

Step 4 — Select item
    session["selected_item"] = session["search_results"][0]   (top-scored result)

Step 5 — Suggest outfit
    Call suggest_outfit(session["selected_item"], session["wardrobe"])
    Store result in session["outfit_suggestion"]

Step 6 — Create fit card
    Call create_fit_card(session["outfit_suggestion"], session["selected_item"])
    Store result in session["fit_card"]

Step 7 — Return session
    return session   ← session["error"] is None on success
```

The loop knows it is done after Step 7. There is no iteration or re-planning.

---

## State Management

**How does information from one tool get passed to the next?**

All state lives in a single `session` dict initialized by `_new_session()`. Each step reads from and writes to that dict; no data is passed between tools directly as function arguments other than what the session provides.

| Session key | Written by | Read by | Purpose |
|---|---|---|---|
| `query` | `_new_session` | Step 2 (parse) | Original user query string |
| `parsed` | Step 2 | Step 3 (search) | `{description, size, max_price}` extracted from query |
| `search_results` | Step 3 | Steps 3 branch check, Step 4 | Full list of matching listing dicts |
| `selected_item` | Step 4 | Steps 5 and 6 | The top-ranked listing dict |
| `wardrobe` | `_new_session` | Step 5 | Passed in by caller; never modified |
| `outfit_suggestion` | Step 5 | Step 6 | Outfit suggestion string from suggest_outfit() |
| `fit_card` | Step 6 | Caller (app.py) | Final caption string |
| `error` | Step 3 (branch A) | Caller (app.py) | Non-None signals early termination |

`app.py`'s `handle_query()` receives the returned session and reads `session["error"]`, `session["selected_item"]`, `session["outfit_suggestion"]`, and `session["fit_card"]` to populate the three Gradio output panels.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| `search_listings` | No listings match the query after filtering by price, size, and keyword scoring | Sets `session["error"]` to `"No listings found matching your search. Try broader keywords or a higher price limit."` and returns the session immediately; `outfit_suggestion` and `fit_card` remain `None` |
| `suggest_outfit` | `wardrobe["items"]` is empty (new user with no wardrobe data) | Switches prompt to ask for general styling advice rather than specific pairings; never errors or returns empty string |
| `create_fit_card` | `outfit` argument is empty or whitespace-only (suggest_outfit returned nothing useful) | Returns the literal string `"Cannot create a fit card without an outfit suggestion."` without calling the LLM |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          User (Gradio UI)                           │
│   query: "vintage graphic tee under $30"                            │
│   wardrobe_choice: "Example wardrobe"                               │
└────────────────────────────┬────────────────────────────────────────┘
                             │ handle_query()
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        app.py / handle_query                        │
│  • guard empty query → return error in panel 1                      │
│  • select wardrobe (get_example_wardrobe or get_empty_wardrobe)     │
│  • call run_agent(query, wardrobe)                                   │
│  • map session fields to 3 Gradio output panels                     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     agent.py / run_agent()                          │
│                   (linear planning loop)                            │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  session = _new_session(query, wardrobe)                    │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             │                                       │
│  ┌──────────────────────────▼──────────────────────────────────┐   │
│  │  Step 2: Parse query (regex)                                │   │
│  │  → session["parsed"] = {description, size, max_price}       │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             │                                       │
│  ┌──────────────────────────▼──────────────────────────────────┐   │
│  │  Step 3: search_listings(description, size, max_price)      │◄──┼── Tool 1
│  │  → session["search_results"]                                │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             │                                       │
│               ┌─────────────┴──────────────┐                       │
│         empty │                            │ results found          │
│               ▼                            ▼                        │
│  ┌────────────────────┐   ┌────────────────────────────────────┐   │
│  │ session["error"]   │   │ Step 4: select top result          │   │
│  │ = "No listings…"   │   │ → session["selected_item"]         │   │
│  │ return session     │   └───────────────┬────────────────────┘   │
│  └────────────────────┘                   │                        │
│                             ┌─────────────┘                        │
│  ┌──────────────────────────▼──────────────────────────────────┐   │
│  │  Step 5: suggest_outfit(selected_item, wardrobe)            │◄──┼── Tool 2
│  │  → session["outfit_suggestion"]                             │   │   (Groq LLM)
│  │                                                             │   │
│  │  wardrobe empty? → general styling prompt                   │   │
│  │  wardrobe present? → specific pairing prompt                │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             │                                       │
│  ┌──────────────────────────▼──────────────────────────────────┐   │
│  │  Step 6: create_fit_card(outfit_suggestion, selected_item)  │◄──┼── Tool 3
│  │  → session["fit_card"]                                      │   │   (Groq LLM)
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             │                                       │
│  ┌──────────────────────────▼──────────────────────────────────┐   │
│  │  Step 7: return session                                     │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
  [Panel 1]           [Panel 2]           [Panel 3]
  Top listing         Outfit idea         Fit card
  found               (outfit_            (fit_card)
  (selected_item      suggestion)
   formatted)
```

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

**Tool 1 — `search_listings`:**
I will give Claude the Tool 1 spec from this document (inputs, return type, scoring logic, size/price filter rules) plus the exact listing dict structure from `data/listings.json` (fields: title, description, category, style_tags as list, colors as list, size as string, price as float) and the `load_listings()` function signature from `utils/data_loader.py`. I will ask Claude to implement `search_listings()` in `tools.py` using only the Python standard library (no LLM). I will verify by running three manual tests: (1) `search_listings("vintage graphic tee")` should return lst_006 and lst_033 near the top; (2) `search_listings("track jacket", size="M")` should include lst_004 and exclude size-L results; (3) `search_listings("designer ballgown", max_price=5.0)` should return `[]`.

**Tool 2 — `suggest_outfit`:**
I will give Claude the Tool 2 spec, the wardrobe dict structure from `data/wardrobe_schema.json` (fields: items list with name, category, colors, style_tags, notes), the `_get_groq_client()` helper already in `tools.py`, and the two-branch logic (empty vs. non-empty wardrobe). I will ask Claude to implement `suggest_outfit()` using a Groq chat completion call. I will verify by calling it twice: once with `get_example_wardrobe()` (should mention specific pieces like the baggy jeans or white sneakers) and once with `get_empty_wardrobe()` (should give general styling advice without referencing specific wardrobe items).

**Tool 3 — `create_fit_card`:**
I will give Claude the Tool 3 spec including the guard clause for empty outfit, the caption style guidelines (casual first-person, mentions item name/price/platform once each, specific vibe language, higher temperature), and the `_get_groq_client()` helper. I will ask Claude to implement `create_fit_card()`. I will verify by calling it with a real outfit string and lst_006's dict, checking that the output is 2–4 sentences, reads like an OOTD post, and naturally includes the title, `$24.00`, and `depop`.

**Milestone 4 — Planning loop and state management:**

**`run_agent()` in `agent.py`:**
I will give Claude the Planning Loop and State Management sections of this document, the `_new_session()` dict structure already in `agent.py`, the three tool signatures, and the exact field names the session dict uses. I will ask Claude to implement `run_agent()` including the regex-based query parser (price pattern `r'\$(\d+(?:\.\d+)?)'` with contextual words like "under", "max"; size pattern matching standalone size tokens). I will verify using the two CLI test cases already in `agent.py`'s `__main__` block: the happy path with `"vintage graphic tee under $30"` should produce a non-None `fit_card`, and the no-results path with `"designer ballgown size XXS under $5"` should produce a non-None `error`.

**`handle_query()` in `app.py`:**
I will give Claude the `handle_query()` docstring, the Gradio output tuple spec `(listing_text, outfit_suggestion, fit_card)`, and the session field names. I will ask Claude to implement it with the empty-query guard, wardrobe selection branch, error-path return, and a formatted listing_text string (e.g., title, price, size, platform, condition on separate lines). I will verify by running `python app.py`, submitting the example queries in the UI, and confirming all three panels populate correctly for the happy path and that the error panel populates alone for the no-results query.

---

## A Complete Interaction (Step by Step)

**Example user query:** `"vintage graphic tee under $30"`

**Step 1: Initialize session**
`run_agent()` calls `_new_session("vintage graphic tee under $30", example_wardrobe)`. The session dict is created with `query = "vintage graphic tee under $30"`, `parsed = {}`, `search_results = []`, `selected_item = None`, `wardrobe = {items: [10 wardrobe items]}`, `outfit_suggestion = None`, `fit_card = None`, `error = None`.

**Step 2: Parse the query**
Regex finds `$30` with the word `"under"` immediately before it → `max_price = 30.0`. No size token is found (no "size M", no standalone "S/M" etc.) → `size = None`. Remaining text after stripping the price phrase: `"vintage graphic tee"` → `description = "vintage graphic tee"`. Session updated: `session["parsed"] = {"description": "vintage graphic tee", "size": None, "max_price": 30.0}`.

**Step 3: Call `search_listings("vintage graphic tee", size=None, max_price=30.0)`**

Price filter (≤ $30.00) keeps: lst_002 ($18), lst_003 ($22), lst_005 ($32 — excluded), lst_006 ($24), lst_011 ($27), lst_012 ($20), lst_013 ($30), lst_014 ($12), lst_015 ($26), lst_016 ($24), lst_017 ($15), lst_020 ($16), lst_021 ($29), lst_023 ($22), lst_024 ($18), lst_026 ($14), lst_027 ($21), lst_030 ($25), lst_033 ($19), lst_034 ($14), lst_035 ($20), lst_040 ($17).

Keyword scoring against `["vintage", "graphic", "tee"]`:
- lst_006 *Graphic Tee — 2003 Tour Bootleg Style*: matches `"graphic tee"` in title (×2), `"graphic tee"` in style_tags (×2), `"vintage"` in style_tags (×1) → score 5
- lst_033 *Vintage Band Tee — Faded Grey*: matches `"vintage"` in title and style_tags (×2), `"graphic tee"` in style_tags (×1), `"band tee"` partially (×1) → score ~4
- lst_002 *Y2K Baby Tee — Butterfly Print*: matches `"graphic tee"` in style_tags (×1), `"vintage"` in style_tags (×1) → score ~2
- lst_015 *Vintage Graphic Hoodie*: matches `"vintage"` (×2), `"graphic"` (×2) → score ~4

Top results after sorting: lst_006 (score 5) is first, lst_033 and lst_015 follow. `session["search_results"]` = ranked list of ~10 matching listings.

**Step 4: Select item**
`session["selected_item"] = session["search_results"][0]` → lst_006:
```
{
  "id": "lst_006",
  "title": "Graphic Tee — 2003 Tour Bootleg Style",
  "description": "Vintage-style bootleg tee with faded graphic. Slightly boxy fit. 100% cotton, soft and worn-in.",
  "category": "tops",
  "style_tags": ["graphic tee", "vintage", "grunge", "streetwear", "band tee"],
  "size": "L",
  "condition": "good",
  "price": 24.0,
  "colors": ["black"],
  "brand": null,
  "platform": "depop"
}
```

**Step 5: Call `suggest_outfit(lst_006, example_wardrobe)`**
Wardrobe is non-empty (10 items), so the LLM receives a prompt like:

> "The user is considering buying this thrifted item: Graphic Tee — 2003 Tour Bootleg Style. It's a vintage-style bootleg tee, slightly boxy, 100% cotton, black. Style tags: graphic tee, vintage, grunge, streetwear, band tee. From the following wardrobe, suggest 1–2 complete outfits that incorporate this tee: [baggy straight-leg jeans dark wash / wide-leg khaki trousers / white ribbed tank / oversized grey crewneck / black cropped zip hoodie / vintage black denim jacket / chunky white sneakers / black combat boots / brown leather belt / black crossbody bag]."

LLM returns something like: "Outfit 1: Tuck the graphic tee into your baggy straight-leg dark wash jeans, add your black combat boots and the brown leather belt for a grunge-streetwear look. Throw your vintage black denim jacket on top if it's cool out. Outfit 2: Style it untucked over your wide-leg khaki trousers with your chunky white sneakers and the black crossbody bag for an easy, relaxed daytime fit."

`session["outfit_suggestion"]` is set to this string.

**Step 6: Call `create_fit_card(outfit_suggestion, lst_006)`**
Groq LLM is called at temperature ~0.9 with a prompt asking for a 2–4 sentence casual OOTD caption incorporating the outfit description, mentioning the item name, its $24 price, and that it was found on depop.

LLM returns something like: "thrifted this 2003 bootleg tee on depop for $24 and it's already doing the most. tucked into my baggy dark wash jeans with combat boots — full grunge-streetwear moment. black denim jacket on top when the sun goes down. this is the find of the month fr."

`session["fit_card"]` is set to this string.

**Step 7: Return session**
`session["error"]` is `None`. All output fields are populated.

**Final output to user (in Gradio UI):**

- **Panel 1 — Top listing found:**
  ```
  Graphic Tee — 2003 Tour Bootleg Style
  Price: $24.00 | Size: L | Condition: good
  Platform: depop
  "Vintage-style bootleg tee with faded graphic. Slightly boxy fit. 100% cotton, soft and worn-in."
  ```

- **Panel 2 — Outfit idea:**
  Outfit 1: Tuck the graphic tee into your baggy straight-leg dark wash jeans, add your black combat boots and the brown leather belt for a grunge-streetwear look. Throw your vintage black denim jacket on top if it's cool out. Outfit 2: Style it untucked over your wide-leg khaki trousers with your chunky white sneakers and the black crossbody bag for an easy, relaxed daytime fit.

- **Panel 3 — Your fit card:**
  thrifted this 2003 bootleg tee on depop for $24 and it's already doing the most. tucked into my baggy dark wash jeans with combat boots — full grunge-streetwear moment. black denim jacket on top when the sun goes down. this is the find of the month fr.
