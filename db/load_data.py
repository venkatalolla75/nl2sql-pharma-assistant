"""
Load the full generated dataset into Postgres and apply the security model.

Usage:
    python3 db/load_data.py

Env vars (all required, read at runtime — nothing here is hardcoded):
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
        -> superuser/bootstrap connection used to create schema, roles, and load data.
    APP_DB_PASSWORD
        -> password to set on the app_login role that the FastAPI backend connects as.
    DEMO_USER_PASSWORD
        -> shared demo password for the 23 seeded users (see db/seed_users.py). Never
           committed; must be supplied at load time.

Order of operations:
    1. Run 01_schema.sql (tables, PKs/FKs only)
    2. Run 02_security.sql (roles, grants, RLS, org_in_scope() function)
    3. Set app_login's password from APP_DB_PASSWORD (LOGIN granted here, not in the SQL file)
    4. COPY organizations, products, zip_territory, sales from schema/generated/*.csv
    5. Insert the 23 seeded users with bcrypt-hashed passwords
    6. Populate org_scope from organizations JOIN zip_territory ON zip
    7. Run 03_indexes.sql (secondary indexes + ANALYZE)
"""

import os
import sys
from pathlib import Path

import bcrypt
import psycopg
from psycopg import sql

ROOT = Path(__file__).parent.parent
DB_DIR = ROOT / "db"
DATA_DIR = ROOT / "schema" / "generated"

SEEDED_USERS = [
    # user_id, email, full_name, role, territory_name, region_name, can_view_wac
    ("U001", "sarah.chen@novapharma.com", "Sarah Chen", "exec", None, None, 1),
    ("U002", "michael.torres@novapharma.com", "Michael Torres", "exec", None, None, 1),
    ("U003", "jennifer.walsh@novapharma.com", "Jennifer Walsh", "director", None, "Northeast", 0),
    ("U004", "david.park@novapharma.com", "David Park", "director", None, "Mid-Atlantic", 0),
    ("U005", "lisa.johnson@novapharma.com", "Lisa Johnson", "director", None, "Southeast", 0),
    ("U006", "robert.kim@novapharma.com", "Robert Kim", "director", None, "Midwest", 0),
    ("U007", "maria.garcia@novapharma.com", "Maria Garcia", "director", None, "South Central", 0),
    ("U008", "james.anderson@novapharma.com", "James Anderson", "director", None, "West", 0),
    ("U009", "amy.nguyen@novapharma.com", "Amy Nguyen", "ram", "New York Metro", "Northeast", 0),
    ("U010", "brian.murphy@novapharma.com", "Brian Murphy", "ram", "New England", "Northeast", 0),
    ("U011", "carlos.rivera@novapharma.com", "Carlos Rivera", "ram", "Mid-Atlantic East", "Mid-Atlantic", 0),
    ("U012", "diana.wright@novapharma.com", "Diana Wright", "ram", "Mid-Atlantic West", "Mid-Atlantic", 0),
    ("U013", "eric.thompson@novapharma.com", "Eric Thompson", "ram", "Southeast Atlantic", "Southeast", 0),
    ("U014", "fiona.davis@novapharma.com", "Fiona Davis", "ram", "Southeast Gulf", "Southeast", 0),
    ("U015", "george.martinez@novapharma.com", "George Martinez", "ram", "Great Lakes East", "Midwest", 0),
    ("U016", "hannah.lee@novapharma.com", "Hannah Lee", "ram", "Great Lakes West", "Midwest", 0),
    ("U017", "ivan.petrov@novapharma.com", "Ivan Petrov", "ram", "Upper Midwest", "Midwest", 0),
    ("U018", "julia.robinson@novapharma.com", "Julia Robinson", "ram", "Texas", "South Central", 0),
    ("U019", "kevin.brown@novapharma.com", "Kevin Brown", "ram", "South Central", "South Central", 0),
    ("U020", "laura.wilson@novapharma.com", "Laura Wilson", "ram", "Pacific Northwest", "West", 0),
    ("U021", "nathan.clark@novapharma.com", "Nathan Clark", "ram", "California North", "West", 0),
    ("U022", "olivia.taylor@novapharma.com", "Olivia Taylor", "ram", "California South", "West", 0),
    ("U023", "patrick.moore@novapharma.com", "Patrick Moore", "ram", "Mountain", "West", 0),
]


def env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"ERROR: required env var {name} is not set.", file=sys.stderr)
        sys.exit(1)
    return val


def run_sql_file(cur, path: Path):
    print(f"  running {path.name} ...")
    cur.execute(path.read_text())


def copy_csv(cur, table: str, columns: list[str], csv_path: Path):
    cols = ", ".join(columns)
    print(f"  loading {csv_path.name} -> {table} ...")
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        next(f)  # skip header
        with cur.copy(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv)") as copy:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                copy.write(chunk)


def main():
    host = env("POSTGRES_HOST")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = env("POSTGRES_DB")
    user = env("POSTGRES_USER")
    password = env("POSTGRES_PASSWORD")
    app_db_password = env("APP_DB_PASSWORD")
    demo_password = env("DEMO_USER_PASSWORD")

    conninfo = f"host={host} port={port} dbname={dbname} user={user} password={password}"

    print("=== Connecting ===")
    with psycopg.connect(conninfo, autocommit=True) as conn:
        with conn.cursor() as cur:
            print("=== Schema ===")
            run_sql_file(cur, DB_DIR / "01_schema.sql")

            print("=== Security (roles, grants, RLS) ===")
            run_sql_file(cur, DB_DIR / "02_security.sql")

            print("=== app_login credentials ===")
            # ALTER ROLE is a utility statement — it doesn't support bind parameters
            # (Postgres rejects "PASSWORD $1"). sql.Literal() safely quotes the value
            # as a SQL string constant instead.
            cur.execute(
                sql.SQL("ALTER ROLE app_login WITH LOGIN PASSWORD {}").format(
                    sql.Literal(app_db_password)
                )
            )

            print("=== Clearing existing data (safe to re-run against an already-loaded "
                  "DB, e.g. redeploying EC2 against the same RDS instance) ===")
            cur.execute(
                "TRUNCATE TABLE sales, org_scope, organizations, products, zip_territory "
                "RESTART IDENTITY CASCADE"
            )

            print("=== Loading reference + organization data ===")
            copy_csv(
                cur, "organizations",
                ["org_id", "org_name", "org_type", "org_status", "org_archetype",
                 "specialty", "address_line1", "city", "state", "zip",
                 "parent_org_id", "parent_org_name", "grandparent_org_id",
                 "grandparent_org_name", "gpo_name", "is_340b"],
                DATA_DIR / "organizations.csv",
            )
            copy_csv(
                cur, "products",
                ["ndc", "drug_name", "generic_name", "strength", "form", "brand_flag",
                 "specialty", "market_category", "market_subcategory",
                 "unit_conversion_factor", "mg_equivalent"],
                DATA_DIR / "products.csv",
            )
            copy_csv(
                cur, "zip_territory",
                ["zip", "state", "territory_number", "territory_name",
                 "region_number", "region_name"],
                DATA_DIR / "zip_territory.csv",
            )

            print("=== Loading sales (2M rows — this takes a few minutes) ===")
            copy_csv(
                cur, "sales",
                ["org_id", "ndc", "drug_name", "data_source", "brand_flag",
                 "pack_units", "total_mg", "wac", "transaction_date", "week_ending_date",
                 "state", "specialty", "period_wk", "period_mo", "period_qtr",
                 "wk_offset", "mo_offset"],
                DATA_DIR / "sales.csv",
            )

            print("=== Seeding users ===")
            pw_hash = bcrypt.hashpw(demo_password.encode(), bcrypt.gensalt()).decode()
            cur.executemany(
                """
                INSERT INTO users
                    (user_id, email, full_name, role, territory_name, region_name,
                     can_view_wac, password_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                [(u[0], u[1], u[2], u[3], u[4], u[5], u[6], pw_hash) for u in SEEDED_USERS],
            )

            print("=== Populating org_scope ===")
            cur.execute(
                """
                INSERT INTO org_scope (org_id, territory_name, region_name)
                SELECT o.org_id, zt.territory_name, zt.region_name
                FROM organizations o
                LEFT JOIN zip_territory zt ON zt.zip = o.zip
                ON CONFLICT (org_id) DO UPDATE
                    SET territory_name = EXCLUDED.territory_name,
                        region_name = EXCLUDED.region_name
                """
            )

            print("=== Indexes ===")
            run_sql_file(cur, DB_DIR / "03_indexes.sql")

    print("\nDone. Seeded users all share the demo password you set in DEMO_USER_PASSWORD.")


if __name__ == "__main__":
    main()
