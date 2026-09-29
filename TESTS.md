# TESTS.md — Automated Test Results

**pytest: 43/57 passed, 0 failed, 14 skipped.**

**Rich cases (question/SQL/expected/actual captured below): 0/0 passed.**

_No LLM-dependent cases produced rich records this run — either AWS credentials were not configured (see PLAN.md blockers) or this run only covered the DB-security/validator layer. The pytest summary below still reflects everything that actually ran._


Generated automatically by `tests/report.py` via a `pytest_sessionfinish` hook — every row below reflects an actual run against the live app (FastAPI in-process + the local Postgres instance with the full 2M-row dataset loaded), not hand-written expectations.

## Full pytest results

| Test | Outcome |
|---|---|
| `test_me_requires_auth` | ✅ passed |
| `test_chat_requires_auth` | ✅ passed |
| `test_login_wrong_password_rejected` | ✅ passed |
| `test_login_unknown_email_rejected` | ✅ passed |
| `test_login_success_exposes_correct_role_and_scope` | ✅ passed |
| `test_logout_clears_session` | ✅ passed |
| `test_login_response_never_includes_password_hash` | ✅ passed |
| `test_ram_scoped_to_single_territory` | ✅ passed |
| `test_ram_sees_zero_rows_outside_own_territory` | ✅ passed |
| `test_two_rams_in_same_region_see_different_scopes` | ✅ passed |
| `test_director_sees_full_region_not_just_one_territory` | ✅ passed |
| `test_director_cannot_see_other_regions` | ✅ passed |
| `test_wac_column_denied_at_db_level[ram-New York Metro-Northeast]` | ✅ passed |
| `test_wac_column_denied_at_db_level[director-None-Northeast]` | ✅ passed |
| `test_select_star_denied_because_it_includes_wac[ram-New York Metro-Northeast]` | ✅ passed |
| `test_select_star_denied_because_it_includes_wac[director-None-Northeast]` | ✅ passed |
| `test_exec_sees_everything_and_full_wac` | ✅ passed |
| `test_users_table_unreachable_by_every_analytics_role[exec-None-None]` | ✅ passed |
| `test_users_table_unreachable_by_every_analytics_role[director-None-Northeast]` | ✅ passed |
| `test_users_table_unreachable_by_every_analytics_role[ram-New York Metro-Northeast]` | ✅ passed |
| `test_reference_tables_unrestricted_for_every_role` | ✅ passed |
| `test_exec_total_volume_this_month` | ⏭️ skipped |
| `test_exec_hub_dispense_free_drug_excluded_from_default_volume` | ⏭️ skipped |
| `test_market_share_uses_distributor_over_market_data` | ⏭️ skipped |
| `test_top_accounts_grandparent_rollup` | ⏭️ skipped |
| `test_ram_revenue_question_returns_volume_not_dollars` | ⏭️ skipped |
| `test_multiturn_followup_refines_prior_query` | ⏭️ skipped |
| `test_ram_cross_territory_request_stays_scoped` | ⏭️ skipped |
| `test_director_cannot_get_wac_via_rephrasing` | ⏭️ skipped |
| `test_prompt_injection_ignore_instructions_and_drop_table` | ⏭️ skipped |
| `test_prompt_injection_exfiltrate_users_table` | ⏭️ skipped |
| `test_ambiguous_question_gets_a_reasonable_answer` | ⏭️ skipped |
| `test_nonsense_input_handled_gracefully` | ⏭️ skipped |
| `test_empty_result_set_handled_gracefully` | ⏭️ skipped |
| `test_empty_chat_message_rejected` | ⏭️ skipped |
| `test_simple_select_passes_and_gets_limit` | ✅ passed |
| `test_cte_with_select_allowed` | ✅ passed |
| `test_existing_limit_not_duplicated` | ✅ passed |
| `test_rejects_write_and_ddl[INSERT INTO sales (org_id) VALUES ('X')]` | ✅ passed |
| `test_rejects_write_and_ddl[UPDATE sales SET wac = 0]` | ✅ passed |
| `test_rejects_write_and_ddl[DELETE FROM sales]` | ✅ passed |
| `test_rejects_write_and_ddl[DROP TABLE sales]` | ✅ passed |
| `test_rejects_write_and_ddl[TRUNCATE sales]` | ✅ passed |
| `test_rejects_write_and_ddl[ALTER TABLE sales ADD COLUMN x INT]` | ✅ passed |
| `test_rejects_write_and_ddl[GRANT ALL ON sales TO PUBLIC]` | ✅ passed |
| `test_rejects_write_and_ddl[CREATE TABLE evil (x INT)]` | ✅ passed |
| `test_rejects_multiple_statements_prompt_injection_style` | ✅ passed |
| `test_rejects_users_table_reference` | ✅ passed |
| `test_rejects_pg_catalog_probe` | ✅ passed |
| `test_rejects_information_schema_probe` | ✅ passed |
| `test_rejects_wac_for_non_exec[ram]` | ✅ passed |
| `test_rejects_wac_for_non_exec[director]` | ✅ passed |
| `test_rejects_wac_in_order_by_for_non_exec[ram]` | ✅ passed |
| `test_rejects_wac_in_order_by_for_non_exec[director]` | ✅ passed |
| `test_allows_wac_for_exec` | ✅ passed |
| `test_non_select_first_word_rejected` | ✅ passed |
| `test_empty_sql_rejected` | ✅ passed |
