# DESIGN.md — Sentinel Dashboard Design System

The visual + interaction system for the Sentinel web dashboard
(`sentinel/ui/`). This document is the source of truth for any agent or human
touching the UI. It is synthesized from four design skills — **Impeccable**
(domain references + anti-patterns), **Frontend Design** (tokens + component
patterns), **Taste Skill** (variance/motion/density knobs), and
**Human-Centric UX** (comprehension + state coverage). Where they conflict,
**human comprehension wins.**

---

## 0. Scope, goal & taste configuration

- **UX scope:** project-wide — the entire Sentinel dashboard (no single part
  was singled out).
- **Primary goal of the surface (one sentence):** *Let a worried user run a
  scan, understand in plain language what is wrong, and safely remove threats
  without fear of breaking their PC.*
- **Taste knobs (Sentinel profile):**
  - `DESIGN_VARIANCE = 6` — distinctive “security operations center” identity;
    one bold element per view, but trustworthy, never flashy.
  - `MOTION_INTENSITY = 5` — moderate (150–300ms). **No spring physics** in a
    serious security tool.
  - `VISUAL_DENSITY = 7` — dense; findings, evidence and progress are
    data-rich and power-user oriented.
  - Resulting aesthetic per the variant matrix: a **balanced, dense, calm-but-
    serious dashboard** — think Linear/Stripe rigor with a SOC palette.
- **Identity / anti-repetition:** primary accent is **violet `#7c5cff`** (the
  Sentinel shield), deliberately distinct from DeskFlow’s pink. The **severity
  palette is the core color language**, and severity is *never* conveyed by
  color alone — always glyph + label.

---

## 1. Design tokens

These mirror `sentinel/ui/static/styles.css`. Treat them as the contract; if you
migrate to Tailwind/React later, map to these exact values.

### Color (dark, never pure black)
```
--bg:        #0e0f13   /* app base — NOT #000 */
--panel:     #16181f   /* elevated surface */
--panel2:    #1c1f29   /* nested surface / inputs */
--ink:       #e6e7eb   /* primary text */
--muted:     #8a8f98   /* metadata / secondary text */
--line:      #23262f   /* hairline borders */
--accent:    #7c5cff   /* Sentinel violet — primary action / focus */
```

### Severity palette (the core semantic language)
```
critical  #ff4d4f   🔴
high      #ff8c1a   🟠
medium    #f5c518   🟡
low       #36c275   🟢
info      #8a8f98   ⚪
```
Rule (Impeccable #10, Human-Centric pillar 4): **always pair severity color
with its glyph + text label.** Color-blind users and grayscale reports must
still parse severity. Verdict (`clean/suspicious/malicious`) and confidence %
are shown as text, never implied by hue alone.

Accent discipline (Impeccable #7): one primary (violet) + the severity
semantic set + one success (`low` green doubles as success). Never introduce a
fourth decorative accent.

### Typography (Impeccable modular scale, 1.25)
```
Font (UI):    Inter / system-ui, -apple-system, Segoe UI, Roboto, sans-serif
Font (mono):  JetBrains Mono / ui-monospace   — for paths, hashes, ports, versions, logs
Weights:      400 body · 500 labels · 600 headings · 700 hero   (NEVER <400 on dark)
Scale (px):   12 meta · 13 body · 15 section · 18 panel title · 24 hero
Line-height:  1.5 body · 1.2 headings · 1.6 mono/log
```
Evidence, file paths, registry keys, hashes and the live log are **always**
monospace — it signals “raw machine data” and aids scanning.

### Spacing (8px grid) & radius
```
4  micro    8  internal    12 list/card inner    16 section gap    24 page section
radius: 12px max (rounded-xl). NEVER rounded-2xl/3xl.
card padding: 20px (the .panel standard).
```

### Motion (knob = 5)
```
micro 100ms  (color/opacity)   fast 150ms (hover/toggle)   normal 250ms (panels/modals)
easing: ease-out cubic-bezier(0.16,1,0.3,1)   — NO spring
Animate ONLY transform + opacity. NEVER width/height/top/left/margin.
Respect @media (prefers-reduced-motion: reduce) — drop non-essential motion.
```

### Z-index scale
```
0 base · 10 elevated/sticky · 20 dropdown/tooltip · 30 modal · 40 toast · 50 overlay
```
No arbitrary values (Impeccable #22).

---

## 2. The user journey & complete state coverage

The dashboard is a 3-step vertical flow. Every data-driven element MUST define
Empty / Loading / Error / Populated / Partial (Human-Centric pillar 4 — the #1
anti-slop rule).

### Step 1 — Choose what to scan
- **Populated:** a grid of `PerspectiveCard`s (npm, process, network,
  persistence, browser), each a 44px+ checkbox target with name + `~Ns`
  estimate. A live **total time estimate** updates as you toggle.
- **Disclosure:** “Automatic mode” is a single labeled switch with a plain
  consequence string: *“Auto-remove high-confidence threats.”* Advanced tuning
  stays out of the default view (progressive disclosure, pillar 2).
- **Primary action:** one dominant violet **Start scan** button. It is the only
  primary-weight control on the screen (clear focal point, pillar 3).
- **Guard:** if zero perspectives selected, the button explains why it is
  disabled rather than silently failing.

### Step 2 — Live progress (the trust-builder)
- **Loading is not a spinner.** Render one progress row per selected
  perspective with an explicit state dot:
  - `pending` (muted) → `running` (amber, pulsing) → `done` (green, “N
    finding(s)”) → `error` (red, plain-language reason).
  - Rows are fed by orchestrator events (`perspective_start`, `progress`,
    `perspective_done`, `perspective_error`).
- A monospace **log panel** streams human messages (auto-scroll, ring-buffered).
- **Error state:** a failed perspective shows *what* failed and offers retry; it
  never blocks the other perspectives or dumps a stack trace.

### Step 3 — Findings & remediation
- **Empty (success!):** when nothing is found, show a reassuring green state:
  *“No threats found 🟢”* — never a blank box.
- **Populated:** findings sorted by severity then confidence. Each
  `FindingCard` shows: severity glyph+label, perspective, confidence %, verdict,
  a plain-language title + description, an expandable **“Why flagged &
  evidence”** (rationale + evidence, monospace), a **recommended action**
  select, and a select checkbox (pre-checked for recommended removals).
- **Summary chips** at the top count findings per severity (glyph + count).
- **Partial/Overflow:** long paths truncate with mono + full value on hover;
  large finding sets should paginate/virtualize (see “What to improve”).
- **Outcome state:** after remediation, each card shows an inline success/error
  banner with the action taken and (on success) that it is reversible.

---

## 3. Component specs

All components inherit the tokens above. Every interactive element MUST have
**hover / focus-visible / active / disabled** states (Impeccable §5).

### Buttons
```
.primary   bg --accent, white text, 600 weight        — one per view
.danger    translucent red, used for "Remediate selected"
.ghost     transparent, hairline border               — secondary actions
focus-visible: ring 2px var(--accent) @ 50% + 2px offset on --bg  (replace default outline)
active: scale(0.98)   disabled: opacity .5 + cursor not-allowed (looks clearly off)
min target: 44×44px
```

### PerspectiveCard
Glass-lite surface (`--panel2`, hairline border, radius 10–12). Checkbox uses
`accent-color: var(--accent)`. Capitalized name + muted `~Ns` estimate. Whole
card is the click target.

### ProgressRow
Dot + capitalized perspective name (fixed 110px) + muted live message. State
drives the dot color; `running` pulses (opacity keyframe only).

### FindingCard
Left border = severity color (`border-left:4px`). Header row is uppercase muted
meta with a colored `severity` token. `<details>` hides evidence by default
(progressive disclosure). Action `<select>` lists plain-language actions. The
optional outcome banner is `.oc.ok` (green) or `.oc.bad` (red).

### SummaryChips
Pill per present severity: `count + label`, bordered+colored to match severity,
glyph included. Falls back to a single green “No findings 🟢” chip.

### ConfirmDialog (destructive actions)
Remediation is destructive-feeling even though reversible — so it **confirms**:
*“Remediate N finding(s)? Actions are reversible from the quarantine vault.”*
Overlay `bg-black/70 backdrop-blur-sm` at z-overlay; card at `--panel` elevated,
radius 12, 250ms opacity+scale in.

### Toast (recommended addition)
For restore/undo confirmations at z-toast; auto-dismiss 4s; pair icon + text.

---

## 4. UX-writing rules (Impeccable §7)

- **No raw enums or system tokens in the UI.** Translate at the edge:
  - `verdict: malicious` → badge “Malicious”; `recommended_action: uninstall`
    → “Uninstall package”; `quarantine` → “Move to quarantine”; `kill` → “Stop
    process”; `disable` → “Disable task/extension.”
- **Error format:** “[Thing] [failed] because [reason]. [Fix].” e.g. *“Process
  scan needs elevated permissions. Re-run Sentinel as Administrator.”*
- **Button labels are verb + noun:** “Start scan”, “Remediate selected”,
  “Select all recommended” — never bare “Submit/OK.”
- **Empty states explain what would be there**, e.g. *“No threats found — the
  perspectives you scanned came back clean.”*
- Use “threat / finding / package / process”, not “IOC / PID binding / row.”

---

## 5. Accessibility & forgiveness (Human-Centric pillars 5–6)

- Keyboard reachable end-to-end; visible focus rings everywhere (never
  mouse-only).
- Meaning never by color alone (glyph + label everywhere severity/verdict
  appears).
- Confirm + undo for anything that changes the system; never wipe the user’s
  selection on error.
- Targets ≥44px; inline, plain validation (e.g. the disabled Start button
  explains itself).
- Honor `prefers-reduced-motion`.

---

## 6. Anti-patterns to guard against (NEVER ship)

Pulled from all four skills, scoped to Sentinel:
- Pure black backgrounds; >3 decorative accents; severity by color only.
- A data view without Empty/Loading/Error states (especially a bare spinner for
  the scan — use per-perspective progress).
- Raw enums, file dumps, or stack traces shown to the user.
- Animating `width/height/top/left`, `transition: all`, or spring physics in
  this serious tool.
- `rounded-2xl`/`3xl`, `box-shadow` for elevation (use border brightness +
  layered surfaces), `font-thin` on dark.
- Silent remediation with no confirmation, feedback, or undo.
- Arbitrary z-index; icon-only buttons for non-obvious actions without a label.

---

## 7. Pre-return checklist (Human-Centric) — status of current build

- [x] Scope stated (project-wide).
- [x] Primary action obvious in <1s (single violet **Start scan**).
- [x] No raw tokens/enums/stack traces surfaced (enum→label mapping in app.js).
- [x] Empty / Loading / Error states for scan + findings (per-perspective
      progress, green empty, plain error rows).
- [x] Clear hierarchy; muted metadata; one focal point per step.
- [x] Secondary complexity disclosed (auto-mode switch, `<details>` evidence).
- [x] Hover/focus/active/disabled on interactive elements.
- [x] 150–300ms transitions; transform/opacity only.
- [x] Submit feedback + destructive confirm + restore-token undo.
- [x] Plain-language copy throughout.
- [x] Severity never color-only (glyph+label); focus rings + keyboard nav.
- [x] ≥44px targets.
- [ ] **prefers-reduced-motion** fallback — *to add* (drop the pulse).
- [ ] **Large-list virtualization / pagination** — *to add* for big scans.

---

## 8. What to improve next (for the coding agent)

Prioritized, all within this system:
1. **Add `@media (prefers-reduced-motion: reduce)`** — disable the running-dot
   pulse and any non-essential transition.
2. **Virtualize/paginate the findings list** when count is high (density knob
   = 7 means we expect long lists); keep severity sort.
3. **Restore Center view** backed by `db.list_quarantine()` — list quarantined
   items with one-click restore (token), full audit trail. Reuse FindingCard
   layout + an `.oc` banner.
4. **Per-perspective re-scan** without re-running everything (an icon button on
   each ProgressRow / a section header action).
5. **Skeleton placeholders** for the brief gap before the first event arrives
   (matching content shape, not a spinner).
6. **Severity filter chips** become interactive (click to filter the list).
7. **Toast system** for restore/undo confirmations at z-toast.
8. If migrating to React/Tailwind: map every value in §1 to Tailwind tokens,
   keep buildless or document the build; do not regress any checklist item in
   §7.

> Decision log (per Impeccable `document` + Human-Centric output rule):
> Scope = whole dashboard. Knobs = variance 6 / motion 5 / density 7. Identity =
> violet accent + severity-as-language. Added full state coverage for scan and
> findings, plain-language enum mapping, reversible-with-confirm remediation.
> Open items: reduced-motion fallback + large-list virtualization.
