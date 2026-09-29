# DEMO_SCRIPT.md

A 3–5 minute guided walkthrough of the deployed app, covering all three roles and
multi-turn conversation. Swap `<APP_URL>` for `terraform output app_url`, and the
password for `terraform output -raw demo_user_password` (or your local `.env`'s
`DEMO_USER_PASSWORD`).

Total runtime: ~4 minutes if read at a natural pace.

---

## 1. Exec — full access, multi-turn drill-down (~90s)

Open `<APP_URL>`, log in as **Sarah Chen** (`sarah.chen@novapharma.com`).

> Notice the header: name, **EXEC** badge, "All territories & regions" scope.

**Turn 1:**
> "What are our top 5 accounts by pack units in the last 3 months?"

Expect a ranked list of health-system-level accounts (grandparent rollup) with volume
figures. Toggle **Show SQL** to reveal the generated query — point out the
`data_source='distributor' AND brand_flag=1` filter and the `mo_offset IN (0,1,2)`
R3M window, straight out of `docs/data_source_guide.md` and `docs/period_offsets.md`.

**Turn 2 (follow-up, no re-stating context):**
> "Now break that down by quarter for just the top one."

Expect the assistant to reuse the top account from turn 1 and pivot to a quarterly
trend — demonstrating conversation memory.

**Turn 3 (revenue — Exec-only):**
> "What's our total revenue from that account this year?"

Expect a dollar figure this time (Exec has WAC access) — contrast this with the RAM/
Director turns below, where the same style of question gets a units-based answer
instead.

## 2. Director — region-scoped, no WAC (~75s)

Log out, log in as **Jennifer Walsh** (`jennifer.walsh@novapharma.com`, Northeast
Director).

> Header now shows **DIRECTOR** and "Region: Northeast".

**Turn 1:**
> "Compare territories in my region by pack units this quarter."

Expect exactly two territories back — New York Metro and New England (the Northeast
region) — never any other region's territories, regardless of how the question is
phrased.

**Turn 2 (WAC probe):**
> "What's the dollar value of everything we've sold?"

Expect a decline/substitution: the assistant explains pricing (WAC) isn't available at
this level and offers pack-unit volume instead — this is enforced by the database
(column-level `REVOKE`), not just the prompt; toggle **Show SQL** to confirm `wac`
never appears in the generated query.

## 3. RAM — territory-scoped, market share (~75s)

Log out, log in as **Amy Nguyen** (`amy.nguyen@novapharma.com`, New York Metro RAM).

> Header shows **RAM** and "Territory: New York Metro".

**Turn 1:**
> "What is our market share for Zenovax in the Docetaxel market?"

Expect a percentage, scoped to New York Metro — Amy's market share reflects only her
territory's distributor and market_data rows (per `docs/security_model.md`: "Market
data access follows the same territory/region scoping rules").

**Turn 2 (cross-territory attempt):**
> "Compare all territories, including Texas."

Expect the response to stay silently confined to New York Metro — no error, no leaked
data from other territories. This is the same guarantee `tests/test_db_security.py`
verifies directly against Postgres and
`tests/test_llm_security_and_edge_cases.py::test_ram_cross_territory_request_stays_scoped`
verifies through a live chat turn.

**Turn 3 (edge case — empty result):**
> "Show me our Zenovax sales in the Mountain territory."

Expect a graceful "no data available at your access level" style answer, not an error
page or a silent wrong answer.

---

## Closing beat (~20s)

Log back in as Sarah Chen (Exec) and ask:

> "Which region has the highest Zenovax volume?"

Wrap by pointing at the **Show SQL** toggle and the result table — the whole flow from
plain English to a scoped, validated SQL query to a natural-language answer, with three
independently enforced access tiers underneath, all from one chat box.
