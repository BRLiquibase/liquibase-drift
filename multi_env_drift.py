#!/usr/bin/env python3
"""
multi_env_drift.py
Snapshot a golden DB, find drift across target environments, remediate, confirm.
Usage: python multi_env_drift.py [config.yaml]
"""

import os, sys, subprocess, datetime
from pathlib import Path
import yaml

SNAPSHOT_FILE = "golden_snapshot.json"


def ts():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def mkdirp(p):
    Path(p).mkdir(parents=True, exist_ok=True)
    return p


def lb(global_args, command, cmd_args, cwd, log_path=None):
    """Run Liquibase silently. Returns (returncode, combined_output).
    global_args come before the command, cmd_args after."""
    cmd = ["liquibase"] + global_args + [command] + cmd_args
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    if log_path:
        Path(log_path).write_text(out, encoding="utf-8")
    return r.returncode, out


def has_changesets(path):
    try:
        return "-- changeset" in Path(path).read_text(encoding="utf-8").lower()
    except FileNotFoundError:
        return False


def snapshot_golden(cfg, workdir):
    print("📸 Snapshotting golden environment...")
    snap = str(Path(workdir) / SNAPSHOT_FILE)
    rc, out = lb(
        global_args=[
            "--reports-enabled=false",
            f"--url={cfg['url']}",
            f"--username={cfg['username']}",
            f"--password={cfg['password']}",
        ],
        command="snapshot",
        cmd_args=[
            "--snapshot-format=json",
            f"--outputFile={snap}",
        ],
        cwd=workdir,
        log_path=str(Path(workdir) / "golden_snapshot.log")
    )

    if rc != 0:
        print(f"❌ Golden snapshot failed. Check {workdir}/golden_snapshot.log", file=sys.stderr)
        sys.exit(rc)

    print("✅ Golden snapshot saved.")
    return snap


def process_target(target, workdir):
    name = target["name"]
    folder = mkdirp(str(Path(workdir) / f"{ts()}_{name}"))
    reports_dir = mkdirp(str(Path(folder) / "reports"))
    ddl_dir     = mkdirp(str(Path(folder) / "ddl"))
    logs_dir    = mkdirp(str(Path(folder) / "logs"))
    ref_url = f"offline:postgresql?snapshot={SNAPSHOT_FILE}"
    changelog_path = str(Path(ddl_dir) / "remediation.sql")
    result = {"name": name, "drift": False, "remediated": False, "error": False, "folder": folder}

    print(f"\n🔍 [{name}] Checking for drift...")

    conn = [
        f"--url={target['url']}",
        f"--username={target['username']}",
        f"--password={target['password']}",
    ]
    report_args = ["--reports-enabled=true", "--reports-open=false"]
    exclude = ["--exclude-objects=table:databasechangelog,table:databasechangeloglock"]

    # Diff before — save report + log
    lb(
        global_args=report_args + [f"--report-path={reports_dir}/", "--report-name=diff_before"] + conn + [f"--reference-url={ref_url}"] + exclude,
        command="diff",
        cmd_args=[],
        cwd=workdir, log_path=f"{logs_dir}/diff_before.txt"
    )

    # Generate diff-changelog — presence of changesets = drift
    lb(
        global_args=["--reports-enabled=false"] + conn + [f"--reference-url={ref_url}"] + exclude,
        command="diff-changelog",
        cmd_args=["--diff-types=tables,columns,indexes", f"--changeLogFile={changelog_path}"],
        cwd=workdir, log_path=f"{logs_dir}/diff_changelog.txt"
    )

    if not has_changesets(changelog_path):
        lb(
            global_args=report_args + [f"--report-path={reports_dir}/", "--report-name=diff_before"] + conn + [f"--reference-url={ref_url}"] + exclude,
            command="diff",
            cmd_args=[],
            cwd=workdir, log_path=f"{logs_dir}/diff_before.txt"
        )
        print(f"  ✅ [{name}] No drift detected.")
        return result

    result["drift"] = True
    print(f"  ⚠️  [{name}] Drift detected. Applying remediation...")

    # Apply remediation changelog
    rc, _ = lb(
        global_args=report_args + [f"--report-path={reports_dir}/", "--report-name=update_report", f"--search-path={ddl_dir}"] + conn,
        command="update",
        cmd_args=[f"--changeLogFile=remediation.sql"],
        cwd=workdir, log_path=f"{logs_dir}/update.txt"
    )

    if rc != 0:
        print(f"  ❌ [{name}] Remediation failed. See {logs_dir}/update.txt")
        result["error"] = True
        return result

    # Diff after — confirm alignment (report)
    lb(
        global_args=report_args + [f"--report-path={reports_dir}/", "--report-name=diff_after"] + conn + [f"--reference-url={ref_url}"] + exclude,
        command="diff",
        cmd_args=[],
        cwd=workdir, log_path=f"{logs_dir}/diff_after.txt"
    )

    # Re-run diff-changelog to confirm no drift remains
    recheck_path = str(Path(ddl_dir) / "recheck.sql")
    lb(
        global_args=["--reports-enabled=false"] + conn + [f"--reference-url={ref_url}"] + exclude,
        command="diff-changelog",
        cmd_args=["--diff-types=tables,columns,indexes", f"--changeLogFile={recheck_path}"],
        cwd=workdir, log_path=f"{logs_dir}/recheck.txt"
    )

    if has_changesets(recheck_path):
        print(f"  ⚠️  [{name}] Remediation incomplete — drift remains. See {ddl_dir}/recheck.sql")
        result["remediated"] = False
        result["error"] = True
    else:
        result["remediated"] = True
        print(f"  ✅ [{name}] Remediated and verified clean. Reports → {reports_dir}/")
    return result


def write_summary(results, workdir):
    total      = len(results)
    drifted    = sum(1 for r in results if r["drift"])
    remediated = sum(1 for r in results if r["remediated"])
    errors     = sum(1 for r in results if r["error"])
    clean      = total - drifted

    lines = [
        "",
        "=" * 52,
        "  DRIFT REMEDIATION SUMMARY",
        "=" * 52,
        f"  Environments checked   : {total}",
        f"  Clean (no drift)       : {clean}",
        f"  Drift detected         : {drifted}",
        f"  Successfully remediated: {remediated}",
        f"  Errors                 : {errors}",
        "=" * 52,
        "",
        "  Per-environment results:",
    ]

    for r in results:
        if r["error"]:
            status = "❌ ERROR"
        elif r["drift"] and r["remediated"]:
            status = "✅ REMEDIATED"
        elif r["drift"]:
            status = "⚠️  DRIFT - NOT FIXED"
        else:
            status = "✅ CLEAN"
        lines.append(f"    {r['name']:<20} {status}")
        if r.get("folder"):
            lines.append(f"      Reports: {r['folder']}/")

    lines += ["", "=" * 52, ""]
    output = "\n".join(lines)

    for line in lines:
        print(line)

    summary_path = Path(workdir) / "summary.txt"
    summary_path.write_text(output, encoding="utf-8")
    print(f"Summary written → {summary_path}\n")


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))

    workdir = mkdirp(os.path.abspath(cfg.get("output_dir", "output")))

    snapshot_golden(cfg["golden"], workdir)

    results = [process_target(t, workdir) for t in cfg["targets"]]

    write_summary(results, workdir)


if __name__ == "__main__":
    main()