# AGENTS.md — Sentinel

Guidance for AI coding agents (and humans) continuing work on **Sentinel**, a
local, defensive threat scanner for Windows 11. Read this file fully before
editing. It encodes the architecture, the hard rules, and the “definition of
done” so you can extend the project without breaking its safety guarantees.

> Companion docs: **README.md** (user-facing usage) and **DESIGN.md** (the
> dashboard design system). When you touch the web UI, follow DESIGN.md.

---

## 1. What Sentinel is (and is not)

Sentinel hunts a specific class of problem: a hidden process — usually a
cryptominer or a malicious npm supply-chain payload — that spikes CPU on a
cycle, stutters games during calm moments, and phones home. It scans from five
independent **perspectives**, explains every finding in plain language,
recommends an action, and removes threats **reversibly**.

- It **is** a focused triage + remediation tool with a human in the loop.
- It is **not** a real-time AV/EDR, a kernel driver, or a replacement for
  Microsoft Defender. Do not try to make it one.

### Non-negotiable product rules

1. **Read-first.** Scanning never modifies the system. Only the remediation
   layer mutates state, and only when explicitly invoked.
2. **Everything is reversible.** Never hard-delete. Files go to the encrypted
   quarantine vault; registry values are backed up; scheduled tasks are
   disabled, not deleted. Every action yields a restore token.
3. **The human decides.** The scanner marks + recommends. Automatic mode may
   only act on findings that are `verdict == malicious` **and**
   `confidence >= 0.85` (see `RemediationEngine.select_auto`). Never lower this
   silently.
4. **No raw internals in user-facing surfaces.** Map enums to plain language in
   the UI/report (see DESIGN.md). Stack traces never reach the user.
5. **Stay offline-capable.** Scans must work with no network. Threat-intel
   feeds are an enrichment, never a hard dependency.

---

## 2. Tech stack & environment

- **Python 3.10+**, standard library first. Pydantic v2 for models, PyYAML for
  config.
- **Optional dependencies are always guarded** behind `try/except ImportError`
  so the package imports and the self-test runs even when they are absent:
  `psutil`, `fastapi`, `uvicorn`, `httpx`, `cryptography`, `rich`.
  - If you add a dependency, add it to `requirements.txt` **and** guard the
    import. A missing optional dep must degrade gracefully (skip a scanner,
    fall back to base64 vault, etc.), never crash the whole tool.
- **Frontend** is intentionally dependency-free: vanilla HTML/CSS/JS served by
  FastAPI under `sentinel/ui/static/`. Keep it buildless unless DESIGN.md
  says otherwise.
- **Target OS is Windows 11.** Code must still *import and unit-test* on Linux
  (the dev/CI sandbox). Gate Windows-only calls (registry, signtool, WMI)
  behind `platform_utils.is_windows()` and provide a no-op/empty result
  elsewhere.

---

## 3. Directory layout

```
sentinel/
  cli.py                 # argparse entrypoint: scan|remediate|restore|history|serve
  core/
    models.py            # Pydantic models + enums (the shared contract)
    config.py            # Config object + load_config()
    db.py                # SQLite ledger (scans, audit, quarantine)
    intel.py             # ThreatIntel: bundled IOCs + optional feed refresh
    scoring.py           # finalize(): signals -> verdict + confidence + rationale
    orchestrator.py      # fans scanners out across threads, emits events
    platform_utils.py    # OS gates, signature checks, path helpers
  scanners/
    base.py              # Scanner base class / interface
    __init__.py          # SCANNERS registry + TIME_ESTIMATES
    npm_scanner.py        process_scanner.py   network_scanner.py
    persistence_scanner.py  browser_scanner.py
  remediation/
    actions.py           # RemediationEngine.apply() / select_auto()
    quarantine.py        # encrypted vault (Fernet, base64 fallback)
    restore.py           # RestoreManager.restore(token)
  report/
    builder.py           # build_json_report / build_html_report / write_reports
  ui/
    app.py               # FastAPI app + serve(config_path)
    static/              # index.html, app.js, styles.css
  data/intel/            # compromised_npm.json, mining_pools.json, malicious_extensions.json
tests/
  run_selftest.py        # 22-check end-to-end harness (must pass, exit 0)
  sample_node_project/   # synthetic fixtures (no node_modules on disk)
config.yaml              # default configuration
requirements.txt
```

---

## 4. The core contract (`core/models.py`)

Everything flows through **`Finding`**. Do not break this shape — the scanners,
scoring, reports, UI, and DB all depend on it.

```python
Finding(
  id: str,                 # stable per finding
  perspective: Perspective,# npm|process|network|persistence|browser
  title: str,              # plain-language headline
  description: str,        # plain-language detail
  evidence: list[str],     # concrete proof (paths, hashes, ports, versions)
  severity: Severity,      # info|low|medium|high|critical
  confidence: float,       # 0..1
  verdict: Verdict,        # clean|suspicious|malicious
  recommended_action: Action,  # none|monitor|quarantine|kill|disable|uninstall
  target: dict,            # what to act on (e.g. {name, version, file} / {pid} / {key})
  reversible: bool,
  rationale: list[str],    # WHY it was flagged, human-readable
  discovered_at: datetime,
)
# props: .severity_rank, .marker (🔴🟠🟡🟢⚪)
# method: .qualifies_for_auto(min_verdict, min_confidence)
```

Enums: `Perspective`, `Severity` (info<low<medium<high<critical), `Verdict`
(clean<suspicious<malicious), `Action`. `SEVERITY_MARKER` maps severity ->
glyph. **Always add a `rationale` and at least one `evidence` item** when you
emit a finding — the UI and reports surface them, and a finding with no “why”
is an anti-pattern here.

---

## 5. How the pieces talk

### Scanners (`scanners/`)
Each scanner subclasses the base, takes `(config, intel)`, and implements
`scan() -> list[Finding]`. They are **pure detectors**: gather raw signals, hand
them to `scoring.finalize(...)`, return findings. They must never remediate.

```python
from .base import Scanner
class FooScanner(Scanner):
    perspective = "foo"
    def scan(self) -> list[Finding]:
        signals = [(weight, "human reason"), ...]
        return [finalize(draft_finding, signals, hard_malicious=False,
                         suggested_action="quarantine")]
```

### Scoring (`core/scoring.py`)
`finalize(finding, signals, hard_malicious=False, suggested_action=...)` sums
weighted signals into confidence and sets the verdict by threshold:
`>= 0.75 -> malicious`, `>= 0.35 -> suspicious`, else `clean`. `hard_malicious`
forces a malicious verdict for definitive IOCs (e.g. a known-compromised package
version). Keep weights small and additive; a single weak signal (e.g. “in a
suspicious directory”) must **never** be sufficient on its own to raise a
finding — this was a real false-positive bug; preserve the guard.

### Orchestrator (`core/orchestrator.py`)
`Orchestrator(config, intel).run(request, on_event=cb)` runs the requested
perspectives in a `ThreadPoolExecutor` and streams events to `on_event`:
`scan_start`, `perspective_start`, `progress`, `finding`, `perspective_done`,
`perspective_error`, `scan_done`. The UI relies on these exact event names for
live progress — if you add an event type, keep the existing ones intact.

### Remediation (`remediation/`)
`RemediationEngine(config, db).apply(findings, actions=None, make_restore_point=True)`
performs reversible actions and records them; `select_auto(findings, verdict,
confidence)` picks auto-mode targets. `RestoreManager(config, db).restore(token)`
undoes any action. Quarantine uses Fernet when `cryptography` is present and a
base64 fallback otherwise.

### Persistence (`core/db.py`)
SQLite with `scans`, `audit`, `quarantine` tables. The audit log is
append-only — never rewrite history; only add rows / mark restored.

### Reports (`report/builder.py`)
`write_reports(scan, reports_dir, outcomes=None)` emits HTML + JSON. **The HTML
template uses token replacement (`__BODY__`, `__CHIPS__`, ...), NOT
`str.format()`** — the CSS contains literal `{}` braces, so `.format()` will
crash. Do not reintroduce `.format()` on the template.

### CLI / UI
`cli.py` exposes `scan`, `remediate`, `restore`, `history`, `serve`. `serve`
imports `from .ui.app import serve`; `ui/app.py` must keep exporting
`serve(config_path)` and binding to `127.0.0.1` only.

---

## 6. Common tasks (recipes)

### Add a new scan perspective
1. Add the value to the `Perspective` enum in `core/models.py`.
2. Create `scanners/<name>_scanner.py` subclassing `Scanner`.
3. Register it in `scanners/__init__.py` (`SCANNERS`) and add a realistic
   `TIME_ESTIMATES[<name>]` (seconds) — the UI shows this before scanning.
4. Add detection logic that produces `Finding`s via `finalize`.
5. Add fixtures + assertions to `tests/run_selftest.py`.
6. The UI/`/api/perspectives` will pick it up automatically.

### Add / refresh threat intelligence
- Edit the bundled JSON in `sentinel/data/intel/`. Keep entries minimal and
  sourced (add a comment/field noting the campaign + date).
- Feed refresh logic lives in `core/intel.py` and must remain optional.

### Add a remediation action
- Extend the `Action` enum, implement the (reversible!) operation in
  `remediation/actions.py`, and implement its inverse in `restore.py`.
  No action ships without a working restore path + a self-test round-trip.

---

## 7. Definition of done (run before you hand work back)

```bash
python -m compileall -q sentinel              # byte-compiles clean
python -c "import sentinel"                    # imports with NO optional deps
python -m sentinel.cli --help                  # CLI intact
python tests/run_selftest.py                   # 22 checks, exits 0
```

The self-test plants synthetic IOCs (known-bad `chalk@5.6.1`, a Shai-Hulud
`evil-pkg`, a poisoned lockfile) and verifies detection, scoring, reporting, and
a full quarantine→restore round-trip with **zero false positives** on a benign
package. If you add behavior, add a check. Never weaken a check to make it pass.

---

## 8. Coding conventions

- Plain stdlib, type hints, small pure functions. Prefer clarity over cleverness.
- Guard every optional import; degrade gracefully.
- Never write paths containing `node_modules` in tooling that runs in the
  sandbox (it is blocked) — build such fixtures at runtime, as the self-test does.
- User-facing strings are plain language. Internal enum values stay internal;
  translate them at the edge (UI/report/CLI output).
- Keep `127.0.0.1`-only binding for the dashboard. Do not expose it on `0.0.0.0`.

---

## 9. Roadmap / good next improvements

- **Process scanner depth:** WMI/ETW-based sampling, parent-process lineage,
  and a longer baseline window for the CPU-periodicity autocorrelation.
- **Signature verification:** real Authenticode checks via `signtool`/WinTrust
  behind `platform_utils`.
- **Scheduled background scans** + a tray notification when a new threat appears.
- **Report diffing:** “what changed since the last scan.”
- **Intel auto-refresh** with signed feed validation (OSV, ThreatFox, URLhaus).
- **UI:** finding list virtualization, per-perspective re-scan, and a restore
  center backed by `db.list_quarantine()`. See DESIGN.md §“What to improve.”

When in doubt, optimize for the worried user staring at an unexplained CPU
spike: make Sentinel tell them *what is wrong, why, and what to safely do next.*
