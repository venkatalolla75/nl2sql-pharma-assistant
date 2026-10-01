-- Database-level access control.
--
-- Design: the backend connects as ONE of a small set of Postgres LOGIN roles, chosen
-- server-side from the authenticated user's row in `users` (never from the LLM or the
-- request body):
--   - app_exec              — one shared role, full access, BYPASSRLS
--   - app_director__<slug>  — one per region (6), e.g. app_director__northeast
--   - app_ram__<slug>       — one per territory (15), e.g. app_ram__new_york_metro
-- Unlike an earlier revision of this file, there is no shared "app_director"/"app_ram"
-- role carrying a *settable* scope (session GUCs set via set_config()) — each login
-- identity's scope is fixed by which role it IS, not by a value the executed query could
-- overwrite. See the C1 design note below for why this changed, and db/load_data.py's
-- provision_scope_roles() for where the per-territory/per-region roles actually get
-- created (it needs zip_territory's data loaded first to know the territory/region
-- names, so it can't happen in this file, which runs before any data load).
--
-- app_login itself (NOLOGIN until load_data.py sets its password) is unrelated to
-- analytics access — it's used for exactly one thing, the /login auth lookup against
-- `users`, and has no membership in any of the roles above, so it cannot read sales/
-- organizations/products/zip_territory/org_scope at all, let alone become another role.
--
-- Two independent layers enforce scoping once the appropriate role is connected:
--   1. Column-level GRANTs: app_director/app_ram (the template roles every per-scope
--      role inherits from) are never granted SELECT on sales.wac. Even `SELECT *` or
--      `SELECT wac` fails with a Postgres permission error — enforced by the database,
--      not by the prompt or the SQL validator.
--   2. Row-level security (RLS): app_director__*/app_ram__* only see sales/organizations
--      rows whose territory/region matches that role's entry in role_scope, checked
--      against session_user — see below. app_exec has BYPASSRLS and sees everything.
--
-- org_scope (org_id -> territory_name/region_name, see 01_schema.sql) backs the RLS
-- check via a direct EXISTS subquery against a table every scope role is granted SELECT
-- on. An earlier version routed this through a SECURITY DEFINER function instead,
-- specifically to stop a RAM from running `SELECT DISTINCT territory_name FROM org_scope`
-- and enumerating every territory/org in the company. That held up under targeted
-- role-switch tests but fell over at 2M-row scale: Postgres cannot inline a
-- SECURITY DEFINER function into the query plan, so `org_in_scope(sales.org_id)`
-- evaluated once per row instead of as a set-based semi-join — a plain scoped
-- `SELECT count(*) FROM sales` timed out past 8s. Reverted to the direct-subquery form,
-- which the planner turns into an indexed semi-join and executes in milliseconds.
-- Trade-off accepted: org_scope contains only org_id/territory_name/region_name (no
-- sales figures, no WAC, no addresses) — a RAM can see the full territory/region list
-- and how orgs map to them, but not any organization's identity/address details (those
-- stay row-scoped via the `orgs_scope` policy on `organizations` itself) or any sales
-- data outside their own scope.
--
-- ===========================================================================
-- C1 design note (QA report finding, fixed here): RLS keyed on a settable GUC is
-- bypassable from inside the executed query itself
-- ===========================================================================
-- The PREVIOUS version of this file keyed both RLS policies off session GUCs
-- (current_setting('app.current_territory'/'app.current_region'/'app.current_role'))
-- that the backend set per-request via set_config(...) after connecting as a single
-- shared app_director/app_ram role. Those GUCs live in the same session the untrusted
-- LLM-generated SQL executes in, and set_config() is an ordinary function callable from
-- inside a SELECT — so a RAM's own generated query could call
-- set_config('app.current_territory', 'Texas', true) and the RLS policy would then
-- trust the attacker's value, reading another territory's data entirely. Confirmed via
-- the QA report's reproduction: a RAM scoped to New York Metro could read Texas's
-- 8,736 rows, or (by setting app.current_role to 'director') an entire region's data, or
-- loop every territory in one query.
--
-- backend/app/sql_guard.py now also rejects set_config/current_setting/SET/RESET
-- outright as a second, independent layer — but a word-blocklist on generated SQL is
-- inherently a chasable target (the same report flags Unicode-escaped identifiers,
-- U&"...", as one concrete way to spell a banned word past a naive text filter), so it
-- isn't the real fix on its own. The real fix is this file: there is no longer any
-- mutable session state for a query to override. Scope comes from *which role the
-- connection authenticated as* (session_user), fixed for the lifetime of that
-- connection and unrelated to anything inside the query it runs. A query could still
-- try `SET ROLE app_ram__texas`, but role_scope's policies check session_user (which
-- SET ROLE does not change — only SET SESSION AUTHORIZATION does, and that requires
-- superuser) — and even current_user would fail here regardless, since app_ram__nym
-- is never granted membership in sibling territory roles, only in the shared app_ram
-- template.

-- ---------------------------------------------------------------------------
-- Roles
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_login') THEN
        CREATE ROLE app_login NOLOGIN;  -- LOGIN + PASSWORD set later by load_data.py from env
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_exec') THEN
        -- LOGIN + PASSWORD set later by load_data.py — a single shared identity is fine
        -- for exec since there's no scope to escalate out of (BYPASSRLS already grants
        -- everything), unlike director/ram.
        CREATE ROLE app_exec NOLOGIN BYPASSRLS;
    END IF;
    -- Template roles: NOLOGIN, hold the column-level grants below. Every per-territory/
    -- per-region LOGIN role (created by load_data.py's provision_scope_roles(), once
    -- territory/region names are known from the loaded zip_territory data) is granted
    -- membership in one of these and inherits its privileges — not logged into directly.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_director') THEN
        CREATE ROLE app_director NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_ram') THEN
        CREATE ROLE app_ram NOLOGIN;
    END IF;
END $$;

-- Explicitly revoke any stale membership from a database previously provisioned by an
-- earlier revision of this file (which DID grant these, as part of the design this
-- replaced). A no-op if the membership was never granted — safe to run unconditionally
-- now that all four roles above are guaranteed to exist.
REVOKE app_exec, app_director, app_ram FROM app_login;

-- Deliberately NO "GRANT app_exec/app_director/app_ram TO app_login" here (the previous
-- revision had this, relying on `SET LOCAL ROLE` + WITH INHERIT FALSE as a fail-closed
-- guard). app_login now has no path to analytics access at all, under any role switch —
-- not because inheritance is off, but because no membership exists to switch into.

-- ---------------------------------------------------------------------------
-- Base table privileges
-- ---------------------------------------------------------------------------

REVOKE ALL ON sales, organizations, products, zip_territory, org_scope, users, role_scope
    FROM PUBLIC;

-- Reference data: unrestricted for every analytics tier
GRANT SELECT ON products, zip_territory TO app_exec, app_director, app_ram;

-- organizations: all columns, row-scoped by RLS below (no sensitive columns here)
GRANT SELECT ON organizations TO app_exec, app_director, app_ram;

-- org_scope / role_scope: needed directly by the RLS policies' EXISTS subqueries — see
-- design note above for why org_scope is a plain GRANT rather than a SECURITY DEFINER
-- function. role_scope only ever contains role-name -> territory/region rows (no sales/
-- org data), so granting SELECT on it carries the same low-sensitivity trade-off as
-- org_scope already does.
GRANT SELECT ON org_scope, role_scope TO app_exec, app_director, app_ram;

-- sales: app_exec gets every column including wac.
GRANT SELECT ON sales TO app_exec;

-- app_director / app_ram (and everything granted membership in them) get every column
-- EXCEPT wac — the database itself has no column called "wac" as far as these roles are
-- concerned.
GRANT SELECT (
    sale_id, org_id, ndc, drug_name, data_source, brand_flag,
    pack_units, total_mg, transaction_date, week_ending_date,
    state, specialty, period_wk, period_mo, period_qtr, wk_offset, mo_offset
) ON sales TO app_director, app_ram;

-- users: only app_login (the base, auth-only connection) can read it, for the /login
-- lookup. app_exec/app_director/app_ram and every per-scope role — the identities under
-- which LLM-generated SQL executes — are never granted access, so a prompt-injected
-- "SELECT * FROM users" fails at the DB regardless of role.
GRANT SELECT ON users TO app_login;

-- Cleanup from an earlier revision of this file (see design note above).
DROP FUNCTION IF EXISTS org_in_scope(TEXT);

-- ---------------------------------------------------------------------------
-- Row-level security
-- ---------------------------------------------------------------------------

ALTER TABLE sales ENABLE ROW LEVEL SECURITY;
ALTER TABLE sales FORCE ROW LEVEL SECURITY;
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations FORCE ROW LEVEL SECURITY;

-- session_user (not current_user): fixed for the life of the connection by which role it
-- authenticated as, and unaffected by SET ROLE even in principle — see the C1 note above.
DROP POLICY IF EXISTS sales_scope ON sales;
CREATE POLICY sales_scope ON sales
    USING (
        EXISTS (
            SELECT 1 FROM org_scope os
            JOIN role_scope rs ON rs.pg_role_name = session_user
            WHERE os.org_id = sales.org_id
              AND (
                  (rs.scope_type = 'region' AND os.region_name = rs.scope_name)
                  OR
                  (rs.scope_type = 'territory' AND os.territory_name = rs.scope_name)
              )
        )
    );

DROP POLICY IF EXISTS orgs_scope ON organizations;
CREATE POLICY orgs_scope ON organizations
    USING (
        EXISTS (
            SELECT 1 FROM org_scope os
            JOIN role_scope rs ON rs.pg_role_name = session_user
            WHERE os.org_id = organizations.org_id
              AND (
                  (rs.scope_type = 'region' AND os.region_name = rs.scope_name)
                  OR
                  (rs.scope_type = 'territory' AND os.territory_name = rs.scope_name)
              )
        )
    );

-- app_exec bypasses both policies via BYPASSRLS (granted above), so it needs no policy
-- clause of its own and always sees every row.
