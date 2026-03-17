# lb_multi_drift

A Python tool that snapshots a golden (reference) database, detects schema drift across multiple target environments, auto-remediates each one using Liquibase, and confirms alignment — producing a full audit trail of reports and DDL for every environment processed.

---

## How it works

1. Snapshots the golden database as a reference point
2. Loops through each target database in config
3. Runs a diff against the golden snapshot to detect drift
4. Generates a remediation changelog (DDL) if drift is found
5. Applies the changelog to bring the target in line
6. Re-diffs to confirm no drift remains
7. Writes a summary across all environments

---

## Prerequisites

- Python 3.8+
- [Liquibase Secure](https://www.liquibase.com) installed and on your `$PATH`
- A valid Liquibase license key
- Network access to all databases in config

---

## Setup

```bash
# Clone / download the project
cd lb_multi_drift

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install pyyaml

# Set your Liquibase license key
export LIQUIBASE_LICENSE_KEY=<your-key>
```

To persist the license key across sessions:

```bash
echo 'export LIQUIBASE_LICENSE_KEY=<your-key>' >> ~/.zshrc
source ~/.zshrc
```

---

## Configuration

Edit `config.yaml` before running:

```yaml
output_dir: output          # where all output is written

golden:
  url: "jdbc:postgresql://localhost:5433/golden"
  username: postgres
  password: secret

targets:
  - name: db1
    url: "jdbc:postgresql://localhost:5433/db1"
    username: postgres
    password: secret
  - name: db2
    url: "jdbc:postgresql://localhost:5433/db2"
    username: postgres
    password: secret
```

Add as many targets as needed. Each target is processed independently.

---

## Usage

```bash
python3 multi_env_drift.py config.yaml
```

---

## Output structure

A timestamped folder is created under `output/` for each target:

```
output/
  summary.txt
  golden_snapshot.json
  golden_snapshot.log
  20260312_163959_db1/
    reports/
      diff_before.html      ← drift report before remediation
      diff_after.html       ← diff report confirming alignment
      update_report.html    ← changelog execution report
    ddl/
      remediation.sql       ← generated DDL to fix drift
      recheck.sql           ← post-remediation verification changelog
    logs/
      diff_before.txt
      diff_changelog.txt
      update.txt
      recheck.txt
  20260312_163959_db2/
    ...
```

---

## Summary output

After all targets are processed, a summary is printed and written to `output/summary.txt`:

```
====================================================
  DRIFT REMEDIATION SUMMARY
====================================================
  Environments checked   : 5
  Clean (no drift)       : 1
  Drift detected         : 4
  Successfully remediated: 4
  Errors                 : 0
====================================================

  Per-environment results:
    db1                  ✅ CLEAN
    db2                  ✅ REMEDIATED
    db3                  ✅ REMEDIATED
    db4                  ✅ REMEDIATED
    db5                  ✅ REMEDIATED
====================================================
```

---

## Local test environment (Docker)

A Docker setup is included to spin up a local Postgres instance with one golden database and five drifted targets.

```bash
# Start the environment
docker-compose up -d

# Verify drift was injected correctly
docker logs lb_drift_demo
```

The init script creates six databases and injects a different type of drift into each of `db1`–`db5`:

| Database | Drift type |
|----------|------------|
| golden   | Clean reference — no drift |
| db1      | Extra table added (`audit_log`) |
| db2      | Extra column on `customers` (`phone`) |
| db3      | `products` table dropped |
| db4      | Rogue index + extra staging table |
| db5      | Column added, table dropped, new table added |

> The Docker setup uses port `5433` to avoid conflicts with any local Postgres instance on `5432`.

To reset and re-inject drift:

```bash
docker-compose down -v
docker-compose up -d
```

---

## Notes

- `databasechangelog` and `databasechangeloglock` tables are excluded from all diffs automatically
- Liquibase HTML reports do not auto-open — all output is silent during the run
- The golden snapshot is stored as `golden_snapshot.json` in the output directory and reused across all target comparisons in a single run
- This tool is designed for PostgreSQL. For SQL Server, update the JDBC URLs and change `offline:postgresql` to `offline:mssql` in `multi_env_drift.py`