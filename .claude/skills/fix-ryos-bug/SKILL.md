---
name: fix-ryos-bug
description: 'Diagnose and fix a bug in the RYOS desktop app the right way — reproduce it, prove it with a failing test, fix the root cause, and verify nothing regressed. Use this whenever the user reports that RYOS misbehaves: a crash, traceback, freeze or hang, a script that won''t stop, output that doesn''t appear or floods, a setting that doesn''t stick, a card stuck in the running state, a broken scripts.db migration, drag-drop or pipeline glitches, or "X used to work and now doesn''t." Trigger even when the user just describes broken behavior ("the window goes white when a script prints a lot", "stop does nothing", "it forgets my last group") without using the word "bug" or pasting an error. This skill carries RYOS''s architecture rules, a reproduce→diagnose→fix→verify→review→commit workflow, per-phase model assignments, and the exact verification commands. Do NOT use it to ADD new capabilities (use add-ryos-feature), for pure UI/UX design feedback (use review-ryos-ui), or for just launching the app (use run-ryos).'
---

# Fixing a bug in RYOS

RYOS ("Run Your Own Scripts") is a Tkinter desktop app. All code lives in the `ryos/` package; the entry point is `ryos.__main__:main`, exposed as the `ryos` console-script in `pyproject.toml`.

The trap with bug-fixing here is fixing the *symptom* instead of the *cause*, or "fixing" something you never actually reproduced. Most RYOS bugs trace back to one of a few structural causes — a worker thread touching a widget directly, a migration that isn't guarded, a card refreshed the wrong way, a setting that never round-trips. So this workflow insists on two things before any code changes: reproduce the bug, and capture it in a **failing test** (where the logic is testable) so the fix is provable and can't silently regress later.

Work through the phases in order. A "fix" you didn't reproduce and can't demonstrate passing is not a fix.

**You are the orchestrator.** You own the conversation, the delegation below, the verification of everything you delegate, and the commit decision. You do **not** diagnose the root cause, write the fix, run the tests, or review the final diff yourself — each goes to a fresh subagent with a pinned model, because an independent agent has no anchoring from this conversation and catches assumptions you've already absorbed. Your own job is steps 1–2 (reproduce, gather context), then spawning, verifying, and committing. Keep the separation even for a one-line fix.

## Recommended model per phase

| Phase | Runs as | Default model | Why this model |
|---|---|---|---|
| 1. Reproduce & scope | orchestrator | Sonnet 4.6 | Owns the conversation; pins down repro steps and expected vs. actual. |
| 2. Locate code | subagent | **Haiku 4.5** | Cheap, fast search; returns the suspect code excerpts to brief diagnosis. |
| 3. Diagnose + failing test | subagent | **Opus 4.8** | Hardest reasoning — root-cause analysis and the minimal correct fix plan. |
| 4. Fix / verify | subagent | **Sonnet 4.6** | Strong coder; fast and economical across the fix-and-re-run loop. |
| 4b. Verify | orchestrator | Sonnet 4.6 | Re-runs tests and walks the checklist; the real gate is the step-5 Opus review. |
| 5. Review | subagent | **Opus 4.8** | Confirms the fix addresses the cause, not the symptom, with no new regressions. |
| 6. Commit & push | orchestrator | Sonnet 4.6 | Mechanical. |
| 7. Report | orchestrator | Sonnet 4.6 | Light summarization. |

The delegated phases are pinned in their `Agent(... model: ...)` calls below (`haiku`, `opus`, `sonnet`, `opus`) — enforced. The orchestrator phases (1, 4b, 6, 7) run on the session model, so **run this from a Sonnet session** for the intended balance.

## Where things live

| Concern | File |
|---|---|
| Paths, `_SETTINGS_DEFAULTS`, `_load_settings` / `_save_settings` | `ryos/settings.py` |
| Windows "run at login" registry | `ryos/startup.py` |
| Toast notifications + GitHub update check | `ryos/notifications.py` |
| `ScriptDB` — all SQLite logic, schema, migrations | `ryos/db.py` |
| `detect_interpreter`, `build_command` | `ryos/interpreter.py` |
| Color palette `C`, flat-button factory, window snap | `ryos/ui/theme.py` |
| `ScrollingLabel`, tooltip | `ryos/ui/widgets.py` |
| Script / preset / param / advanced-options dialogs | `ryos/ui/dialogs.py` |
| `PipelineEditorDialog` | `ryos/ui/pipeline.py` |
| `ScriptCard`, `PipelineCard` | `ryos/ui/cards.py` |
| `RYOSApp` main window + run engine | `ryos/ui/app.py` |
| `__version__` | `ryos/__init__.py` |

## Architecture rules that always apply

These invariants are also the usual suspects: when something breaks, a violated rule is often the cause. Internalize the *why*. **This is the canonical list** — when a brief below says to include the architecture rules, paste this whole section in verbatim; a partial list is how a rule quietly gets dropped.

- **Tkinter only.** The UI is built from `tk.Frame`, `tk.Label`, `tk.Button`, etc. No ttk themes, Qt, or web tech.

- **Worker threads never touch widgets directly.** Script execution runs on a `threading.Thread`. Tkinter is not thread-safe, so a worker that writes to a `Text` widget or flips a label from its own thread will eventually crash, freeze, or corrupt the display — a very common bug source. Workers reach the UI in exactly two ways: by putting items on `self.output_queue` (drained on the main thread by a recurring `self.after(80, self._drain_output_queue)`), or via `self.after(0, callback)`. A freeze/white-window/garbled-output report should make you suspect a violation here first.

- **Don't rebuild all the cards on run/stop.** When a script starts or stops, flip the running state of *that one card* in place. Calling the full `_refresh_cards()` on start/stop is slow, loses scroll position, and drops in-flight state — and "card stuck running" / "scroll jumps" bugs often live here. Grep `ryos/ui/cards.py` and `ryos/ui/app.py` for the current running-state mechanism and reuse it.

- **Database changes are additive and migration-safe.** Schema lives in `ScriptDB._init_db()` in `ryos/db.py`. SQLite has **no** `ADD COLUMN IF NOT EXISTS`; the file reads existing columns with `PRAGMA table_info(<table>)` then guards each migration (`if "<col>" not in cols: ALTER TABLE ...`). "DB won't open after upgrade" bugs usually mean a migration wasn't guarded this way. New query/mutation logic is a method on `ScriptDB`, not raw SQL in the UI.

- **Settings round-trip through `_SETTINGS_DEFAULTS`.** A setting must be a key in `_SETTINGS_DEFAULTS` (so old files still load via `{**_SETTINGS_DEFAULTS, **stored}`), saved/loaded via `_save_settings()` / `_load_settings()`, and wired to its control in `ryos/ui/dialogs.py`. "Setting doesn't stick" bugs are usually a missing link in that chain.

- **Dependency direction is one-way: `ui/*` → top-level modules.** `ryos/db.py`, `ryos/settings.py`, etc. must never import from `ryos.ui.*`. A new back-import creates an import cycle and may surface as an import error at startup.

- **Route colors and buttons through `theme.py`.** Colors come from the `C` dict; buttons from the flat-button factory. Add to `C` rather than hard-coding hex.

- **Comments explain WHY, not WHAT.** Add a comment only when the reason for a line is non-obvious.

- **Bump `__version__`** in `ryos/__init__.py` — patch level for a bug fix.

## The workflow

### 1. Reproduce and scope the bug

You can't fix what you can't see fail. Pin down, from the user, the exact steps, the expected behavior, and the actual behavior (and the full traceback if there is one — ask for it rather than guessing). Then reproduce it:

- If it's logic (a `ScriptDB` method, settings round-trip, interpreter/param parsing), reproduce with a quick `python3 -c ...` or by reading the failing path — the cheapest repro.
- If it's runtime/UI behavior (freeze, stuck card, output glitch), use the `run-ryos` skill to launch and drive the app and capture screenshots of the broken state. If there's no display, say so and reason from the code + traceback.

If you genuinely cannot reproduce it, say so and ask the user for more detail (OS, exact script, settings) instead of speculating a fix. State the confirmed repro in one sentence before moving on.

### 2. Locate the code (delegate broad search to a Haiku agent)

Hand the search for the suspect code to a fast Haiku agent and keep your own context clean.

```
Agent({ description: "Locate code for <bug>", subagent_type: "general-purpose", model: "haiku", prompt: <brief> })
```

The brief gives the bug and its repro in a line or two plus the **Where things live** table, and asks the agent to: find the file(s)/function(s) on the failing path; return the relevant code **excerpts verbatim** with `file:line` references (the suspect function plus its callers/callees) so they can be pasted into the diagnosis brief; and flag anything that looks like a violated architecture rule near the failure. End with: *"Do not propose a fix or edit anything — only locate and quote the relevant code."*

### 3. Diagnose the root cause and write a failing test (fresh Opus agent)

You do not diagnose inline. Spawn a fresh Opus agent to find the *root cause* (not the symptom) and produce the fix plan.

```
Agent({ description: "Diagnose <bug>", subagent_type: "general-purpose", model: "opus", prompt: <self-contained brief> })
```

The brief is self-contained — paste, verbatim: the confirmed repro and expected/actual behavior; any traceback; the **Where things live** table and the entire **Architecture rules that always apply** section; the code excerpts from step 2; and this instruction: *"Find the ROOT CAUSE, not the symptom — explain why the bug happens, tracing it to a specific line or interaction. Then specify the smallest correct fix. Where the bug is in testable non-UI logic, write a unit test (in the `TestScriptDB*` style of tests/test_ryos.py) that FAILS on the current code and will PASS once fixed — this proves the bug and guards against regression. For a purely visual bug, describe the run-ryos check that demonstrates it instead. Do NOT write the fix; produce: root cause, the failing test (or visual check), the fix plan (files + functions + one-line purpose), and risks/regressions to watch. List any open questions instead of guessing."*

A good diagnosis is specific. Illustrative shape (not a real RYOS bug): *root cause — the stop handler calls `proc.terminate()` but never flips the card's running flag, so a card whose process exits between polls stays "running"; failing test — assert the card state resets after the done-event is drained; fix — set the state in the done branch of the queue drain; risk — make sure normal completion still clears it.*

Present the diagnosis and fix plan to the user; proceed once they're on board (a "go ahead" counts as approval). Use a task list for the concrete changes.

### 4. Fix and verify (Sonnet agent)

You do not write the fix or run the tests yourself. Spawn a Sonnet agent to apply the plan, make the failing test pass, and confirm nothing else broke.

```
Agent({ description: "Fix <bug>", subagent_type: "general-purpose", model: "sonnet", prompt: <self-contained brief> })
```

The brief includes, verbatim: the root cause and fix plan from step 3; the failing test to add (or the visual check); the entire **Architecture rules that always apply** section (paste it — the fix must not trade one violation for another); the `__version__` patch bump; and the acceptance criteria:

- `cd D:/Projects/RYOS && uv run python -m unittest discover -s tests -v` — the new regression test passes and the whole suite is green.
- `cd D:/Projects/RYOS && uv run ryos` — the original repro no longer reproduces, and run/stop, groups, output panel, drag-drop, and the pipeline editor still work. **If there's no display and the GUI can't launch, don't silently skip this** — say so, rely on the unit tests, and use the `run-ryos` screenshot driver where possible.

Add: *"Read only the files in the plan plus direct callers/callees; don't scan the repo. Edit only inside `ryos/`, plus the regression test in tests/test_ryos.py. Don't touch pyproject.toml, build*.bat, or uv.lock. Apply the fix, add the failing test, bump `__version__`, then run the suite and the repro check; if anything fails, read the traceback, fix, and re-run until clean. Do not commit or push. Report files changed, the regression test going red→green, the final suite result, and a one-line repro-gone note."*

When the agent returns, **verify before moving on** — this is the gate. Run `git diff` and re-run the suite yourself, then check the diff:

- [ ] The regression test actually fails on the old code and passes on the fix (not a test written to trivially pass).
- [ ] The fix addresses the root cause from step 3, not just the surface symptom.
- [ ] `__version__` bumped (patch) in `ryos/__init__.py`.
- [ ] No worker thread touches a widget except via `self.after` / `self.output_queue`.
- [ ] No new `import ryos.ui.*` inside top-level modules; any DB change stays `PRAGMA`-guarded.
- [ ] Run/stop still flips the affected card in place — no `_refresh_cards()` on start/stop.
- [ ] Edits stay within `ryos/` plus the one regression test.

Fix inline or send the Sonnet agent a follow-up via SendMessage if anything's off. Mark tasks complete only once verified.

### 5. Review before commit (fresh Opus agent)

Spawn an independent Opus agent to review the staged diff.

```
Agent({ description: "Review fix for <bug>", subagent_type: "general-purpose", model: "opus", prompt: <self-contained brief> })
```

The brief includes, verbatim: the original bug + repro; the root cause and plan from step 3; the full `git diff`; the entire **Architecture rules that always apply** section; and: *"Review ONLY the diff and the files it modifies. Confirm the change fixes the stated root cause (not just the symptom), that the regression test genuinely covers the bug, and that no architecture rule is violated or new regression introduced. Do NOT edit anything. Report BLOCKERS, SUGGESTIONS, and OK. If there are no blockers, end with 'READY TO COMMIT'."*

If there are BLOCKERS, fix them or delegate back via SendMessage, then re-review. Proceed only on `READY TO COMMIT`.

### 6. Commit and push

Match the existing commit style (`git log --oneline -5`). Stage only the relevant files — never `scripts.db`, `dist/`, `build/`, `.env`, or `__pycache__`.

```bash
cd D:/Projects/RYOS && git add ryos/ tests/test_ryos.py && git commit -m "$(cat <<'EOF'
fix: <short description of the bug>

<root cause in a line; what changed>

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)" && git push
```

### 7. Report back

Tell the user, briefly: what was broken and the root cause, the fix and which files under `ryos/` changed, the regression test added, the new `__version__`, the commit hash, and anything to watch for.
