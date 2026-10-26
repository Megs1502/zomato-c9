# Evaluation: Restaurant Recommendation System

How to judge the build in [implementation-plan.md](implementation-plan.md). Case IDs point at [edge-case.md](edge-case.md).

Two scores are recorded separately:

- **Gates** are pass or fail. A phase is done only when every gate for that phase passes. Release requires every gate through Phase 8.
- **Quality** scores live-model wording on a fixed query set. Wording may vary between runs. Card facts may not.

The model is scored on ranking and explanation text. Name, cuisine, rating, and cost are scored against the catalog.

## 1. Gate rules

| Rule | Pass condition |
| --- | --- |
| Automated tests | `pytest` is green (VR-07). |
| Network | `tests/test_ingest.py`, `tests/test_filters.py`, and `tests/test_ranker.py` pass with no API key and no live model call. |
| Facts | On every card, `name`, `cuisines`, `rating`, and `cost_for_two` equal the catalog row for that `id` (API-07). |
| Membership | Every returned `id` exists in the catalog and matches the effective location (API-08). |
| Bounds | `candidate_count` is at most 15. `recommendations` is at most `top_n` (API-09, API-10). |
| Empty search | Zero matches after relaxation return 200, an empty list, and guidance. The model client is not called (API-05, FL-30). |
| Fallback | A blank key, timeout, HTTP error, or unusable JSON returns 200 with `explanation_source` `fallback` and the pre-rank order (MD-10, MD-22, VR-03). |
| Privacy | Parquet, prompt payload, and page omit the `phone`, `url`, `menu_item`, and raw `reviews_list` columns (IN-24, VR-08). |
| Secrets | `.env` is gitignored (SK-06). |

A mismatched number inside an explanation sentence is a quality deduction (section 5). The card fields still have to match the catalog.

## 2. Phase gates

| Phase | Evidence | Pass when |
| --- | --- | --- |
| 1. Skeleton | Startup with and without parquet | SK-01 and SK-03 pass. `from app.config import settings` succeeds. `.env` is absent from git. |
| 2. Ingest | `pytest tests/test_ingest.py` plus one local ingest | IN-01 through IN-39 pass. Both data files exist. A second ingest on the same download yields the same ids (IN-35). |
| 3. Catalog | `GET /api/meta` twice | CT-02 and CT-03 pass. `get_many` matches CT-04, CT-05, and CT-06. |
| 4. Filters | `pytest tests/test_filters.py` | FL-01 through FL-38 pass. An empty relaxed result does not call the model client. |
| 5. Model layer | `pytest tests/test_ranker.py` with a fake HTTP client | MD-07 through MD-26 pass. Tests pass with no API key. |
| 6. Recommend API | Test client against a fixture catalog | API-01 through API-10 pass. |
| 7. UI | Page against the API | UI-01 through UI-15 pass. |
| 8. Verification | Section 4 scorecard plus section 6 queries | VR-01 through VR-08 pass. Quality averages meet section 5. |

Run the automated gates before the live queries. A red pytest file stops the evaluation.

Startup checks SK-02, SK-04, SK-05, CT-01, CT-07, API-11, and API-12 are part of the Phase 8 gate sweep. They can be checked once, not on every query.

## 3. Catalog checks after ingest

Run these against `data/restaurants.parquet` before any live query. Each is pass or fail.

| Check | Pass when |
| --- | --- |
| Row identity | `id` is unique and equals lowercase name, a bar, and the normalized address. |
| Required fields | Every row has a non-empty `name`. |
| Ratings | Every present rating is in the inclusive range 0 to 5. |
| Cost | Every present cost is an integer. Missing cost stays null. |
| Snippets | Every present snippet is at most two excerpts, each about 280 characters. |
| Forbidden columns | `phone`, `url`, `menu_item`, and raw `reviews_list` are absent. |
| Meta | `catalog_meta.json` localities include `Banashankari`. Cuisine and locality lists match the distinct non-empty values in the parquet file. |
| Bands | Histogram counts are printed for low (≤ 500), medium (501–1000), high (> 1000), and missing cost. A nearly empty band fails VR-06 until `app/config.py` is updated and the filter tests are re-run. |

## 4. Release scenario scorecard

Mark each row after one run. Gates are pass or fail.

| ID | Query or setup | Gate |
| --- | --- | --- |
| VR-01 | Banashankari, budget medium, cuisine Italian, minimum rating 4 | Several cards. Each name is in the catalog. Each explanation uses that row’s cuisine, cost, or rating. |
| VR-02 | A locality, cuisine, and rating that stay empty after relaxation | 200, empty list, guidance visible, no model-error banner. |
| VR-03 | Repeat VR-01 with `LLM_API_KEY` removed | Cards remain. Status line shows fallback. Order matches rating, then votes, then id. |
| VR-04 | A search with additional text `quick service` and a working key | At least one explanation uses a payload signal such as Quick Bites or another restaurant type. |
| VR-05 | `POST /api/recommendations` with location `Delhi` | 400 and at most 5 locality suggestions. |
| VR-07 | `pytest` | Green, with no live model calls from the unit tests. |
| VR-08 | Prompt payload and the page for VR-01 | No value from the dropped `phone` column. |
| UI-01 | Open `/` | Localities, cuisines, three budgets, and a 0–5 rating slider load from `/api/meta`. |
| UI-03 | Double-click Submit | One in-flight request. The button enables again when the response returns. |
| UI-08 | VR-02 on the page | Empty-state copy includes the API guidance. |
| UI-12 | A name or explanation containing `<` or `&` | The browser shows the characters as text. |

`Delhi` is sent to the API directly. The locality dropdown is filled from the catalog, so the page itself cannot select it (UI-14).

## 5. Live quality rubric

Use this on VR-01, VR-04, and the extra queries in section 6. Score each returned card, then average.

Automatic checks on every live response, all required:

- HTTP 200 for a known locality.
- `len(recommendations) <= top_n`.
- `candidate_count <= 15`.
- Each `id` is in the catalog at the effective location.
- Cost sits in a band listed under `filters_applied.budget`.
- When `filters_applied.cuisine` is set, that token is on the restaurant.
- When effective `min_rating` is above 0, each rating is present and at least that value.
- `explanation_source` is `llm` when the key is set and the call succeeds.
- Rank order is the list order, with unique ranks.

Explanation score for each card:

| Score | Meaning |
| --- | --- |
| 2 | Two or three sentences. Names the fit using fields that appear on that card or in its candidate payload (cuisine, cost, rating, votes, type, dishes, snippet, or the user’s extra preference). |
| 1 | States a real catalog fact and stops there, or is a single vague sentence that is still true of this restaurant. |
| 0 | Invents a restaurant, a dish, an award, a phone number, or a feature absent from the payload. Or the text is empty after server handling. |

A number in the sentence that disagrees with the card scores 1 at best, even when the rest of the sentence is specific. The card fields remain a separate gate and must still match the catalog.

Preference score, only for queries that send `additional_preferences`:

| Score | Meaning |
| --- | --- |
| 2 | The explanation ties the extra preference to a payload field, such as Quick Bites for “quick service”. |
| 1 | The explanation repeats the preference and still cites a real field. |
| 0 | The explanation ignores the preference, or invents a feature to satisfy it. |

Summary score for the response:

| Score | Meaning |
| --- | --- |
| 2 | Compares the returned set using real differences among those cards. |
| 1 | Mentions the set and stays consistent with the cards. |
| 0 | Describes restaurants that were not returned, or contradicts the effective filters. |

Quality targets for a release:

- Every automatic check in this section passes.
- Mean explanation score on the section 6 set is at least 1.5.
- VR-04 has at least one card with preference score 2.
- Mean summary score is at least 1.

Fallback responses are excluded from the explanation average. They are judged by MD-22 through MD-26 and VR-03.

Re-running a live query may change model order. That is acceptable when both orders satisfy the filters and the rubric. Fallback order for the same shortlist must stay identical (MD-26).

## 6. Fixed live query set

Run these with a working key after the catalog checks. Record gates and rubric scores on the sheet in section 7.

| Query | Location | Budget | Cuisine | Min rating | Extra text | What it evaluates |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | Banashankari | medium | Italian | 4 | — | VR-01. Rich shortlist, grounding, explanations. |
| Q2 | Banashankari | low | South Indian | 3 | family-friendly | Soft preference against restaurant type and snippet. |
| Q3 | Indiranagar | high | — | 4 | — | Blank cuisine means any cuisine (FL-05). High band is cost above 1000. |
| Q4 | Banashankari | medium | Italian | 4 | quick service | VR-04. Preference score. |
| Q5 | A locality with no surviving rows | high | Italian | 4.5 | — | VR-02. Pick the locality during eval if Banashankari still returns rows after relaxation. |
| Q6 | Delhi | medium | Italian | 4 | — | VR-05. Expect 400. |

Q5 is chosen from the catalog, not hard-coded, because relaxation can widen budget, drop cuisine, and lower the rating until only the locality remains. Use a locality whose rows still produce an empty list under FL-30. If every locality still has three restaurants after full relaxation, Q5 is skipped and the empty path is judged from the fixture tests for API-05 instead.

For Q1, also repeat once with the key removed. That repeat is VR-03 and is a gate, not a rubric row.

## 7. Score sheet

Copy this for each evaluation run.

```text
Date:
Catalog rows:
Model:
Git revision:

Gates
[ ] Phase 1–6 pytest
[ ] Catalog checks (section 3)
[ ] VR-01  VR-02  VR-03  VR-04  VR-05  VR-07  VR-08
[ ] UI-01  UI-03  UI-08  UI-12

Quality (explanation / preference / summary)
Q1:  e=   p=n/a  s=
Q2:  e=   p=     s=
Q3:  e=   p=n/a  s=
Q4:  e=   p=     s=
Q5:  empty-path gate only
Q6:  400 gate only

Mean explanation:
Mean summary:
VR-04 preference score 2 on at least one card: yes / no

Release: pass / fail
Notes:
```

Release passes when every checked gate is marked and the section 5 quality targets are met.

## 8. How to run

1. Create a virtual environment and install the package, including `pytest`.
2. Run ingest once. Complete section 3. If VR-06 fails, update budget thresholds and re-run `pytest tests/test_filters.py`.
3. Run `pytest`. Confirm the run makes no live model call.
4. Start the API with a real `LLM_API_KEY`. Execute Q1–Q6 in the browser or with `POST /api/recommendations`.
5. Fill section 7 from the JSON and the page.
6. Stop the API, remove the key, start again, and repeat Q1 for VR-03.

Filter and ranker tests remain the authority for relaxation order, bad JSON, unknown ids, and the 15-candidate cap. The live set checks that those paths still hold on the real catalog and a real model.

## 9. Out of scope

These are listed in the implementation plan as later work, and this evaluation does not score them:

- A database-backed catalog
- A separate frontend toolchain
- Accounts, saved searches, or a stored review corpus
- A taste study or an offline ranking benchmark beyond the rubric above
