# TESTS.md — Automated Test Results

**pytest: 98/134 passed, 0 failed, 36 skipped.**

**Rich cases (question/SQL/expected/actual captured below): 0/0 passed.**

_No LLM-dependent cases produced rich records this run — either AWS credentials were not configured (see PLAN.md blockers) or this run only covered the DB-security/validator layer. The pytest summary below still reflects everything that actually ran._


Generated automatically by `tests/report.py` via a `pytest_sessionfinish` hook — every row below reflects an actual run against FastAPI in-process + the local Postgres instance with the full 2M-row dataset loaded, not hand-written expectations.

## Full pytest results

| Test | Outcome |
|---|---|
| `test_wac_top_product_multiturn_no_timeout_exec` | ⏭️ skipped |
| `test_director_multiturn_followup` | ⏭️ skipped |
| `test_ram_multiturn_followup` | ⏭️ skipped |
| `test_error_message_only_blames_access_level_for_real_permission_denial` | ⏭️ skipped |
| `test_error_message_blames_access_level_only_when_db_actually_denies` | ⏭️ skipped |
| `test_h4_invalid_column_error_gets_a_distinct_message_not_too_complex` | ⏭️ skipped |
| `test_access_note_exec_never_claims_a_scope_restriction` | ⏭️ skipped |
| `test_access_note_director_says_region_not_territory` | ⏭️ skipped |
| `test_access_note_ram_says_territory` | ⏭️ skipped |
| `test_exec_answer_never_claims_scoped_to_territory` | ⏭️ skipped |
| `test_period_note_matches_documented_offset_patterns[SELECT SUM(wac) FROM sales WHERE data_source='distributor' AND brand_flag=1 AND mo_offset = 0-current month]` | ⏭️ skipped |
| `test_period_note_matches_documented_offset_patterns[SELECT SUM(wac) FROM sales WHERE data_source='distributor' AND brand_flag=1 AND mo_offset IN (0,1,2)-R3M]` | ⏭️ skipped |
| `test_period_note_matches_documented_offset_patterns[SELECT SUM(wac) FROM sales WHERE data_source='distributor' AND brand_flag=1 AND mo_offset IN (3,4,5)-R6M]` | ⏭️ skipped |
| `test_period_note_matches_documented_offset_patterns[SELECT SUM(wac) FROM sales WHERE data_source='distributor' AND brand_flag=1 AND mo_offset IN (1,2,3)-last quarter]` | ⏭️ skipped |
| `test_period_note_none_when_no_offset_filter_present` | ⏭️ skipped |
| `test_top_product_question_defaults_to_r3m_and_states_period` | ⏭️ skipped |
| `test_wac_revenue_question_excludes_hub_dispense_and_market_data` | ⏭️ skipped |
| `test_no_period_account_questions_do_not_time_out[Who are our top 10 accounts by volume?]` | ⏭️ skipped |
| `test_no_period_account_questions_do_not_time_out[What are our top accounts?]` | ⏭️ skipped |
| `test_no_period_account_questions_do_not_time_out[Who are our best customers?]` | ⏭️ skipped |
| `test_no_period_account_questions_do_not_time_out[What are our biggest accounts by units?]` | ⏭️ skipped |
| `test_me_requires_auth` | ✅ passed |
| `test_chat_requires_auth` | ✅ passed |
| `test_login_wrong_password_rejected` | ✅ passed |
| `test_login_unknown_email_rejected` | ✅ passed |
| `test_login_success_exposes_correct_role_and_scope` | ✅ passed |
| `test_docs_urls_disabled_in_production` | ✅ passed |
| `test_docs_urls_enabled_by_default` | ✅ passed |
| `test_docs_reachable_in_this_dev_container` | ✅ passed |
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
| `test_c1_set_config_cannot_leak_another_territory` | ✅ passed |
| `test_c1_set_config_cannot_escalate_to_director_of_another_region` | ✅ passed |
| `test_c1_looping_all_territories_only_ever_shows_own_scope` | ✅ passed |
| `test_c1_set_config_no_effect_even_run_before_any_real_query` | ✅ passed |
| `test_exec_total_volume_this_month` | ⏭️ skipped |
| `test_exec_hub_dispense_free_drug_excluded_from_default_volume` | ⏭️ skipped |
| `test_market_share_uses_distributor_over_market_data` | ⏭️ skipped |
| `test_market_share_all_time_percentage_formatted_correctly` | ⏭️ skipped |
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
| `test_ytd_pattern_recognized_and_labeled_from_real_data` | ✅ passed |
| `test_ytd_pattern_not_confused_with_trailing_12_months` | ✅ passed |
| `test_ytd_pattern_case_and_whitespace_insensitive` | ✅ passed |
| `test_rate_limit_allows_up_to_the_hourly_cap_then_blocks` | ✅ passed |
| `test_rate_limit_resets_after_the_window_elapses` | ✅ passed |
| `test_rate_limit_is_per_user_not_global` | ✅ passed |
| `test_chat_returns_429_with_friendly_message_when_rate_limited` | ✅ passed |
| `test_exec_never_flagged_regardless_of_question` | ✅ passed |
| `test_ram_own_territory_mention_not_flagged` | ✅ passed |
| `test_ram_no_place_named_not_flagged` | ✅ passed |
| `test_ram_other_territory_flagged` | ✅ passed |
| `test_ram_other_region_flagged` | ✅ passed |
| `test_ram_california_south_repro_from_report` | ✅ passed |
| `test_director_territory_within_own_region_not_flagged` | ✅ passed |
| `test_director_own_region_mention_not_flagged` | ✅ passed |
| `test_director_other_region_flagged` | ✅ passed |
| `test_director_territory_in_another_region_flagged` | ✅ passed |
| `test_simple_select_passes_and_gets_limit` | ✅ passed |
| `test_default_period_injected_when_sales_query_has_no_offset_filter` | ✅ passed |
| `test_default_period_not_injected_when_offset_already_present` | ✅ passed |
| `test_default_period_not_injected_when_query_has_no_where_clause` | ✅ passed |
| `test_default_period_not_injected_for_non_sales_tables` | ✅ passed |
| `test_default_period_unaliased_sales_gets_unqualified_filter` | ✅ passed |
| `test_default_period_wk_offset_also_counts_as_already_scoped` | ✅ passed |
| `test_default_period_applies_symmetrically_to_every_where_clause` | ✅ passed |
| `test_default_period_skips_where_clauses_not_scoping_sales` | ✅ passed |
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
| `test_c1_qa_report_attack_payloads_rejected_as_ram[SELECT t.n FROM (SELECT set_config('app.current_territory','Texas',true) AS x) c CROSS JOIN LATERAL (SELECT count(*) AS n FROM sales WHERE c.x IS NOT NULL) t]` | ✅ passed |
| `test_c1_qa_report_attack_payloads_rejected_as_ram[SELECT t.n FROM (SELECT set_config('app.current_role','director',true), set_config('app.current_region','West',true) AS x) c CROSS JOIN LATERAL (SELECT count(*) AS n FROM sales WHERE c.x IS NOT NULL) t]` | ✅ passed |
| `test_c1_qa_report_attack_payloads_rejected_as_ram[SELECT zt.territory_name, (SELECT set_config('app.current_territory', zt.territory_name, true)), count(*) FROM sales s JOIN organizations o ON o.org_id = s.org_id JOIN zip_territory zt ON zt.zip = o.zip GROUP BY zt.territory_name]` | ✅ passed |
| `test_c1_qa_report_attack_payloads_rejected_as_ram[SELECT current_setting('app.current_territory')]` | ✅ passed |
| `test_c1_unicode_escaped_identifier_rejected` | ✅ passed |
| `test_set_and_reset_keywords_rejected` | ✅ passed |
| `test_default_period_not_injected_when_period_qtr_already_present` | ✅ passed |
| `test_default_period_not_injected_when_period_mo_already_present` | ✅ passed |
| `test_default_period_not_injected_when_transaction_date_already_present` | ✅ passed |
| `test_default_period_not_injected_when_week_ending_date_already_present` | ✅ passed |
| `test_strip_no_period_marker_removes_leading_comment_line` | ✅ passed |
| `test_strip_no_period_marker_absent_is_noop` | ✅ passed |
| `test_ensure_default_period_force_no_period_skips_injection_even_without_where` | ✅ passed |
| `test_ensure_default_period_force_no_period_skips_injection_with_other_filters` | ✅ passed |
| `test_qa_report_c2_all_time_total_transactions_repro` | ✅ passed |
| `test_qa_report_c2_qtr_comparison_not_corrupted_by_r3m` | ✅ passed |
| `test_legitimate_query_not_blocked_by_c1_guards` | ✅ passed |
| `test_total_sales_rows_matches_full_dataset` | ✅ passed |
| `test_exec_alltime_paid_demand_units_and_wac` | ✅ passed |
| `test_nym_ram_r3m_paid_units_and_transactions` | ✅ passed |
| `test_nym_ram_alltime_visible_row_count` | ✅ passed |
| `test_northeast_director_r3m_paid_units` | ✅ passed |
| `test_zenovax_docetaxel_r3m_market_share` | ✅ passed |
