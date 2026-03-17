#!/bin/bash
set -e

# ---------------------------------------------------------
# 01_setup.sh
# Creates 6 databases, applies a shared baseline to all,
# then injects a different type of drift into each of db1-db5.
# golden remains untouched — it is the reference.
# ---------------------------------------------------------

BASELINE=$(cat <<'EOSQL'
  CREATE TABLE customers (
    id         SERIAL PRIMARY KEY,
    first_name VARCHAR(50),
    last_name  VARCHAR(50),
    email      VARCHAR(100),
    created_at TIMESTAMP DEFAULT now()
  );
  CREATE TABLE orders (
    id          SERIAL PRIMARY KEY,
    customer_id INTEGER,
    order_date  TIMESTAMP,
    total       DECIMAL(10,2)
  );
  CREATE TABLE products (
    id         SERIAL PRIMARY KEY,
    sku        VARCHAR(40),
    name       VARCHAR(100),
    price      DECIMAL(10,2),
    created_at TIMESTAMP DEFAULT now()
  );
  CREATE TABLE invoices (
    id       SERIAL PRIMARY KEY,
    order_id INTEGER,
    issued_at TIMESTAMP,
    amount   DECIMAL(10,2)
  );
EOSQL
)

echo "Creating databases..."
for db in golden db1 db2 db3 db4 db5; do
  psql -v ON_ERROR_STOP=1 -U postgres -c "CREATE DATABASE $db;"
  echo "  ✅ $db created"
done

echo "Applying baseline to all databases..."
for db in golden db1 db2 db3 db4 db5; do
  psql -v ON_ERROR_STOP=1 -U postgres -d "$db" -c "$BASELINE"
  echo "  ✅ $db baseline applied"
done

echo "Injecting drift into db1–db5..."

# db1: extra table created out of band
psql -U postgres -d db1 <<'SQL'
  CREATE TABLE audit_log (
    id         SERIAL PRIMARY KEY,
    event      TEXT,
    actor      VARCHAR(100),
    created_at TIMESTAMP DEFAULT now()
  );
SQL
echo "  ⚠️  db1: extra table (audit_log)"

# db2: extra column added to customers
psql -U postgres -d db2 -c "ALTER TABLE customers ADD COLUMN phone VARCHAR(20);"
echo "  ⚠️  db2: extra column on customers (phone)"

# db3: products table dropped entirely
psql -U postgres -d db3 -c "DROP TABLE products;"
echo "  ⚠️  db3: products table dropped"

# db4: rogue index + extra table
psql -U postgres -d db4 <<'SQL'
  CREATE INDEX idx_orders_customer ON orders(customer_id);
  CREATE TABLE temp_staging (
    id      SERIAL PRIMARY KEY,
    payload TEXT,
    loaded_at TIMESTAMP DEFAULT now()
  );
SQL
echo "  ⚠️  db4: rogue index + temp_staging table"

# db5: combination — extra column, dropped table, new table
psql -U postgres -d db5 <<'SQL'
  ALTER TABLE customers ADD COLUMN loyalty_tier VARCHAR(10);
  DROP TABLE products;
  CREATE TABLE promo_codes (
    id       SERIAL PRIMARY KEY,
    code     VARCHAR(20),
    discount DECIMAL(5,2),
    expires  TIMESTAMP
  );
SQL
echo "  ⚠️  db5: extra column + dropped table + new table (promo_codes)"

echo ""
echo "Setup complete. Drift summary:"
echo "  golden  → clean reference"
echo "  db1     → extra table (audit_log)"
echo "  db2     → extra column on customers"
echo "  db3     → products table missing"
echo "  db4     → rogue index + temp_staging table"
echo "  db5     → column added, products dropped, promo_codes added"