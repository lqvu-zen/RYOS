# Updating and rolling back

From 2.4 on, RYOS updates itself. It finds a new version, downloads it in the background, checks that it really comes from RYOS's maintainer, and installs it only when you say so. If the new version doesn't suit you, one step takes you back to the one you had.

> **Coming from 2.3.x?** Download 2.4 by hand once, from the [latest release](https://github.com/lqvu-zen/RYOS/releases/latest), and extract it into an empty folder (not over your old one, which can leave old files behind). Your scripts, groups, history and settings stay where they are, in `%APPDATA%\RYOS`. From then on, RYOS updates itself.

## How RYOS finds and downloads an update

When a new version is out, a banner appears at the top of the list. While you carry on working, RYOS downloads the zip for *your* kind of RYOS (the Windows build, the one with AI agents, or RYOS Agent — never another), then checks it:

- the release's `SHA256SUMS.txt` must carry the maintainer's signature, made with the key built into your RYOS;
- the zip must match its line in that file.

Anything that fails a check is thrown away, and nothing is installed.

You can turn the background download off: **Options → Logging → Download updates in the background**. The banner still tells you a new version is out; you then download it from the release page yourself.

Testers can also see release candidates: **Options → Logging → Offer release candidates (for testing)**. It is off by default; when on, RYOS and `ryos-cli` offer a newer release candidate of your download and install it like a release.

## Restart to update

Once the download is checked, the banner reads **Update ready — RYOS X (you have vY)**, with two buttons:

- **Restart to update** closes RYOS, puts the new version in place and opens it again. The program stays at the same path, so your shortcuts and Start with Windows keep working.
- **Later** hides the banner until RYOS next starts. Nothing is installed.

RYOS never stops a run to update:

- **Runs going.** RYOS asks whether to wait. Say yes and it waits, then restarts by itself once the last run has finished.
- **A schedule due in the next few minutes.** RYOS asks whether to restart now anyway; that run won't happen while RYOS restarts.
- **An AI agent connected.** While Claude (or another agent) has `ryos-cli.exe mcp` open, the files can't be swapped. RYOS names it and offers to install the update **the next time RYOS starts**. Close the agent, or just open RYOS again later.

## Rolling back

The version you had is kept beside your RYOS folder, as `<your folder>.previous`. To go back to it, choose **Help → Roll back to RYOS X…** and confirm. RYOS restarts as the version you had; the one you leave becomes the new `.previous`, so you can change your mind again.

> **Your data may be ahead.** Now and then a new version changes how your data is stored. When it has, RYOS warns you before rolling back: the older version will refuse to open your data (it never damages it) until you update again.

The entry is greyed out when there's nothing to go back to — before your first update, if the `.previous` folder has been changed since, or if the updates folder (see below) was deleted.

## RYOS Agent and the command line

RYOS Agent has no window, so it updates from the terminal:

```text
ryos-cli version --check          is there a new version, and is it downloaded yet?
ryos-cli update                   download, check and install it
ryos-cli update --rollback        go back to the version you had
```

Each one asks before it changes anything; add `--yes` to skip the question. The swap happens once the command has ended, and what happened is written to `ryos-cli.log`.

Two things to know first:

- **Run it from somewhere else.** A terminal sitting inside the RYOS folder holds it in place: `cd` out of it first.
- **Close the agent first.** While Claude Desktop or Claude Code has RYOS Agent's MCP server open, RYOS can't swap the files and says so. Quit the agent, run `ryos-cli update`, then open the agent again.

## If something goes wrong

RYOS checks every file of the new version before and after putting it in place. If anything fails, the version you had is put back as it was, and RYOS tells you why.

| What you see | What to do |
| --- | --- |
| "…may still be running, or antivirus may be scanning it" | Another RYOS, an agent's `ryos-cli.exe mcp`, or your antivirus held a file open. Close what you can and try again in a minute. Look in `ryos-cli.log` for the details. |
| "RYOS could not put … back together" | Rare: something stopped the swap halfway. Close every RYOS and agent, then run the command it names, `ryos-cli apply-update --install "<your folder>" --recover`. |
| "RYOS cannot write in …" | RYOS lives in a folder you can't change without being an administrator (such as Program Files). Download the new version by hand, or move RYOS to a folder of your own. |
| An update keeps failing | Download the zip by hand from the release page and extract it. Your data is never in the RYOS folder, so nothing is lost. |

Where things are:

- `<your folder>.previous` — the version you had, kept for rolling back.
- `%LOCALAPPDATA%\RYOS\updates` — downloaded updates, and RYOS's notes on each update. Don't delete it: it also holds the record that lets you roll back.

## Running from source

If you run RYOS from source (`RYOS-portable.zip` or a clone, started with `uv run ryos`), it never updates itself; the banner and `ryos version --check` tell you a new version is out. Update with `git pull`, or download a fresh `RYOS-portable.zip`.

---
[← RYOS Agent](14-ryos-agent.md) · [Contents](README.md)
