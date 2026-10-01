# PLAN.md — NL-to-SQL Pharma Assistant

Living plan for the take-home assignment (source: https://github.com/cveeraiy/nl2sql-assignment).
Updated as phases complete. See end of file for a running blocker log.

## QA_REPORT.txt remediation — status (DONE: deployed live, verified against the live site)

An external QA review (`QA_REPORT.txt`) found 2 critical, 4 high, and several medium/low
issues against the full 2M-row dataset. Working through them in the report's suggested
fix order, committing after each. This section is the live status tracker — see git log
for full writeups per item, and `DESIGN.md`'s new "C1" section for the critical finding's
complete before/after.

| # | Item | Status | Notes |
|---|---|---|---|
| C1 | RAM/Director can read any territory/region via `set_config()` in generated SQL | **Done** | Two-layer fix: (1) `sql_guard.py` now rejects `set_config`/`current_setting`/`SET`/`RESET`/`pg_sleep`/`dblink`/`lo_import`/`lo_export` + Unicode-escaped identifiers (`U&"..."`) that could spell a banned word past a text filter; (2) the real fix — `db/02_security.sql` RLS no longer reads a settable session GUC at all. Rewrote to ~22 per-scope Postgres LOGIN roles (`app_exec`, `app_director__<region>` ×6, `app_ram__<territory>` ×15), provisioned by `db/load_data.py`'s new `provision_scope_roles()` from the loaded `zip_territory` data, RLS keyed on `session_user` via a new `role_scope` table. `backend/app/db.py`'s `scoped_cursor()` now connects directly as the right per-scope role instead of `app_login` + `SET LOCAL ROLE` + `set_config()`. New `SCOPE_ROLE_PASSWORD` secret threaded through `docker-compose.yml`, `infra/`, `.env.example`. All 3 confirmed bypass payloads re-run directly against the DB (bypassing `sql_guard.py` entirely) after the fix: all return exactly the caller's own row count now. Tests: `test_db_security.py`'s `test_c1_*` (DB layer) + `test_sql_guard.py`'s `test_c1_*` (app layer). Also fixed in passing: `infra/templates/user_data.sh.tpl` was hardcoding `STATEMENT_TIMEOUT_MS=8000`, silently overriding the `20000` default set last session — the live deployment has actually been running at the old 8s limit this whole time (also fixed `infra/docker-compose.aws.yml`, which was initially missed — it needed the same `SCOPE_ROLE_PASSWORD` plumbing as the local compose file). **Deployed and verified live** (`138c98f`, redeployed via `terraform apply` once a stable connection was confirmed — see the deploy log below). All 4 of the report's attack payloads re-run against the live app as Amy (RAM, logged in over real HTTP): blocked with zero leaked rows in every case — 2 by the new H1 scope-guard matching the territory/region name in the question text, 2 by the model itself declining (`NO_QUERY`) before SQL was ever generated. The authoritative DB-level RLS fix and the `sql_guard.py` regex layer were independently confirmed via the full local pytest suite's `test_c1_*` tests (both layers, 137/137 passing) before and after the live deploy. |
| C2 | Default-period injection corrupts queries that already filter by `period_qtr`/`period_mo`/`transaction_date`/etc., or ask for explicit "all time" | **Done** | `sql_guard.py`'s `_PERIOD_PRESENT` now recognizes `mo_offset`/`wk_offset`/`period_qtr`/`period_mo`/`period_wk`/`transaction_date`/`week_ending_date` as "already scoped" (was `mo_offset`/`wk_offset` only). Added `strip_no_period_marker()` + `ensure_default_period(..., force_no_period=...)`: the SQL-generation prompt (`prompts.py` rule 8) now instructs the model to prepend a `-- NO_PERIOD` comment line when the user explicitly wants all-time/unscoped history; `main.py` strips it before validation and passes the signal through so the R3M backstop is skipped only then. Added 2 new few-shots (all-time with the marker; a named-year query using `period_mo`, not `mo_offset`). Tests: both of the report's repro cases (Q1-2026-vs-Q1-2025 not getting `mo_offset` jammed on top of `period_qtr`; "across all time" staying unfiltered) reproduced directly in `test_sql_guard.py` and asserted fixed, plus unit coverage for each period column and the marker round-trip. Committed locally. |
| H3 | Market share rendered as "1.14%" instead of "114%" (decimal share not ×100'd) | **Done, verified against live Bedrock** | `ANSWER_SYSTEM_PROMPT` (`prompts.py`) now has an explicit rule: `market_share` is a decimal fraction, multiply by 100 before stating it (1.14 -> "114%", never "1.14%"), and state a >100% result plainly as a real property of the data rather than hiding/rounding it. `test_market_share_all_time_percentage_formatted_correctly` (`test_llm_nl_to_sql.py`) passed against real Bedrock once AWS credentials were restored. |
| H4 | "Compare Q1 2026 vs Q1 2025" hallucinates a `period_yr` column and misuses `period_qtr` as `'Q1'` (real format `'2026-Q1'`) | **Done, verified against live Bedrock** | `prompts.py` rule 5 now states explicitly: no `period_yr` column exists, `period_qtr` format is `'<year>-Q<n>'`, `period_mo` is `'<year>-<month>'`. Added a worked Q1-2026-vs-Q1-2025 few-shot using conditional aggregation with the real format. `main.py` now catches `psycopg.errors.UndefinedColumn` before the generic catch-all and returns a distinct "referenced a data field that doesn't exist" message instead of "too complex or slow". `test_h4_invalid_column_error_gets_a_distinct_message_not_too_complex` (`test_answer_quality.py`) passed against real Bedrock once AWS credentials were restored. |
| H1 | Out-of-scope territory/region questions get a fabricated "no sales due to market conditions" answer instead of an access-denied message | **Done** | New `backend/app/scope_guard.py`: `find_out_of_scope_mention()` loads the real territory/region names from `zip_territory` (cached, same pattern as `periods.py`) and matches them against the question text. `main.py`'s `/chat` now checks this FIRST, before calling Bedrock at all — short-circuits with an honest "I don't have access to data for the `<X>` region/territory — I can only show you results for `<own scope>`. Want me to run this for `<own scope>` instead?" message, saving an LLM call + a query that would always return 0 rows anyway. A Director's own region's territories are correctly treated as in-scope (only cross-region mentions are flagged); a RAM's own region name is also allowed through unflagged (common phrasing like "how's my region doing", not itself a request for other territories). Tests (`tests/test_scope_guard.py`, 10 tests, DB-only/no Bedrock) reproduce the report's literal examples: RAM asking about "Texas" or "California South", Director asking about "the West region" or "Texas sales" — all correctly flagged; own-scope mentions and no-place-named questions correctly pass through unflagged. Full non-Bedrock suite (86 tests) still green. |
| H2 | "This year"/YTD defined as trailing 12 months (`mo_offset BETWEEN 0 AND 11`), then answer text calls it "January to November" regardless | **Done** | `prompts.py` rule 5 redefines "this year"/"YTD"/"so far this year" to the current calendar year through the latest available month, via an exact subquery shape (`period_mo >= (SELECT LEFT(period_mo,4) \|\| '-01' FROM sales WHERE mo_offset = 0 LIMIT 1)`) that derives the current year from the data itself rather than hardcoding one. Added a matching few-shot. `periods.py` now recognizes this exact shape (`_YTD_PATTERN`) and labels it from the REAL `period_mo` values present (`_ytd_label()`) — confirmed against the local DB: `mo_offset=0` is `2026-09`, so YTD now correctly labels "year to date (2026): 2026-01 to 2026-09", never a hardcoded "January to November". Tests: `tests/test_periods.py` (3 tests, DB-only/no Bedrock) verify the pattern match and the real label. Full non-Bedrock suite (89 tests) still green. |
| M2 | Drug names misspelled in answers (paraphrased instead of copied verbatim) | **Done** | `ANSWER_SYSTEM_PROMPT` now has an explicit rule: copy `drug_name` exactly as it appears in the rows (case adjustment only), never paraphrase/respell. |
| M3 | Director revenue question gets a flat refusal, not offered the volume alternative RAM already gets | **Done** | Root cause: the model could legally respond `NO_QUERY` when told it lacked WAC access, producing a flat "I'm not able to answer that" refusal instead of attempting a volume query — nothing in the prompt actually forbade this. Added `DOMAIN_RULES` rule 13: a Director/RAM asking about revenue/dollars MUST get a substituted `pack_units` query, never a refusal/`NO_QUERY`, explicitly stated as identical for both roles. Also reinforced in both roles' `scope_line` text. |
| M4 | Exec occasionally told "scoped to your region" (answer-side hallucination, data is full company) | **Done** | `ANSWER_SYSTEM_PROMPT`'s scope-note rule now states explicitly this has NO exceptions for an Exec, even if the question itself names a specific territory/region (mentioning a place isn't the same as being restricted to it) — only the backend's own note may introduce a scope caveat, never the model's own inference. |
| L1 | `/docs` (FastAPI interactive API) publicly reachable on the live host | **Done** | `main.py` now gates `docs_url`/`redoc_url`/`openapi_url` on a new `APP_ENV` env var via `_docs_urls()` — all three disabled when `APP_ENV=production` (set in `infra/docker-compose.aws.yml`'s `backend` service), left on by default for local dev. Tests in `test_auth.py` cover both the pure helper and that `/docs` is actually reachable in this dev container. |
| — | Value-assertion tests using the report's reference numbers (2,000,000 total rows; Exec all-time paid units 6,309,523; NYM R3M units 35,689; Director Northeast R3M units 68,236; Zenovax/Docetaxel share ~114%) | **Done, verified live** | Every reference number independently re-verified directly against the local full dataset via raw SQL before being hardcoded (all matched the report exactly, including the market-share one — report's "~114%" turned out to be the R3M value 1.1378, not all-time, confirmed by checking both). `tests/test_value_assertions.py` (6 tests, DB-only via `scoped_cursor`) all passing. `tests/qa_regression.py`'s 5 live-chat test cases (TC30-TC34) all passed against the live deployed URL (see deploy log below) — confirmed the live site states "6,309,523" verbatim for the Exec all-time-units question. |
| — | Redeploy + re-run `qa_regression.py` against live + update `TESTS.md` | **Done** | See the full deploy log below — `terraform apply`, a deploy-breaking bug found and fixed, redeploy, then `qa_regression.py --base-url http://34.206.93.198`: **40 passed, 0 failed, 0 warnings**. Full local suite re-run after: **137/137 passed, 0 failed, 0 skipped**. `TESTS.md` regenerated from that run and committed. |

M1 (HTTP-only, no TLS) and L2/L3 (org_scope enumerable by any role; demo password
committed in `qa_regression.py`) were explicitly out of scope for this remediation pass
per the user's instructions (not in the numbered fix list) — both are already documented
as accepted trade-offs elsewhere (DESIGN.md trade-offs section; `qa_regression.py`'s own
docstring for L3).

**Reference values from the report** (for the pending value-assertion tests): sales
total rows 2,000,000; Exec all-time paid demand 6,309,523 units / $3,242,848,648.11 WAC;
RAM New York Metro R3M paid units 35,689, R3M paid transactions 4,872, all-time rows
visible 136,921 (confirmed exactly during the C1 fix); Director Northeast R3M paid units
68,236; Zenovax/Docetaxel market share ~1.14 decimal (~114%, a genuine property of the
synthetic `market_data`, already noted in DESIGN.md pre-C1).

**Flight-mode constraint (active as of this session):** user is on an unreliable flight
connection. Continuing to fix C2 onward and **committing locally after each item**, no
`git push`, no `terraform apply`/redeploy, until the user explicitly confirms a stable
connection. If any step needs network (Bedrock calls for LLM-dependent tests, `docker`
image pulls, etc.) and fails due to connectivity, note it here and move to non-network
work rather than retrying in a loop. The final "redeploy + run qa_regression.py against
live + update TESTS.md with live results" step (row 2 above) stays pending until then —
all local fixes and local-pytest-verified TESTS.md updates can still proceed.

**Network blocker hit (during H3, now resolved):** the new LLM-dependent accuracy test
(`test_market_share_all_time_percentage_formatted_correctly`) skipped locally —
`AWS_SESSION_TOKEN` in `.env` is empty, i.e. the temporary AWS SSO credentials have
expired and weren't refreshed into `.env` (this normally needs `aws sso login`, a
browser-based flow — blocked by the flight connection). This affected **every**
Bedrock-dependent test in the suite (`test_llm_nl_to_sql.py`,
`test_llm_security_and_edge_cases.py`, `test_answer_quality.py`), not just this one.

**Resolved:** on a stable connection, confirmed the user's actual AWS auth is long-lived
IAM access keys via `aws configure` (not SSO) — `aws sts get-caller-identity` verified
locally as `arn:aws:iam::080949906726:user/nl2sql-deployer`. Synced
`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` from the local AWS CLI config into `.env`
(`AWS_SESSION_TOKEN` stays empty — not needed for static IAM keys) and confirmed the
tester container itself can authenticate. Ran the full suite: **134/134 passed** (all 36
previously-skipped Bedrock tests now ran and passed). One test
(`test_director_cannot_get_wac_via_rephrasing`) failed once in the full run but passed
3/3 in isolated re-runs — confirmed transient LLM sampling variance (same pattern as
prior sessions' documented Bedrock flakiness), not a real regression. Hardened it anyway
since it's security-relevant (WAC leakage prevention): added a dedicated few-shot to
`FEWSHOT_NON_EXEC` for this exact adversarial phrasing ("dollar value ... exactly"),
explicit that no period/emphasis wording changes the no-wac rule. Re-verified 3/3 in
isolation and the full 134/134 suite clean afterward.

Also fixed in passing (user asked to confirm it): `infra/variables.tf`'s
`budget_alert_email` default was wrong (an old personal address) since this variable was
first introduced — no `tfvars` override exists, so this default is what actually applies
to the live AWS Budget alert. Corrected to `venkatalolla75@gmail.com`.

## Live deploy log (git history rewritten to Venkata, redeploy, found+fixed a real
## deploy-breaking bug, verified against the live site)

1. User rewrote local git history (author -> Venkata &lt;venkatalolla75@gmail.com&gt;) and
   force-pushed to a new remote (`github.com/venkatalolla75/nl2sql-pharma-assistant`).
   `git fetch origin` + `git reset --hard origin/master`: local and origin were already
   byte-identical (same tree hash) before the reset, confirming no work was lost — the
   rewrite happened in the same working directory this session was already using, so
   local `master` already reflected it. Verified `git log` shows Venkata as author on
   every commit.
2. `terraform plan` with `repo_url` pointed at the new GitHub remote: clean, scoped plan
   (EC2 replacement to pick up new user-data/repo URL + the new `SCOPE_ROLE_PASSWORD`
   secret, budget-email update, EIP reattach — no RDS/VPC/IAM changes). Applied
   successfully; same `app_url` (EIP preserved across the replacement).
3. First `qa_regression.py` run against the live URL: **9 passed, 31 failed.** Exec
   questions got the generic "too complex or slow" message; Director/RAM got raw HTTP
   500s. The JSON response's own `error` field gave the exact cause directly:
   `KeyError: 'SCOPE_ROLE_PASSWORD'`.
4. Root cause: `infra/docker-compose.aws.yml`'s `backend` service was missing
   `SCOPE_ROLE_PASSWORD` in its environment block entirely — an earlier edit (adding it
   while fixing C1, before the flight-mode interruption) matched a search string that
   turned out to be unique to the `loader` service's block, so `backend`'s block was
   silently never touched. This shipped undetected through every local test run because
   local dev uses the separate (correctly-edited) `docker-compose.yml`. `app.db.
   get_auth_connection` (login) uses `APP_DB_PASSWORD`, not `SCOPE_ROLE_PASSWORD`, which
   is why login/profile checks kept working while every analytics query broke — a split
   that looked like a database/RLS problem rather than a one-line env-var gap.
5. Fixed, added `tests/test_infra_env_parity.py` (3 tests, compares required env vars
   between the local and AWS compose files' `backend`/`loader` services so this exact
   class of gap can't ship silently again), committed, and **pushed immediately** (this
   fix had to reach `origin/master` before redeploying, since EC2's user-data clones
   whatever's on that branch).
6. Forced an EC2 replacement (`terraform apply -replace="aws_instance.app"`) to pick up
   the fix — same scoped plan pattern as step 2. New instance booted, confirmed
   `6,309,523` units back from a live `/chat` call as Exec (exact match to the report's
   reference value).
7. Re-ran `qa_regression.py` against the live URL: **40 passed, 0 failed, 0 warnings.**
   Every accuracy/security/value-assertion/edge case test case passed, including the
   H1 out-of-scope cases (TC09, TC14) and all 5 value-assertion cases (TC30-34).
8. Re-ran the QA report's 4 literal C1 attack payloads against the live app logged in as
   Amy (RAM) over real HTTP. The live interface is NL-only (no raw-SQL endpoint), so each
   payload was submitted as a prompt-injection-style message asking the model to run the
   exact attack SQL verbatim. All 4 were blocked with zero rows leaked: 2 (the ones
   naming "Texas"/"West" literally in the message text) by the new H1 scope-guard, which
   matches real territory/region names in the question text before Bedrock is even
   called; the other 2 (no place name in the NL text, just the raw SQL) were declined by
   the model itself (`NO_QUERY: out of scope`) before reaching SQL generation. Both
   outcomes are valid independent layers; the authoritative guarantee (DB-level RLS
   keyed on `session_user` + `sql_guard.py`'s regex blocklist) was already proven
   unconditionally by the full local pytest suite's `test_c1_*` tests (`test_db_security.
   py` + `test_sql_guard.py`), which run the exact same 4 payloads directly against
   `scoped_cursor`/`validate_and_finalize` with no LLM involved — SSM access to inspect
   the live RDS connection directly wasn't available (agent never registered on either
   EC2 instance this session; `aws ssm describe-instance-information` stayed empty), so
   this is the closest faithful "live app" reproduction achievable over HTTP alone.
9. Final full local suite re-run: **137/137 passed, 0 failed, 0 skipped.** `TESTS.md`
   regenerated from this run.

## Phased Task List

### Phase 0 — Setup — done
- [x] Copy README.md, docs/, schema/ from assignment repo
- [x] Confirm local tooling: Docker (running), Python 3.14 (present), git (present via Git Bash)
- [x] Install gh CLI, Terraform CLI, AWS CLI via winget (no admin rights needed — user-scope)
- [x] `git init`, initial commit (5 commits so far, one per phase)
- [x] Create GitHub repo via `gh repo create`, push — public, since `infra/`'s EC2 user-data
      clones it with a plain unauthenticated `git clone` (no deploy-key plumbing exists)

### Phase 1 — Plan (this file) — done
- [x] Read README.md and every file in docs/ and schema/
- [x] Summarize domain rules below
- [x] Keep updated through remaining phases

### Phase 2 — Build (local, Docker) — done, verified
- [x] `docker-compose.yml`: Postgres 16 service + app service + loader + tester profiles
- [x] Run `schema/generate_data.py` → full CSVs (40K orgs, 2M sales, 40 products, ~30K zips)
- [x] Postgres DDL (`db/01_schema.sql`)
- [x] Load full dataset via `COPY` (`db/load_data.py`) — verified row counts match spec exactly
- [x] Indexes (`db/03_indexes.sql`) — all planned indexes added post-load
- [x] `users` table + `password_hash` column (bcrypt), seeded with all 23 users, shared demo
      password (assumption documented in DESIGN.md — seed data has no password column)
- [x] DB-level security (`db/02_security.sql`): RLS policies + per-role column GRANTs — verified
      directly with raw psql role-switch tests AND via pytest (`tests/test_db_security.py`)
- [x] FastAPI backend: `/login`, `/logout`, `/me`, `/chat` (`backend/app/main.py`)
- [x] Bedrock integration (`backend/app/bedrock.py`) — exercised live against Amazon Nova Pro
      (not Claude — see Blockers Log and DESIGN.md for why)
- [x] SQL validation (`backend/app/sql_guard.py`) — SELECT-only, row limit, forbidden
      tables/keywords, non-exec WAC check
- [x] Chat UI (`backend/app/static/`) — login, role badge, message thread, loading indicator,
      result tables, Show SQL toggle, friendly errors — tested via curl (login/session/error
      paths); full chat flow not yet visually verified in a browser (needs Bedrock)

### Phase 3 — Test — done
- [x] `tests/` — pytest suite: `test_sql_guard.py`, `test_db_security.py`, `test_auth.py`
      (43 tests, all passing, no Bedrock needed)
- [x] `test_llm_nl_to_sql.py` (accuracy) + `test_llm_security_and_edge_cases.py` (cross-territory,
      prompt injection, edge cases) — all 14 now passing against Amazon Nova Pro (57/57 total)
- [x] Found and fixed three real bugs via this suite, once AWS access made it runnable:
      (1) RLS via a `SECURITY DEFINER` function caused an 8s+ timeout on a scoped full-table
      count (see `db/02_security.sql` design note and DESIGN.md trade-offs); (2) conversation
      history stored as a mixed `"[SQL: ...]\n{answer}"` string caused Nova to echo that same
      hybrid format back on follow-up turns instead of raw SQL, breaking multi-turn refinement
      (`backend/app/main.py`); (3) `load_data.py` wasn't idempotent, so replacing the EC2
      instance against an already-loaded RDS hit `UniqueViolation` on reload (`db/load_data.py`)
- [x] `TESTS.md` auto-generated by a `pytest_sessionfinish` hook — now records two runs: the
      full local suite (57/57) and a live run against the deployed URL over real HTTP
      (`tests/conftest.py`'s `LIVE_URL` env var), which skips only the tests needing a direct
      Postgres connection RDS doesn't expose outside the VPC by design

### Phase 4 — Deploy (AWS via Terraform) — done, live
- [x] `infra/` Terraform: VPC (2 AZ, no NAT Gateway), RDS Postgres (db.t4g.micro, private
      subnet), EC2 (t3.micro, public subnet), IAM instance role scoped to Bedrock + SSM,
      AWS Budget with 80%/100% email alerts
- [x] `terraform validate` + `fmt` pass
- [x] `terraform apply` — applied; fixed three issues surfaced only by a real apply (none
      catchable by `validate`/`fmt`/`plan`): an em dash in a security-group description (EC2's
      API is ASCII-only), AL2023 has no `docker-buildx-plugin` package (fetches the buildx
      binary directly now, resolved via `python3` rather than a `curl | grep -m1` pipe that
      raced under `pipefail`), and the IAM policy needed to also cover Bedrock inference-profile
      ARNs, not just foundation-model ARNs
- [x] Load full dataset into RDS (automated via EC2 user-data)
- [x] Deploy app container to EC2, verify public URL — login, session, and chat all confirmed
      working end-to-end against the live URL
- [x] Re-run Phase 3 test suite against the live URL, results appended to `TESTS.md`

### Phase 5 — Document — done
- [x] `DESIGN.md`: architecture (Mermaid), DB choice rationale, domain-knowledge approach, LLM +
      prompt design, security implementation, AWS services, trade-offs, future improvements
- [x] Updated `README.md` with setup + deployment steps
- [x] `DEMO_SCRIPT.md`: ~4 min script with multi-turn conversations for Exec, Director, and RAM
      (written to be followed once live; not yet recorded — needs the live deployment)

---

## Domain Rules Summary

### Sales definition ("what counts as a sale")
- `sales.data_source` has three distinct meanings — never mix them in one ratio:
  - **`distributor`** — NovaPharma's actual paid shipments. This is "our sales" / "our revenue"
    / "paid demand". Always filter `brand_flag = 1` when asking about NovaPharma's own volume.
    `wac` holds real transaction dollars here.
  - **`hub_dispense`** — free drug via patient assistance program. `wac = 0` always. **Excluded**
    from revenue and from default "sales"/"volume" totals unless the user explicitly asks to
    include free drug / PAP volume (then `data_source IN ('distributor','hub_dispense')`).
  - **`market_data`** — third-party estimate of total market volume, all manufacturers
    (`brand_flag` distinguishes NovaPharma (1) vs. competitors (0) within this source). Used only
    as the market-share denominator or for competitive/market-size analysis. `wac` here is an
    estimate, never used for real revenue.
- Default "sales" / "revenue" query = `data_source = 'distributor' AND brand_flag = 1`.

### Market share formula
```
Market Share = NovaPharma distributor equivalents / total market_data equivalents
```
- Numerator: `SUM(pack_units * unit_conversion_factor)` WHERE `data_source='distributor' AND brand_flag=1`, joined to `products` on `ndc`, filtered to the relevant `market_subcategory`.
- Denominator: same equivalents formula WHERE `data_source='market_data'` for the same `market_subcategory` (all manufacturers).
- Expressed as a decimal 0–1 (×100 for %). **If denominator = 0 → NULL, not 0.**
- Equivalents = `pack_units × unit_conversion_factor` (or `total_mg / mg_equivalent`) — normalizes
  different pack sizes of the same drug so they're comparable.
- R3M vs R6M trend: `R3M share (mo_offset 0,1,2) − R6M share (mo_offset 3,4,5)`; optionally
  volume-weighted: `(R3M share − R6M share) × (R3M volume + R6M volume)`.

### Organization hierarchy
```
Grandparent (health system / IDN)  →  Parent (hospital/clinic group)  →  Facility (site)
```
- `sales.org_id` always references a **Facility**. Roll-ups join through `parent_org_id` /
  `grandparent_org_id` denormalized on the organizations table.
- Default "account" = **grandparent level**. Use
  `COALESCE(o.grandparent_org_name, o.org_name)` because standalone facilities (no parent chain)
  have NULL hierarchy fields and should be treated as their own top-level account.
- `gpo_name` (Onmark / ION / Unity / VitalSource) and `is_340b` are org-level attributes usable
  for segmentation/filtering, unrelated to the org hierarchy levels themselves.

### Product / market classification
```
specialty (Oncology | Urology) → market_category (therapeutic area) → market_subcategory (drug class)
```
- `products.brand_flag = 1` marks NovaPharma's 7 branded products (Zenovax, Carbotrel, Gemtara,
  Paxelium, Oncosetron, Cyclonova, Luprex Depot); `0` = competitor/generic.
- Market share / competitive comparisons always match on `market_subcategory` (e.g., "Docetaxel"
  includes Zenovax + Taxotere + Docetaxel Generic).
- Time filtering should prefer the precomputed `wk_offset`/`mo_offset` columns (0 = current
  period) over raw date arithmetic — offsets already account for data-refresh lag.
  `period_wk`/`period_mo`/`period_qtr` are the human-readable GROUP BY labels.

### Roles & access scope
| Role | Data scope | WAC access |
|---|---|---|
| Exec | All territories, all regions | Full (`can_view_wac=1`) |
| Director | All territories in their assigned `region_name` | None |
| RAM | Only their assigned `territory_name` | None |

- `products` and `zip_territory` are unrestricted reference data for every role.
- Non-Exec revenue questions ("what are my total sales in dollars") must not run a WAC query —
  respond with a polite explanation and offer the unit-based equivalent
  (`pack_units`/`total_mg`/equivalents) instead.
- Cross-scope requests ("compare all territories" from a RAM) must be declined or silently
  narrowed to the user's own scope — never partially leak other territories/regions.

### WAC restriction (defense in depth) — as built
1. **Primary control — column-level GRANTs**: `app_director`/`app_ram` are granted `SELECT` on
   an explicit column list for `sales` that excludes `wac`; `app_exec` gets `SELECT` on the whole
   table. No view needed — Postgres enforces this on the base table itself, so even
   `SELECT * FROM sales` fails with a permission error for non-exec roles (verified in
   `tests/test_db_security.py`).
2. **Primary control — RLS**: row-level security policies on `sales`/`organizations` keyed off
   session GUCs (`app.current_role`/`app.current_territory`/`app.current_region`) set via
   `SET LOCAL`/`set_config()` from the authenticated user's DB row at the start of each request's
   transaction — independent of what SQL the LLM generates.
3. **Secondary control — prompt + generated-SQL validation**: the system prompt tells non-Exec
   roles they have no WAC access at all; `sql_guard.py` additionally rejects any `wac` reference
   for non-Exec roles before the query ever reaches Postgres, so a validated system doesn't rely
   on the LLM's cooperation alone.

---

## Blockers Log

| # | Phase | Blocker | Status |
|---|---|---|---|
| 1 | 0 | `gh` CLI not authenticated — repo creation/push needs `gh auth login` (interactive OAuth) | **Resolved** — user ran `gh auth login` |
| 2 | 2/4 | No AWS credentials present (`~/.aws` absent, no env vars) | **Resolved** — user ran `aws configure` (IAM user `nl2sql-deployer`, `AdministratorAccess`, region `us-east-1`) |
| 3 | 4 | Bedrock model access enabled in console, but every `Converse` call against Anthropic Claude models failed with `AccessDeniedException: ... not authorized to perform the required AWS Marketplace actions (aws-marketplace:ViewSubscriptions, aws-marketplace:Subscribe) ...`, identically for both the admin IAM user and the EC2 instance role, and recurring after the 5+ minutes AWS's own error message suggests waiting | **Resolved by switching model, not by fixing the blocker itself** — this is an account-level AWS Marketplace entitlement restriction (common on new/free-tier accounts), not an IAM or code problem. Switched the default `BEDROCK_MODEL_ID` to `amazon.nova-pro-v1:0` (first-party Bedrock model, no Marketplace listing, works on-demand). See DESIGN.md "Model choice" for the full writeup. `infra/iam.tf` still authorizes `anthropic.*` too, so reverting is a one-line env var change if this account's Marketplace restriction clears later. |
| 4 | 4 | `terraform apply` to upgrade RDS to `db.t4g.small` (for more buffer-cache headroom against timeouts) failed: `FreeTierRestrictionError: This instance size isn't available with free plan accounts.` | **Open, not urgent** — this account's AWS billing plan itself rejects the `ModifyDBInstance` call; needs the account plan upgraded or a support request, not a code/Terraform fix. RDS confirmed left in a clean, unmodified state (`available`, still `db.t4g.micro`) — the failed call didn't get stuck partway. `var.rds_instance_class` reverted to `db.t4g.micro` to match; bump it back to `db.t4g.small` once the restriction lifts. Not urgent because the default-period backend enforcement + `idx_orgs_account_name` (see git log) already fixed the timeout this was meant to guard against. |

**Additional issues found only once a real `terraform apply` ran** (none of these are
catchable by `validate`/`fmt`/`plan` — they only surface against the real AWS API or the
real EC2 boot sequence): an em dash in an `aws_security_group` description (EC2's
`CreateSecurityGroup` API is ASCII-only); AL2023 has no `docker-buildx-plugin` package, so
`docker compose build` failed on the instance with "requires buildx 0.17.0 or later" and
silently aborted the rest of `user-data` under `set -e` (fetches the buildx binary directly
now); the IAM policy needed `bedrock:InvokeModel` on inference-profile ARNs, not just
foundation-model ARNs; and `load_data.py` wasn't idempotent, so replacing the EC2 instance
against an already-loaded RDS (e.g. to pick up a `user-data` fix) hit `UniqueViolation` on
reload — fixed with a `TRUNCATE ... CASCADE` before loading. All fixed and verified via a
full instance-replacement cycle; see git log for details.

**Verified working end-to-end, live**: `https://github.com/venkatalolla75/nl2sql-pharma-assistant`
(public — required so EC2's unauthenticated `git clone` in `user-data` can reach it) deployed
to AWS via Terraform; full 2M-row dataset loaded into RDS; login, session, and chat confirmed
working against the public URL for Exec/Director/RAM roles; database-level security
independently verified with raw psql role-switch tests locally (RAM sees 2,648/40,000 orgs and
136,921/2,000,000 sales rows — New York Metro only, WAC column access denied by Postgres
itself; Director sees 5,211 orgs/268,912 sales — Northeast region; Exec sees all
40,000/2,000,000 rows plus full WAC; `app_exec` is denied access to the `users` table, so
LLM-generated SQL can never read credentials regardless of role) — the identical schema/security
SQL is what's applied to RDS. 57/57 tests pass locally; 36/57 pass against the live URL over
real HTTP (the other 21 are exactly the direct-Postgres tests, which correctly can't reach RDS
from outside the VPC — see TESTS.md).
