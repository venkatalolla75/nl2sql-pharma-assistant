-- Database-level access control.
--
-- Design: the backend connects as ONE login role (app_login, created + password-set by
-- db/load_data.py from an env var — never hardcoded here). app_login itself is granted
-- nothing beyond CONNECT + SELECT on the `users` table (for the login/auth lookup only —
-- the LLM never sees or queries `users`). To run an analytics query, the backend issues
--   SET LOCAL ROLE app_exec | app_director | app_ram
-- inside the request's transaction, based on the authenticated user's role. Because the
-- grants below are WITH INHERIT FALSE, app_login has NO analytics access until it does
-- so explicitly — a bug that skips the SET ROLE step fails closed, not open.
--
-- Two independent layers enforce scoping once a role is active:
--   1. Column-level GRANTs: app_director/app_ram are never granted SELECT on sales.wac.
--      Even `SELECT *` or `SELECT wac` fails with a Postgres permission error — this is
--      enforced by the database, not by the prompt or the SQL validator.
--   2. Row-level security (RLS): app_director/app_ram only see sales/organizations rows
--      whose territory/region matches session GUCs (app.current_territory /
--      app.current_region) set by the backend from the authenticated user's row. app_exec
--      has BYPASSRLS and sees everything.
--
-- org_scope (org_id -> territory_name/region_name, see 01_schema.sql) backs the RLS
-- check. It is deliberately NOT granted to app_director/app_ram directly — that would
-- let a RAM run `SELECT DISTINCT territory_name FROM org_scope` and enumerate every
-- territory/org in the company, which is itself a scope leak. Instead the policies call
-- a SECURITY DEFINER function that checks org_scope with the function owner's privileges,
-- so app_director/app_ram can ask "is org X in my scope?" without being able to read the
-- table's rows directly.

-- ---------------------------------------------------------------------------
-- Roles
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_login') THEN
        CREATE ROLE app_login NOLOGIN;  -- LOGIN + PASSWORD set later by load_data.py from env
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_exec') THEN
        CREATE ROLE app_exec NOLOGIN BYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_director') THEN
        CREATE ROLE app_director NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_ram') THEN
        CREATE ROLE app_ram NOLOGIN;
    END IF;
END $$;

GRANT app_exec     TO app_login WITH INHERIT FALSE;
GRANT app_director TO app_login WITH INHERIT FALSE;
GRANT app_ram      TO app_login WITH INHERIT FALSE;

-- ---------------------------------------------------------------------------
-- Base table privileges
-- ---------------------------------------------------------------------------

REVOKE ALL ON sales, organizations, products, zip_territory, org_scope, users FROM PUBLIC;

-- Reference data: unrestricted for every analytics tier
GRANT SELECT ON products, zip_territory TO app_exec, app_director, app_ram;

-- organizations: all columns, row-scoped by RLS below (no sensitive columns here)
GRANT SELECT ON organizations TO app_exec, app_director, app_ram;

-- org_scope: intentionally NOT granted here — see design note above. Accessed only
-- through the SECURITY DEFINER function org_in_scope() below.

-- sales: app_exec gets every column including wac.
GRANT SELECT ON sales TO app_exec;

-- app_director / app_ram get every column EXCEPT wac — the database itself has no
-- column called "wac" as far as these roles are concerned.
GRANT SELECT (
    sale_id, org_id, ndc, drug_name, data_source, brand_flag,
    pack_units, total_mg, transaction_date, week_ending_date,
    state, specialty, period_wk, period_mo, period_qtr, wk_offset, mo_offset
) ON sales TO app_director, app_ram;

-- users: only app_login (the base, pre-SET-ROLE connection) can read it, for auth lookup.
-- app_exec/app_director/app_ram — the roles under which LLM-generated SQL executes —
-- are never granted access, so a prompt-injected "SELECT * FROM users" fails at the DB.
GRANT SELECT ON users TO app_login;

-- ---------------------------------------------------------------------------
-- Scope-check function (SECURITY DEFINER — owned by the bootstrapping role, typically
-- the default `postgres` superuser or whichever role ran this script)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION org_in_scope(p_org_id TEXT)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1 FROM org_scope s
        WHERE s.org_id = p_org_id
          AND (
              (current_setting('app.current_role', true) = 'director'
                  AND s.region_name = current_setting('app.current_region', true))
              OR
              (current_setting('app.current_role', true) = 'ram'
                  AND s.territory_name = current_setting('app.current_territory', true))
          )
    );
$$;

REVOKE ALL ON FUNCTION org_in_scope(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION org_in_scope(TEXT) TO app_director, app_ram;

-- ---------------------------------------------------------------------------
-- Row-level security
-- ---------------------------------------------------------------------------

ALTER TABLE sales ENABLE ROW LEVEL SECURITY;
ALTER TABLE sales FORCE ROW LEVEL SECURITY;
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sales_scope ON sales;
CREATE POLICY sales_scope ON sales
    USING ( org_in_scope(sales.org_id) );

DROP POLICY IF EXISTS orgs_scope ON organizations;
CREATE POLICY orgs_scope ON organizations
    USING ( org_in_scope(organizations.org_id) );

-- app_exec bypasses both policies via BYPASSRLS (granted above), so it needs no policy
-- clause of its own and always sees every row.
