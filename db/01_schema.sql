-- Pharmaceutical Sales Database — PostgreSQL schema
-- Adapted from schema/create_tables.sql (SQLite) for Postgres.
-- PKs/FKs only here; secondary indexes are added AFTER bulk load (see 03_indexes.sql)
-- so the initial COPY of 2M sales rows isn't slowed by index maintenance.

CREATE TABLE IF NOT EXISTS organizations (
    org_id                TEXT PRIMARY KEY,
    org_name              TEXT NOT NULL,
    org_type              TEXT NOT NULL,
    org_status            TEXT NOT NULL,
    org_archetype         TEXT,
    specialty             TEXT,
    address_line1         TEXT,
    city                  TEXT,
    state                 TEXT,
    zip                   TEXT,
    parent_org_id         TEXT,
    parent_org_name       TEXT,
    grandparent_org_id    TEXT,
    grandparent_org_name  TEXT,
    gpo_name              TEXT,
    is_340b               INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    ndc                     TEXT PRIMARY KEY,
    drug_name               TEXT NOT NULL,
    generic_name             TEXT NOT NULL,
    strength                TEXT,
    form                    TEXT,
    brand_flag              INTEGER NOT NULL,
    specialty                TEXT,
    market_category          TEXT,
    market_subcategory       TEXT,
    unit_conversion_factor   NUMERIC,
    mg_equivalent            NUMERIC
);

CREATE TABLE IF NOT EXISTS zip_territory (
    zip                 TEXT PRIMARY KEY,
    state               TEXT NOT NULL,
    territory_number    TEXT NOT NULL,
    territory_name      TEXT NOT NULL,
    region_number       TEXT,
    region_name         TEXT
);

CREATE TABLE IF NOT EXISTS sales (
    sale_id             BIGSERIAL PRIMARY KEY,
    org_id              TEXT NOT NULL REFERENCES organizations(org_id),
    ndc                 TEXT NOT NULL REFERENCES products(ndc),
    drug_name           TEXT NOT NULL,
    data_source         TEXT NOT NULL,
    brand_flag          INTEGER NOT NULL,
    pack_units          NUMERIC,
    total_mg            NUMERIC,
    wac                 NUMERIC,
    transaction_date    DATE,
    week_ending_date    DATE,
    state               TEXT,
    specialty            TEXT,
    period_wk           TEXT,
    period_mo           TEXT,
    period_qtr          TEXT,
    wk_offset           INTEGER,
    mo_offset           INTEGER
);

CREATE TABLE IF NOT EXISTS users (
    user_id             TEXT PRIMARY KEY,
    email               TEXT NOT NULL UNIQUE,
    full_name           TEXT NOT NULL,
    role                TEXT NOT NULL CHECK (role IN ('exec', 'director', 'ram')),
    territory_name      TEXT,
    region_name         TEXT,
    can_view_wac        INTEGER DEFAULT 0,
    password_hash       TEXT NOT NULL
);

-- Precomputed org -> territory/region lookup (organizations has no territory columns;
-- territory is only derivable via zip -> zip_territory). Populated once after data load
-- by db/load_data.py. Backs the RLS policies in 02_security.sql with an indexed join
-- instead of a live organizations JOIN zip_territory on every row-security check.
CREATE TABLE IF NOT EXISTS org_scope (
    org_id          TEXT PRIMARY KEY REFERENCES organizations(org_id),
    territory_name  TEXT,
    region_name     TEXT
);

-- Maps a per-scope Postgres LOGIN role (app_ram__<territory>, app_director__<region>) to
-- the territory/region it's allowed to see. Backs the RLS policies in 02_security.sql,
-- keyed on session_user rather than a settable session GUC — see that file's design note
-- and DESIGN.md's C1 writeup for why. Populated by db/load_data.py once zip_territory's
-- distinct territory/region names are known (02_security.sql runs before any data is
-- loaded, so it can't populate this itself).
CREATE TABLE IF NOT EXISTS role_scope (
    pg_role_name  TEXT PRIMARY KEY,
    scope_type    TEXT NOT NULL CHECK (scope_type IN ('territory', 'region')),
    scope_name    TEXT NOT NULL
);
