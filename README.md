# 🛡️ Sentinel — Local Threat Scanner (Windows 11)

Sentinel is a defensive, **read-first** security tool that hunts the kind of
threat you described: a hidden process (often a cryptominer or a malicious npm
supply-chain payload) that spikes your CPU on a cycle, stutters games during
calm moments, and quietly phones home. It **scans from five independent
perspectives**, explains every finding in plain language, recommends an action,
and can **remove threats reversibly** — nothing is ever hard-deleted.

> You stay in control. Sentinel marks and recommends; **you** decide. An
> optional **Automatic mode** acts only on high-confidence (≥85%), definitively
> malicious findings.

---

## Why this catches your symptom

A CPU that spikes every few minutes and *drops when you open Task Manager* is a
classic **monitor-evading miner**. The lag during calm game scenes (but not
intense combat) is the miner stealing spare cycles whenever the GPU/CPU frees
up. Sentinel's **process monitor** specifically:

- samples per-process CPU over a window and runs **autocorrelation** to detect a
  *regular on/off cycle*,
- runs a **monitor-evasion probe** — it opens a watcher and flags any process
  whose CPU collapses when it thinks it's being observed,
- checks **digital signature** and **file provenance** (temp/AppData paths),
- matches known **miner process names**.

Meanwhile the **network scanner** catches the outbound side (mining pools /
stratum ports), and the **npm scanner** catches the likely *source* — a
compromised package pulled in by your agents.

---

## The five scan perspectives

| # | Perspective | What it inspects |
|---|-------------|------------------|
| 1 | **npm** | Compromised package versions (e.g. the Sept 2025 `chalk`/`debug` campaign), Shai-Hulud worm markers, install lifecycle scripts, obfuscation / `eval(atob())`, wallet addresses, raw-IP fetches, poisoned lockfiles |
| 2 | **process** | CPU-cycle periodicity, Task-Manager-evasion behavior, unsigned binaries, suspicious parent→child chains, miner process names |
| 3 | **network** | Active connections mapped to processes, mining-pool / stratum endpoints, beaconing patterns |
| 4 | **persistence** | Run/RunOnce registry keys, Startup folders, Scheduled Tasks pointing at scripts / temp dirs / unsigned binaries |
| 5 | **browser** | Chrome/Edge/Brave extensions: known-bad IDs, over-broad permissions, in-page miner code (CoinHive-style / WASM) |

Pick any combination — more perspectives = more thorough but slower. The UI and
CLI both show a time estimate before you start.

---

## Install

```powershell
# Windows 11, PowerShell, Python 3.10+
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> Run an elevated (Administrator) terminal for the persistence scanner and for
> creating a System Restore point before remediation.

## Use it

### Command line

```powershell
# Full scan, all five perspectives
python -m sentinel.cli scan --all

# Targeted quick triage (fast)
python -m sentinel.cli scan --perspectives process,network

# Full scan + auto-remove high-confidence threats
python -m sentinel.cli scan --all --auto

# Review past scans / quarantine
python -m sentinel.cli history

# Undo any action (everything is reversible)
python -m sentinel.cli restore <restore-token>
```

Each scan writes an interactive **HTML report** and a **JSON report** to
`%LOCALAPPDATA%\Sentinel\reports\`.

### Dashboard

```powershell
python -m sentinel.cli serve      # then open http://127.0.0.1:8787
```

The dashboard lets you choose perspectives, watch **live progress**, review each
marked finding (severity, confidence, why it was flagged, evidence), and
remediate per-finding or in bulk — with a one-click **Select all recommended**.

---

## How remediation stays safe

- A **System Restore point** is attempted before the first action of a batch.
- Files are **moved into an encrypted quarantine vault** (Fernet/AES), never
  deleted. Package dirs and extensions are moved aside; registry values are
  backed up before removal; scheduled tasks are disabled (not deleted).
- Every action is written to an **append-only audit log** and is reversible via
  a **restore token**.

## Marking scheme

🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

Each finding has a **verdict** (clean / suspicious / malicious), a **confidence**
score, a **plain-language rationale**, the **evidence** behind it, and a
**recommended action**.

---

## Architecture

```
CLI / Web UI
     │
     ▼
Orchestrator ──fans out──▶ 5 scanners (isolated worker threads)
     │                         │ emit Finding[]
     │                         ▼
     │                    Scoring engine ──▶ verdict + confidence + rationale
     │                         │
     ├──────────────▶ Reports (HTML + JSON)
     │
     └──────────────▶ Remediation engine ──▶ Quarantine vault + SQLite ledger
                                                      │
                                                 Restore (one-click undo)
```

Threat intelligence is bundled offline (`sentinel/data/intel/*.json`) and can be
refreshed from public feeds (OSV, abuse.ch ThreatFox/URLhaus) when online —
scans always work offline with last-known indicators.

## Verify the build

```powershell
python tests/run_selftest.py     # 22 end-to-end checks, exits 0 on success
```

The self-test plants synthetic IOCs (a known-bad `chalk@5.6.1`, a Shai-Hulud
`evil-pkg`, a poisoned lockfile) and verifies detection, scoring, reporting and
a full quarantine→restore round-trip — with **zero** false positives on a
benign package.

---

## Notes & limits

- Built and tuned for **Windows 11**. The code imports and runs on any OS for
  development, but the persistence scanner and signature checks are Windows-only.
- Sentinel is a focused **defensive triage tool**, not a replacement for
  Microsoft Defender / a full EDR. Run it alongside them.
- Detection lists are seeds — extend `sentinel/data/intel/*.json` and tune
  `config.yaml` to your environment (add your project folders under `npm_roots`).
