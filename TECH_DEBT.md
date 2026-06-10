# RYOS Technical Debt Audit

_Generated 2026-06-10 · version 1.7.2-dev · ~5,600 LOC across `ryos/`_

## Summary

RYOS is a healthy small codebase: clean package layout, a thin standard-library dependency surface, a real test suite (50 tests) for the data and interpreter layers, and decent docs (README + CLAUDE.md). The debt is concentrated in three places: **no automated quality gate (CI/lint)**, **the `RYOSApp` god class in `ryos/ui/app.py`**, and **broad exception swallowing** that hides failures. None of it is on fire, but the UI layer is now large enough (app.py is 2,380 lines) that adding features is getting slower and riskier, and nothing automatically catches a regression before release.

Priority score below = **(Impact + Risk) × (6 − Effort)**, each rated 1–5.

| # | Item | Type | Impact | Risk | Effort | Priority |
|---|------|------|:------:|:----:|:------:|:--------:|
| 1 | No CI / no lint / no type or format config | Infrastructure | 4 | 4 | 2 | **32** |
| 2 | Broad `except Exception` swallowing failures silently | Architecture | 3 | 4 | 2 | **28** |
| 3 | Zero tests for `ui/` and app logic (largest module untested) | Test | 4 | 4 | 3 | **24** |
| 4 | Giant methods: `_refresh_cards` (267 lines), `_build_ui` (142) | Code | 4 | 3 | 3 | **21** |
| 5 | Duplicated job-launch logic (`_run_script` vs pipeline step) | Code | 3 | 3 | 3 | **18** |
| 6 | `RYOSApp` god class — ~90 methods, 2,275 lines, one class | Architecture | 5 | 3 | 4 | **16** |
| 7 | Three parallel build scripts, no canonical one | Infrastructure | 2 | 2 | 2 | **16** |
| 8 | Ad-hoc schema migrations in `_init_db`, no version tracking | Architecture | 2 | 3 | 3 | **15** |
| 9 | Unpinned dependency (`tkinterdnd2`, no lower bound) | Dependency | 2 | 2 | 1 | **20*** |

_\*Item 9 scores high mechanically because it's near-zero effort, but the real-world risk is low (single, stable dep). Treat it as a 5-minute fix, not a priority._

---

## Findings

### 1. No CI, lint, type-check, or format config — Priority 32
There is no `.github/` workflow and `pyproject.toml` declares no `ruff`/`black`/`mypy`/`pytest` tooling. The 50 existing tests only run when someone remembers to run them locally, and the release flow (`release-ryos` skill, manual version bumps) has no gate. A broken import or failing test can ship.

**Business justification:** This is the highest-leverage fix. One GitHub Actions workflow that runs `pytest` + `ruff check` on every push turns the existing (good) test suite into an actual safety net and pays off on every future change.

### 2. Broad exception swallowing — Priority 28
`except Exception:` / bare `except:` with silent `pass` appears throughout `settings.py`, `notifications.py`, `theme.py`, `widgets.py`, and several spots in `app.py` (e.g. lines 63, 76, 479, 2373). Some are legitimate (best-effort UI cosmetics), but settings load/save and DB paths swallowing everything means corruption or permission errors fail invisibly — the user just sees lost data with no log.

**Business justification:** Silent failures are the hardest bugs to support. Narrowing these to specific exceptions and logging the rest converts "it just stopped working" reports into actionable logs. The `logger` module already exists, so this is low-effort.

### 3. No tests for the UI / app layer — Priority 24
`tests/test_ryos.py` covers `db.py` and `interpreter.py` well (export/import, migrations, ordering, command building). But `ui/app.py` (2,380 lines, the most complex and most frequently changed module), plus `settings.py`, `startup.py`, and `notifications.py`, have **zero** tests. Headless tkinter is already wired up in the test harness, so the runway exists.

**Business justification:** The untested code is exactly the code that changes most often (see git log: compact mode, card size, quick-run index). Regressions here reach users directly. Extracting pure logic (job state, quick-run resolution, suggestion ranking) out of the widget code makes it testable and is the natural companion to items 4–6.

### 4. Oversized methods — Priority 21
`_refresh_cards` is 267 lines and `_build_ui` is 142; both mix layout, state, and event wiring in a single scope. These are the methods most likely to break when touched and the hardest to review.

**Business justification:** Breaking these into named sub-builders (per section / per card type) makes diffs reviewable and lets the UI skills (`review-ryos-ui`, `add-ryos-feature`) target smaller surfaces.

### 5. Duplicated job-launch logic — Priority 18
`_run_script` and the pipeline-step launch path both construct a `_Job`, spawn a daemon thread targeting `_run_subprocess`, and register a running row. The setup is copy-pasted rather than funneled through one `_launch(job)` helper.

**Business justification:** Any change to how jobs start (e.g. env handling, cwd logic, cancellation) currently has to be made in two places and is easy to get half-right.

### 6. `RYOSApp` god class — Priority 16
A single class owns UI construction, drag-and-drop, tab management, group CRUD, subprocess orchestration, the quick-run subsystem, output routing, notifications, and update checks — ~90 methods over 2,275 lines. High mechanical effort to split, which is why the priority lands mid-table despite high impact.

**Business justification:** This is the root cause behind items 3–5. The pragmatic path is incremental: extract cohesive subsystems (QuickRun, JobManager, TabBar) into their own classes over time rather than one big-bang refactor. Do it opportunistically as you touch each area.

### 7. Three parallel build scripts — Priority 16
`build_cxfreeze.bat`, `build_nuitka.bat`, and `build_pyinstaller.bat` all exist; `build.bat` delegates to cxfreeze. CLAUDE.md calls cxfreeze canonical but the other two still need to keep working or rot.

**Business justification:** Pick one canonical packager, mark the others clearly experimental (or move them to a `packaging/` folder), so contributors don't waste time debugging a path nobody ships.

### 8. Ad-hoc schema migrations — Priority 15
`_init_db` does manual `PRAGMA table_info` + `ALTER TABLE ... ADD COLUMN` checks for each historical column. It works and is well-tested, but there's no schema-version number, so ordering and future destructive migrations (renames, drops) will get fragile.

**Business justification:** A single `PRAGMA user_version` counter with numbered migration steps future-proofs this before the next schema change, at modest cost.

### 9. Unpinned dependency — Priority 20 (low real risk)
`dependencies = ["tkinterdnd2"]` has no version floor. A breaking upstream release could surprise a fresh `uv` install. Five-minute fix: pin a `>=` lower bound and a tested upper bound.

---

## Phased remediation plan

Designed to run **alongside feature work**, not as a freeze.

**Phase 1 — Safety net (≈1 day, do first)**
- Add a GitHub Actions workflow running `pytest` and `ruff check` on push/PR (item 1).
- Add `ruff` config to `pyproject.toml`; fix what it flags. Pin `tkinterdnd2` (item 9).
- Narrow the highest-stakes `except Exception` blocks in `settings.py` and DB paths, logging the rest (item 2, first pass).

**Phase 2 — Make the UI testable (incremental, 1–2 weeks of opportunistic work)**
- Extract pure logic out of `app.py` into testable units: quick-run resolution/ranking, job state, version parsing already in `notifications`. Add tests as you go (item 3).
- Funnel both launch paths through one `_launch(job)` helper (item 5).
- Split `_refresh_cards` and `_build_ui` into named sub-builders (item 4).

**Phase 3 — Structural (ongoing, only as you touch each area)**
- Peel cohesive subsystems off `RYOSApp` one at a time — start with QuickRun since it's already fairly self-contained (item 6).
- Introduce `PRAGMA user_version` migration numbering before the next schema change (item 8).
- Consolidate build scripts; document the canonical one and quarantine the rest (item 7).

## What's already good (don't "fix")
- Thin, standard-library-only runtime (just `tkinterdnd2`) — low dependency debt.
- Thread-safe output via `Queue` + `after()` polling, as documented in CLAUDE.md.
- Solid test coverage of the data + interpreter layers, including migration tests.
- Clear module boundaries and an up-to-date CLAUDE.md / README.
