# RYOS Agent: let Claude run your scripts, without the app

**RYOS Agent** is RYOS without the window. You give it a short list of your scripts, and Claude can run those scripts and read their output, and nothing else. Use it when you want Claude to have your scripts but have no use for the RYOS window.

If you already use the RYOS window, you don't need this page. The full Windows download includes everything here. See [The command line and AI agents](13-command-line-and-agents.md).

## What you get

- **An allow-list.** Claude sees only the scripts you choose. It can't list, run, or learn the name of anything else.
- **Your parameters, not Claude's.** Claude runs a script with its own parameters or one of its saved presets. It can't make up parameters of its own.
- **A record.** Every run is kept in history: who started it (you, Claude, a schedule), when, how it went, and its output.
- **Room to grow.** Install the full RYOS app later and your scripts, presets and history are already in it.

What you don't get without the window: RYOS schedules, notifications, Quick Run, and the pipeline editor. To run something on a timer, see [Running on a timer](#running-on-a-timer).

> **What the allow-list protects.** It is what Claude Desktop, and any other agent that talks to RYOS only through MCP, can reach. An agent that can also run commands on your PC, such as Claude Code, is not kept in by it: it can start programs itself, including your scripts. Only connect an agent like that if you trust it with your computer.

## 1. Download

Download **RYOS-agent.zip** from the [latest release](https://github.com/lqvu-zen/RYOS/releases/latest) and extract it, for example to `C:\Tools\RYOS-agent`. Inside is `ryos-cli.exe`. Nothing else needs installing for RYOS itself; your scripts still need whatever runs them, as they do now (Python for a `.py`, and so on) — RYOS uses what's on your PC.

Open a terminal in that folder and check it runs:

```text
ryos-cli --version
```

The examples below assume the folder is on your `PATH`, or that you run them from inside it.

## 2. Add your scripts

Add a script and choose whether Claude may run it:

```text
ryos-cli add C:\tools\backup.py --name backup --group Tools --expose
```

| Option | What it does |
| --- | --- |
| `--name N` | The name you and Claude will use. Defaults to the file name. Must be unique in its group. |
| `--group G` | The group it belongs to. Groups keep the list tidy and make names unique (`Tools/backup`). |
| `--workdir DIR` | The folder it runs in. Defaults to the script's own folder. |
| `--params="..."` | The parameters it always runs with. Put the `=` in when they start with a dash. |
| `--expose` | Claude may run it. **Leave this off and Claude can't see the script at all.** Asks you to confirm in the terminal; add `--yes` to skip the question. |

RYOS works out how to run the file (Python, PowerShell, a batch file and so on) the same way the window does. If the file isn't there yet, or is outside the group's base folder, RYOS refuses unless you add `--yes`.

Only expose a script you'd be happy for Claude to run without asking you first.

### Presets: give Claude a few safe choices

Claude can't pass its own parameters, but it can pick a preset you saved:

```text
ryos-cli preset add Tools/backup full  --params="--full --verify"
ryos-cli preset add Tools/backup quick --params="--fast"
```

Now Claude can run the plain `backup`, `backup` with **full**, or `backup` with **quick**, and nothing else.

### Change your mind

```text
ryos-cli list                                  everything you've added, and what Claude may run
ryos-cli expose Tools/backup off               Claude loses it at once
ryos-cli edit Tools/backup --params="--fast"
ryos-cli preset remove Tools/backup quick
ryos-cli remove Tools/backup                   asks first; add --yes to skip the question
```

Names work as everywhere else in RYOS: the name, `group/name` when a name is in more than one group, or the number `ryos-cli list` shows (`#12`).

## 3. Connect Claude

**Claude Desktop.** Open *Settings → Developer → Edit Config* and add RYOS to `claude_desktop_config.json`, using the folder you extracted to:

```json
{
  "mcpServers": {
    "ryos": {
      "command": "C:\\Tools\\RYOS-agent\\ryos-cli.exe",
      "args": ["mcp"]
    }
  }
}
```

Backslashes are doubled, because that's how JSON writes `\`. If the file already has an `"mcpServers"` section, put the `"ryos": { ... }` part inside it rather than adding a second one.

Quit Claude Desktop from the tray icon (closing the window isn't enough) and open it again.

**Claude Code.** In a terminal:

```text
claude mcp add --scope user ryos -- C:\Tools\RYOS-agent\ryos-cli.exe mcp
```

`--scope user` makes RYOS available in every project. Leave it out to add RYOS to the current folder only.

## 4. Try it

Ask Claude:

> *List my RYOS scripts.*

It should name only the scripts you exposed. Then try something real:

> *Run the backup with the full preset and tell me if anything failed.*

Claude starts the run, checks on it until it finishes, and tells you how it went. Long runs are fine: Claude doesn't have to wait in one go.

To see what's been run, by Claude or by you:

```text
ryos-cli history
ryos-cli history Tools/backup --limit 5
```

## Running on a timer

RYOS Agent has no window, so RYOS's own schedules don't run. Use Windows Task Scheduler instead: point it at `ryos-cli.exe` with `run Tools/backup --preset full` as the arguments. The run shows up in `ryos-cli history` like any other.

## Moving to the full app later

Download **RYOS-windows.zip** and run `RYOS.exe`. Your scripts, presets, history, and what Claude may run are all there, because both versions keep your data in the same place (`%APPDATA%\RYOS`). Change the Claude config to point at the new `ryos-cli.exe`, then delete the RYOS-agent folder.

Keep both on the same version. From 2.3.0 on, a RYOS that finds data it can't safely use — written by a newer version that changed it in a way older ones don't understand — stops and asks you to update rather than risk damaging it.

## Keeping up to date

```text
ryos-cli version --check
```

This tells you whether a newer RYOS Agent is available, and which file to download.

## If something's wrong

| What you see | What to do |
| --- | --- |
| Claude says it has no RYOS tools | Check the path in the config, then fully quit and reopen Claude Desktop. For Claude Code, run `claude mcp list`. |
| Claude connects but lists nothing | No script is exposed yet. Run `ryos-cli list`, then `ryos-cli expose <name> on`. |
| `ryos-cli mcp` seems to hang when you run it yourself | That's normal: it's waiting for Claude to talk to it. Press **Ctrl+C**. |
| A command stops with exit code 125 | RYOS refused: no such script, an ambiguous name, a bad path, a name already in the group, or no such preset. The message says which. |
| "…updated by a newer RYOS, and this one cannot use it safely" | Another RYOS on this PC is newer. Update this one to the same version; nothing was changed. |

> **Output is just text.** A script's output goes back to Claude as it is. If a script prints something that looks like an instruction, a careful agent reports it rather than doing what it says, but keep that in mind before exposing a script that reads web pages or e-mail.

---
[← The command line and AI agents](13-command-line-and-agents.md) · [Contents](README.md)
