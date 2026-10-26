# Edge Cases: Restaurant Recommendation System

Corner cases for the build in [implementation-plan.md](implementation-plan.md). Each case states the situation and the behavior the phase must implement. IDs are stable so tests can cite them.

Rules that cut across phases:

- Restaurant facts on a card come from the catalog. The model supplies order, summary, and explanation text.
- Location is a Bangalore locality from the catalog. City names such as Delhi or Bangalore are unknown localities.
- A fully empty shortlist skips the model. One or two matches after relaxation still call the model.
- A blank `LLM_API_KEY`, a timeout, an HTTP error, or unusable JSON returns a 200 fallback list ordered by rating and votes.
- Phone numbers, URLs, menu dumps, and raw `reviews_list` never appear in the parquet file, the prompt, or the page.

## Phase 1 — Skeleton

| ID | Situation | Expected behavior |
| --- | --- | --- |
| SK-01 | `data/restaurants.parquet` is absent at startup | Process exits. The message tells the operator to run the ingest script. |
| SK-02 | Parquet exists but is unreadable (truncated or wrong format) | Process exits with the same ingest instruction. The API does not stay up and answer 500s. |
| SK-03 | `.env` is missing | App starts from defaults: base URL, model name, candidate limit 15, top-n 5, timeout 20 seconds. |
| SK-04 | `LLM_API_KEY` is empty | Startup still succeeds. Ranking waits until a request, then uses fallback (MD-10). |
| SK-05 | `CANDIDATE_LIMIT`, `DEFAULT_TOP_N`, or `LLM_TIMEOUT_SECONDS` is zero, negative, or non-numeric | Startup fails with a configuration error that names the variable. |
| SK-06 | Fresh clone | `data/` and `.env` are gitignored, so the first start hits SK-01 until ingest is run. |

## Phase 2 — Ingest

### Ratings

| ID | Input | Expected value |
| --- | --- | --- |
| IN-01 | `4.1/5` | `4.1` |
| IN-02 | `4.1 /5` (space before the slash) | `4.1` |
| IN-03 | `NEW` | missing |
| IN-04 | `-` | missing |
| IN-05 | blank, null, or whitespace | missing |
| IN-06 | Parsed number below 0 or above 5 | missing |

### Cost for two

| ID | Input | Expected value | Budget band |
| --- | --- | --- | --- |
| IN-07 | `800` | `800` | medium |
| IN-08 | `1,200` | `1200` | high |
| IN-09 | blank, null, or whitespace | missing | excluded by every budget filter |
| IN-10 | `500` | `500` | low (upper edge) |
| IN-11 | `501` | `501` | medium (lower edge) |
| IN-12 | `1000` | `1000` | medium (upper edge) |
| IN-13 | `1001` | `1001` | high (lower edge) |
| IN-14 | `0` | `0` | low |

Rows with a missing cost stay in the catalog. The histogram counts only rows that have a cost.

### Yes / No fields and list fields

| ID | Situation | Expected behavior |
| --- | --- | --- |
| IN-15 | `online_order` or `book_table` is `Yes` or `No` in any letter case | `true` or `false` |
| IN-16 | Either flag is blank | `false` |
| IN-17 | `cuisines`, `rest_type`, `dish_liked`, or `listed_in(type)` is null | empty list |
| IN-18 | `North Indian, Mughlai, Chinese` | three trimmed tokens |
| IN-19 | Extra spaces, a trailing comma, or a repeated token | empty tokens dropped, repeats collapsed |
| IN-20 | Cuisine token case differs only by capitals across rows | one catalog spelling is kept, and later match is case-insensitive |

### Reviews and dropped columns

| ID | Situation | Expected behavior |
| --- | --- | --- |
| IN-21 | `reviews_list` is empty, `[]`, or malformed | `review_snippet` is null. Ingest continues. |
| IN-22 | One short review | That review is kept, truncated only when it exceeds about 280 characters. |
| IN-23 | Many reviews, including a multi-megabyte `reviews_list` | At most two excerpts, each about 280 characters. The raw column is discarded. |
| IN-24 | Output parquet | Columns `phone`, `url`, `menu_item`, and raw `reviews_list` are absent. |
| IN-25 | A review excerpt itself contains a phone number or other personal text | The excerpt may still contain it, because only the `phone` column is removed. Excerpts stay short. |

### Identity and dedupe

The id is `lowercase(name) + "|" + normalized address`. Address normalization trims, lowercases, and collapses internal whitespace. Matching is exact after that. Nearby spellings stay different restaurants.

| ID | Situation | Expected behavior |
| --- | --- | --- |
| IN-26 | Name is null, blank, or whitespace | Row is dropped. |
| IN-27 | Same name and address, different `listed_in(type)` or `listed_in(city)` | One restaurant. List fields are a set union. Areas are a set union. |
| IN-28 | Duplicate rows disagree on `votes` | Keep the largest `votes` and the `rating` from that same row. |
| IN-29 | Duplicate rows tie on `votes` | Keep the higher rating. If the rating also ties, keep the earliest source row so a second ingest is identical. |
| IN-30 | One duplicate has a cost or a snippet and another does not | Keep a non-null cost and a non-null snippet. When both costs are present and differ, keep the cost from the row chosen for votes. |
| IN-31 | Scalar flags disagree (`online_order`, `location`) | Take them from the same row chosen for votes. |
| IN-32 | Same name, different address (a chain) | Two ids and two catalog rows. |
| IN-33 | Same place with different capitalization or extra spaces in the address | One id. |
| IN-34 | Name has damaged encoding such as `CafÃ©` | Repair the encoding when the result is a readable name. Leave the name unchanged when the repair is ambiguous. |
| IN-35 | Ingest run twice on the same download | The same ids and the same merged fields. |
| IN-36 | `data/` does not exist yet | The script creates it, then writes `restaurants.parquet` and `catalog_meta.json`. |

### Catalog meta

| ID | Situation | Expected behavior |
| --- | --- | --- |
| IN-37 | `catalog_meta.json` | Localities and cuisines are sorted, unique, and taken from rows that survived dedupe. Restaurant count is the deduped count. |
| IN-38 | A row has a blank locality | It is stored, and the blank value is left out of the locality list. |
| IN-39 | Cost histogram | Prints counts for low, medium, high, and missing. A nearly empty band is a signal to edit `app/config.py` and re-run filter tests (VR-06). |

## Phase 3 — Catalog and meta

| ID | Situation | Expected behavior |
| --- | --- | --- |
| CT-01 | First successful startup after ingest | Localities and cuisines are loaded from the parquet rows. A stale `catalog_meta.json` cannot hide a locality that is present in parquet. |
| CT-02 | Second `GET /api/meta` | Answers from memory. Parquet is not read again. |
| CT-03 | `GET /api/meta` after a real ingest | 200. Body includes `Banashankari`, the cuisine list, budgets `low`, `medium`, and `high`, and default minimum rating `0`. |
| CT-04 | `get_many` with a known id followed by an unknown id | Returns the known restaurant only. |
| CT-05 | `get_many` id order is `b`, `a` | Result order is `b`, then `a`. |
| CT-06 | `get_many` repeats an id | One entry, at the first position. |
| CT-07 | Parquet has zero restaurant rows | Process starts. Meta lists are empty. Recommendation search returns the empty state. |

## Phase 4 — Filters, pre-rank, and relaxation

### Request validation

Matching is case-insensitive after trim. A cuisine match is equality with a whole token. `India` does not match `North Indian`. `Italian` matches a restaurant whose cuisine list contains `Italian`.

| ID | Situation | Expected behavior |
| --- | --- | --- |
| FL-01 | `location` omitted, blank, or whitespace | 400. Location is required. |
| FL-02 | `banashankari` or ` Banashankari ` | Matches catalog locality `Banashankari`. The response uses the catalog spelling. |
| FL-03 | `Delhi` or `Bangalore` | 400. Suggestions are a short list of catalog localities, capped at 5, and empty when nothing is close. |
| FL-04 | `budget` omitted or a value such as `cheap` | 400. |
| FL-05 | `cuisine` omitted, blank, or whitespace | Any cuisine. |
| FL-06 | `italian` | Matches token `Italian`. |
| FL-07 | Cuisine is a substring of a token, or a token is a substring of the query | No match. Unknown full strings return 400 with up to 5 cuisine suggestions. |
| FL-08 | `min_rating` omitted | Treated as `0`. |
| FL-09 | `min_rating` is below 0, above 5, or not a number | 400. |
| FL-10 | `additional_preferences` omitted or whitespace | Empty preference text. |
| FL-11 | Preference text length 300 | Accepted. |
| FL-12 | Preference text length 301 | 400. |
| FL-13 | `top_n` omitted | 5. |
| FL-14 | `top_n` is 1 or 8 | Accepted. |
| FL-15 | `top_n` is 0, 9, negative, or not an integer | 400. |

### Who passes the hard filters

| ID | Situation | Expected behavior |
| --- | --- | --- |
| FL-16 | Locality, cuisine token, rating, and cost all match | Row is eligible. |
| FL-17 | Cost is missing | Excluded for low, medium, and high. |
| FL-18 | Cost is 500, 501, 1000, or 1001 | Bands follow IN-10 through IN-13. |
| FL-19 | `min_rating` is 0 and rating is missing | Row stays eligible. |
| FL-20 | `min_rating` is greater than 0 and rating is missing | Row is excluded. |
| FL-21 | Rating equals `min_rating` | Row stays eligible (`>=`). |
| FL-22 | Restaurant has several cuisines and one token matches | Row stays eligible. |
| FL-23 | Locality has restaurants and every one lacks a cost | Empty result. Summary can say places were skipped because cost is unknown. |

### Score, cap, and thin results

Score is `rating * log(1 + votes)`. Sort by score descending, then votes descending, then id ascending.

| ID | Situation | Expected behavior |
| --- | --- | --- |
| FL-24 | Rating missing | Sorts after every rated row, including a rated row with 0 votes. |
| FL-25 | Votes are 0 and rating is present | Score is 0. The row still sorts ahead of missing ratings. |
| FL-26 | Two rows share a score and a vote count | Lower id comes first. |
| FL-27 | 16 or more rows match | Prompt candidates are the top 15. `candidate_count` is 15. |
| FL-28 | 4 rows match | `candidate_count` is 4. `top_n` 5 returns at most 4 cards. |
| FL-29 | 1 or 2 rows remain after every relaxation | Those rows are the candidate list. The model is called. |
| FL-30 | 0 rows remain after every relaxation | Empty `recommendations`, guidance in `summary`, model is not called. |

### Relaxation

Relax only when the current match count is below 3. Stop at the first step that yields 3 or more. Location is never widened.

| Step | What changes |
| --- | --- |
| 1 | `low` also allows medium. `high` also allows medium. `medium` also allows low and high. |
| 2 | Cuisine constraint is removed. |
| 3 | `min_rating` drops by 0.5, repeating until the count is at least 3 or the threshold reaches 0. |

| ID | Situation | Expected `relaxed` value |
| --- | --- | --- |
| FL-31 | 3 or more rows match the original filters | `[]` |
| FL-32 | 2 rows match, and the wider budget produces 3 or more | `["budget_widened"]`. Cuisine and minimum rating stay as requested. |
| FL-33 | Wider budget is still under 3, and dropping cuisine reaches 3 | `["budget_widened", "cuisine_dropped"]` |
| FL-34 | Cuisine drop is still under 3 | `min_rating_lowered` is appended. Effective `min_rating` is the threshold that was actually used. |
| FL-35 | Original `min_rating` is already 0 | Step 3 has nothing to lower. |
| FL-36 | User asked for `low` | Widened bands are low and medium. High stays out. |
| FL-37 | User asked for `high` | Widened bands are high and medium. Low stays out. |
| FL-38 | User asked for `medium` | Widened bands are low, medium, and high. |

Effective filters in the response:

```json
{
  "location": "Banashankari",
  "budget": ["medium", "low", "high"],
  "cuisine": null,
  "min_rating": 3.5,
  "relaxed": ["budget_widened", "cuisine_dropped", "min_rating_lowered"]
}
```

`cuisine` is null when that constraint was dropped. `budget` lists only the bands in force.

## Phase 5 — Prompt, model output, and fallback

### Prompt payload

| ID | Situation | Expected behavior |
| --- | --- | --- |
| MD-01 | 15 candidates | The user message contains 15 records and no more. |
| MD-02 | `dish_liked` is very long | The list sent to the model is capped. |
| MD-03 | `review_snippet` is null | The field is omitted. |
| MD-04 | Candidate record | Includes id, name, cuisines, rating, votes, cost, restaurant type, listing types, online order, and table booking. Excludes phone, url, and menu items. |
| MD-05 | `additional_preferences` is `quick service` | The phrase is in the user message. The instructions tell the model to use it as the tie-breaker. |
| MD-06 | `LLM_BASE_URL` has a trailing slash | The client calls `{base}/chat/completions` once, with a single slash before `chat`. |

### Model JSON

Temperature is 0.2. Timeout is 20 seconds.

| ID | Model output | Expected behavior |
| --- | --- | --- |
| MD-07 | JSON object with `summary` and `recommendations` | Use it. `explanation_source` is `llm`. |
| MD-08 | The same JSON inside a ` ```json ` fence | Fences are stripped, then parsed as in MD-07. |
| MD-09 | Prose around the JSON, a JSON array, or truncated JSON | Fallback. |
| MD-10 | API key blank, timeout, connection error, or HTTP 401, 429, or 500 | Fallback. A blank key does not wait on the network. |
| MD-11 | `recommendations` is `[]` | Fallback. |
| MD-12 | `summary` is missing and the id list is usable | Keep the ids. Summary is an empty string. |
| MD-13 | One known id and one unknown id | Keep the known id. Source stays `llm`. |
| MD-14 | Every id is unknown, or the only ids are duplicates of unknown ids | Fallback. |
| MD-15 | The same known id appears twice | Keep the first copy. |
| MD-16 | More than `top_n` valid items | Keep `top_n` after ordering by `rank`, then by array order. |
| MD-17 | Fewer valid items than `top_n` | Return those items. Do not fill the rest from the fallback ranker. |
| MD-18 | `rank` values are gapped or start above 1 | Sort by ascending `rank`. Missing `rank` keeps array order after the ranked items. |
| MD-19 | Explanation is empty | Substitute the fallback sentence for that restaurant. Source stays `llm`. |
| MD-20 | Explanation is longer than the configured cap | Truncate the text on the server. |
| MD-21 | Explanation quotes a rating or cost that differs from the catalog | Leave the sentence as written. Card fields still come from the catalog (API-07). |

### Fallback ranker

| ID | Situation | Expected behavior |
| --- | --- | --- |
| MD-22 | Fallback runs | Order matches FL-24 through FL-26. Length is `min(top_n, candidate count)`. |
| MD-23 | Fallback explanation | Built from that row’s rating, votes, cuisine, and cost. |
| MD-24 | Rated row has no rating because `min_rating` was 0 | Explanation omits a numeric rating. |
| MD-25 | Fallback summary | States that the list is ordered by rating and popularity because a written recommendation was unavailable. |
| MD-26 | Same candidates and preferences, fallback twice | The same ids in the same order. |

## Phase 6 — Recommendation API

| ID | Situation | Expected behavior |
| --- | --- | --- |
| API-01 | Valid search with a mocked model | 200. Card order follows model rank. Facts are joined by id. |
| API-02 | Unknown locality or cuisine | 400 and up to 5 suggestions. |
| API-03 | Body is empty, is not JSON, or has the wrong field types | 400. |
| API-04 | Extra JSON fields | Ignored. Known fields still validate. |
| API-05 | Shortlist empty | 200, `recommendations` is `[]`, summary asks for another locality or a lower rating, `explanation_source` is omitted, model client is not called. |
| API-06 | Provider failure with a non-empty shortlist | 200 and `explanation_source` is `fallback`. |
| API-07 | Model text names a different rating or cost | `rating` and `cost_for_two` on the card equal the parquet row. |
| API-08 | Response ids | Every id was in that request’s candidate set. |
| API-09 | `candidate_count` | Size of the capped shortlist before `top_n`. Never above 15. |
| API-10 | `top_n` is 1 and 15 candidates exist | `candidate_count` is 15. `recommendations` has one item. |
| API-11 | Two requests at the same time | Both use the catalog loaded at startup. |
| API-12 | Catalog failed during startup | The process has already exited (SK-01, SK-02). A running server does not use 500 for ordinary searches. |

## Phase 7 — User interface

| ID | Situation | Expected behavior |
| --- | --- | --- |
| UI-01 | `/` loads and meta succeeds | Locality dropdown and cuisine suggestions come from `/api/meta`. Budget options are low, medium, and high. Rating slider runs from 0 to 5. |
| UI-02 | `/api/meta` fails | The form shows a load error. Submit stays disabled. |
| UI-03 | Submit, including a double click or a second Enter | One request. The button is disabled until the response or the error returns, then it is enabled again. |
| UI-04 | 200 with cards | Status line shows the effective filters. Summary is visible. Cards follow rank and show name, cuisines, rating, cost for two, explanation, address, and restaurant type. |
| UI-05 | `relaxed` is non-empty | Status line names each relaxation. |
| UI-06 | `relaxed` is `[]` | Status line does not say the search was broadened. |
| UI-07 | `explanation_source` is `fallback` | Status line says the written recommendation was unavailable. |
| UI-08 | Empty `recommendations` | The empty state shows the API summary, which tells the user to change locality or rating. The summary block used for a non-empty list stays hidden. |
| UI-09 | 400 with suggestions | Those locality or cuisine suggestions are shown. |
| UI-10 | Rating is null on a card | The card shows that a rating is unavailable. It does not show 0. |
| UI-11 | Several cuisines | Shown together on the card. |
| UI-12 | Name, address, or explanation contains `<`, `&`, or script-like text | Inserted as text. The browser does not treat it as HTML. |
| UI-13 | Cuisine left blank | Request omits cuisine or sends it blank, and the API treats it as any cuisine (FL-05). |
| UI-14 | Locality control | A dropdown of catalog localities, so `Delhi` cannot be selected there. The API case FL-03 still stands for a hand-written request. |
| UI-15 | Long explanation or a long name | Text wraps inside the card. |

## Phase 8 — Verification scenarios

These are the manual checks from the plan, written as cases.

| ID | Setup | Expected behavior |
| --- | --- | --- |
| VR-01 | Banashankari, medium, Italian, minimum rating 4, live model | Several cards. Each name is in the catalog. The explanation uses cuisine, cost, or rating from that row. |
| VR-02 | A locality, cuisine, and rating that stay empty through FL-30 | Empty state and guidance. No model-error banner. |
| VR-03 | The VR-01 search with `LLM_API_KEY` removed | Cards remain. Status line shows fallback. Order follows rating and votes. |
| VR-04 | Additional text `quick service`, live model | At least one explanation uses a signal from the payload, such as Quick Bites or another restaurant type. |
| VR-05 | Request location `Delhi` | 400 and locality suggestions. |
| VR-06 | Phase 2 histogram shows a nearly empty budget band | Adjust the thresholds in `app/config.py`, then re-run the filter tests before treating the bands as final. |
| VR-07 | `pytest` | Green. Ingest, filter, and ranker tests do not call a live model. |
| VR-08 | Prompt payload and the rendered page for any search | No phone numbers from the `phone` column. |

## Case index by test file

| Test file | Cases that belong there |
| --- | --- |
| `tests/test_ingest.py` | IN-01 through IN-39 |
| `tests/test_filters.py` | FL-01 through FL-38 |
| `tests/test_ranker.py` | MD-01 through MD-26, API-01 through API-10 |
| Manual, Phase 8 | CT-03, UI-01 through UI-15, VR-01 through VR-08 |
| Startup check | SK-01 through SK-06, CT-01, CT-02, CT-07, API-11, API-12 |
