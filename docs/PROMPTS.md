# RYOS prompt book

Paste-ready prompts for running RYOS with the Claude team. Replace anything in `{braces}`. Written 2026-10-13 by the secretary session; keep it next to `docs/STATUS.md` and add to it when a new prompt proves useful.

**Which tab, which model:**

| Tab | Model and effort | For |
|---|---|---|
| Secretary | Sonnet 5.5, Medium | `/ryos-secretary`: status, issues, decisions, plan steps |
| Coding | Sonnet 5.5, Medium (High for the release test phase and releases) | one plan step per fresh tab |
| Planning | Opus 5.5, High | a whole release plan, a big design question |

Open a new tab with `Ctrl+Shift+Esc`. Switch the model by clicking its name under the prompt box.

---

## 1. Starting a session

**Secretary, in Claude Code (once the skill is installed):**
```
/ryos-secretary
```

**Secretary, in claude.ai or a Claude Code tab without the skill:**
```
You're my RYOS project secretary: not the planner, and you never write code.
You keep docs/STATUS.md (decisions, open items, issues) and add plan steps
to docs/plans/ when I decide something. Read docs/STATUS.md, then check
git log, gh issue list -R lqvu-zen/RYOS and the current plan's Status table
for anything newer, and tell me where we are.
```

**Coding: continue the plan** (one fresh tab per step):
```
Read docs/STATUS.md to find the current plan, then continue with its next open step in Order. Update the Status table when it's done.
```

**Coding: one specific step:**
```
Do step {N} of docs/plans/release-{X.Y.Z}.md. Paste the step and its
"Done when" into every agent brief. Update the Status table when it's done.
```

---

## 2. Planning (secretary tab, unless marked)

**What should we do this week?**
```
What should we do this week? Check what's open in the current plan, new
GitHub issues and anything waiting on me, and propose an order. Don't start
a new release plan.
```

**A new feature idea:**
```
I want {feature, in a sentence or two}. Is it worth it, and does it belong
in the current release or the next? Give me your recommendation, then add it
as a plan step once I agree.
```

**Check GitHub issues:**
```
Check the GitHub issues opened or updated since the last status update and
triage them into the plans. Ask me before adding anything.
```

**User feedback:**
```
A user said: "{feedback}". What do you think, and what should we change?
Log it under User feedback in STATUS, and draft a short reply I can send.
```

**Log a decision:**
```
Decision: {decision}. Log it, update the plans it affects, and give me the
prompt for the coding session.
```

**Turn the 2.4 brief into a plan** (planning tab on Opus High, or the secretary calling `ryos-planner`):
```
Turn docs/plans/release-2.4.0-brief.md into docs/plans/release-2.4.0.md, in
the format of docs/archive/release-2.3.1.md. Check every step against the code and
docs/BEHAVIOUR.md. Give me the open questions, each with your recommended
answer, before writing the file.
```

**The next release after the current one:**
```
{X.Y.Z} has shipped. Close its plan (Status complete, issues closed),
archive it to docs/archive/, and draft the next release from what's
parked, the behaviour map's untested backlog and open issues. Ask me what
goes in.
```

---

## 3. Building (coding tab)

**A feature that isn't in a plan yet (small):**
```
/add-ryos-feature {what the user should be able to do}. Read the relevant
docs/BEHAVIOUR.md entries first and check every surface they list. Add or
update the map entry with its test.
```

**A bug report:**
```
/fix-ryos-bug GitHub issue #{N}: {one-line summary}. Reproduce it first.
Check every surface the docs/BEHAVIOUR.md entries list, add the regression
test and the map entry, and reference #{N} in the commit.
```

**Packaging, database, threading or security work:**
```
... (as above) This touches {packaging / the database / threading /
security}: escalate the implementer to Opus at medium effort.
```

**An independent review of work that already landed:**
```
Use ryos-reviewer in diff mode to review {commit range, e.g. v2.3.0..HEAD}
against docs/plans/release-{X.Y.Z}.md and docs/BEHAVIOUR.md. Report
blockers only; fix nothing.
```

**Behaviour map upkeep:**
```
Check docs/BEHAVIOUR.md against the code changed since {commit or tag}: add
missing entries, update the surfaces, and list new "untested" entries.
Don't change code.
```

---

## 4. Testing

**Run the release check** (coding tab):
```
Build all four zips and run tests/release_check.py. Report pass or fail per
check. Fix nothing yet.
```

**Tester agent on a release candidate** (coding tab):
```
Run ryos-tester on the {vX.Y.Z-rcN} zips in dist/: every change since
{last tag}, both layouts, each relevant download. Report PASS or FAIL per
flow, with screenshots for failures.
```

**Your own clean-machine MCP check** against real Claude Desktop and Claude Code, which `release_check.py`'s plain JSON-RPC can't show: follow `docs/MCP_CLEAN_TEST.md` (Command Prompt, not PowerShell; a throwaway `APPDATA`). Or ask a secretary session:
```
Walk me through the clean-machine MCP test for {vX.Y.Z-rcN} on my PC, step
by step, using a throwaway data folder under D:\Work\RYOS-test.
```

**Report what you found while using a release candidate** (secretary tab):
```
While using {vX.Y.Z-rcN} I found: {what happened, steps, which download}.
File it as a GitHub issue, triage it, and tell me whether it blocks
promotion.
```

---

## 5. Releasing (coding tab, High effort)

**Start a release candidate:**
```
/release-ryos Start the release candidate for {X.Y.Z}: release_check.py,
then publish v{X.Y.Z}-rc1 as a GitHub pre-release, then run ryos-tester.
Give me the manual checklist. Stop there; don't promote.
```

**Promote after the RC days:**
```
/release-ryos I've used v{X.Y.Z}-rc{N} for {days} days and ticked the
checklist: {anything worth noting}. Promote the same commit to v{X.Y.Z}:
release_check.py, then the release review (READY TO PUBLISH), then publish.
Close the issues the notes name.
```

**A new RC after a fix:**
```
/release-ryos rc{N} had {problem}, now fixed in {commit}. Cut
v{X.Y.Z}-rc{N+1} through the same flow.
```

**Something is wrong with a published release:**
```
v{X.Y.Z} has {problem}, affecting {who}. First tell me the options (mark it
pre-release so update checks skip it, or a {X.Y.Z+1} hotfix), and what each
means for people who already updated. Don't touch the release until I
choose.
```

---

## 6. Upkeep (coding tab unless noted)

**Refresh the tutorial screenshots after UI changes:**
```
/ryos-tutorial-generator Refresh the screenshots and text of the tutorial
pages affected by {feature or release}.
```

**A UI review:**
```
/review-ryos-ui Review {screen, e.g. the compact rows and the detail pane},
in both layouts and two themes. Findings first; change nothing until I agree.
```

**Tech debt check-in:**
```
Compare docs/tech-debt-2026-09-21.md with the code today. What's fixed,
what's new, and the top three worth doing next. Write it as a new dated
tech-debt doc and mark the old one superseded.
```

**Docs cleanup:**
```
/design-steward:cleanup Audit docs/ and the repo root for superseded or
finished documents. Propose remove, archive or keep for each, and fix links
in the same commit once I agree.
```

**Dependency updates:**
```
Check for newer PySide6, cx_Freeze and mcp versions. Tell me what changed
that matters to RYOS and the risk of upgrading. Upgrade only what I approve,
with the full test suite and a release_check.py run.
```

**The signing key for 2.4 self-update (part A2), only when that step comes:**
```
It's time for the Ed25519 update-signing key. Walk me through creating it on
my PC, where to keep the private key and its backup (never in the repo), and
put only the public key into the code.
```

---

## 7. Housekeeping

**Too much context in a coding tab:** finish the current step, then open a new tab with the "continue the plan" prompt from section 1.

**A secretary edit got reverted** (coding tab):
```
The secretary's edit to {file} was reverted. Restore it from {where} and
commit it; secretary edits to docs/STATUS.md and docs/plans/ are always
committed, never reverted.
```

**Where did this decision come from?** (secretary tab):
```
Why did we decide {thing}? Find it in the decision log, and the commit or
plan step that carried it out.
```
