-- Secondary indexes — applied AFTER bulk COPY (see db/load_data.py) so the 2M-row
-- sales load isn't slowed by index maintenance during insert.

-- sales: date/time filtering, source/brand filtering, org and product joins
CREATE INDEX IF NOT EXISTS idx_sales_org_id        ON sales (org_id);
CREATE INDEX IF NOT EXISTS idx_sales_ndc            ON sales (ndc);
CREATE INDEX IF NOT EXISTS idx_sales_mo_offset      ON sales (mo_offset);
CREATE INDEX IF NOT EXISTS idx_sales_wk_offset      ON sales (wk_offset);
CREATE INDEX IF NOT EXISTS idx_sales_period_mo      ON sales (period_mo);
CREATE INDEX IF NOT EXISTS idx_sales_period_qtr     ON sales (period_qtr);
CREATE INDEX IF NOT EXISTS idx_sales_source_brand   ON sales (data_source, brand_flag);
CREATE INDEX IF NOT EXISTS idx_sales_transaction_dt ON sales (transaction_date);

-- organizations: hierarchy rollups and zip -> territory join
CREATE INDEX IF NOT EXISTS idx_orgs_zip             ON organizations (zip);
CREATE INDEX IF NOT EXISTS idx_orgs_grandparent     ON organizations (grandparent_org_id);
CREATE INDEX IF NOT EXISTS idx_orgs_parent          ON organizations (parent_org_id);
CREATE INDEX IF NOT EXISTS idx_orgs_gpo             ON organizations (gpo_name);

-- products: market classification lookups
CREATE INDEX IF NOT EXISTS idx_products_subcategory ON products (market_subcategory);
CREATE INDEX IF NOT EXISTS idx_products_category    ON products (market_category);
CREATE INDEX IF NOT EXISTS idx_products_brand_flag  ON products (brand_flag);

-- zip_territory: territory/region lookups
CREATE INDEX IF NOT EXISTS idx_zipterr_territory    ON zip_territory (territory_name);
CREATE INDEX IF NOT EXISTS idx_zipterr_region       ON zip_territory (region_name);

-- org_scope: backs the RLS scope-check function (org_id is already PK/unique)
CREATE INDEX IF NOT EXISTS idx_orgscope_territory   ON org_scope (territory_name);
CREATE INDEX IF NOT EXISTS idx_orgscope_region      ON org_scope (region_name);

ANALYZE sales;
ANALYZE organizations;
ANALYZE products;
ANALYZE zip_territory;
ANALYZE org_scope;
