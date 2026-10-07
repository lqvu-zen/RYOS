# The command line and AI agents

Everything so far happens in the window. RYOS can also run your scripts and pipelines **without** it: from a terminal, from Windows Task Scheduler or a git hook, or for an **AI agent** such as Claude. The window can stay open while you do; its rows update when a run started elsewhere finishes.

## The command line

**Where it is.** In the Windows download, `ryos-cli.exe` sits next to `RYOS.exe` (`RYOS.exe` opens the window and can't print to a terminal). Run from source, it's `uv run ryos` followed by a command. The examples below use `ryos-cli`; from source, type `uv run ryos` instead.

```text
ryos-cli list                         every script and pipeline, and how to name each
ryos-cli run Tools/backup             run a script and show its output as it goes
ryos-cli run Tools/backup --preset full
ryos-cli pipeline Release/ship        run a pipeline, every step
```

**Naming one.** Use the name the row shows, or `group/name` when the same name is in more than one group. RYOS refuses an ambiguous name and lists the ones you might mean. `ryos-cli list` shows each one's full name and its number (`#12`), which also works.

**Parameters.** A script runs with its own parameters, unless you give a saved preset (`--preset LABEL`) or your own: `--params="--fast --verbose"`. Put the `=` in when the parameters start with a dash.

**A few more options:**

| Option | What it does |
| --- | --- |
| `--timeout 300` | Stop the run if it takes longer than 300 seconds. |
| `--json` | Print one result at the end (how it went, exit code, times, the last lines of output) instead of streaming. Handy for scripts that call RYOS. |

**How it went.** The exit code is the script's own: 0 when it passed. RYOS uses a few codes of its own, so a script that calls RYOS can tell them apart:

| Exit code | Meaning |
| --- | --- |
| 1 | The run failed with no code of its own (a failed pipeline, a script that couldn't start). |
| 124 | It ran past `--timeout` and was stopped. |
| 125 | RYOS refused: no such script, an ambiguous name, no such preset, a missing file. |
| 130 | You pressed **Ctrl+C**; the run was stopped first. |

Runs from the command line are in **Run history** like any other.

**Running on a timer without the window.** RYOS's own [schedules](07-schedules-and-history.md) need the window running (in the tray is enough). To run something when RYOS is closed, point Windows Task Scheduler at `ryos-cli.exe` with `run <group/name>` as the arguments.

## Letting an AI agent run your scripts

An AI agent connected to RYOS can see and run the scripts and pipelines you choose, and read their output, so you can ask it things like *"run the nightly backup and tell me if anything failed"*. It talks to RYOS through **MCP** (Model Context Protocol), the standard way tools like Claude Code and Claude Desktop connect to other programs.

### Choose what it may run

Nothing is available to an agent until you say so. Open a script (or a pipeline) and tick **Available to agents — an AI agent connected to RYOS may run it**, then **Save**.

![The script dialog, with three options under Group: Ask for a temporary parameter on each run, Launcher, and Available to agents](images/02-add-script-dialog.png)

What an agent can and can't do:

- It sees **only** what you ticked. Everything else isn't there at all: it can't list it, run it, or learn its name. Untick a script and the agent loses it at once.
- It runs a script with its own parameters, or one of its saved presets. It **cannot** pass parameters of its own.
- It can stop a run it started, and read a run's output a page at a time.
- A pipeline you tick runs all its steps, whatever the steps' own settings.
- Ticking isn't copied by an import, and a copy or move that makes a script run a different file (into another group's base folder) loses it. Tick it again if you want the agent to have that one too.

Only tick what you'd be happy for the agent to run without asking you first.

### Connect Claude

The MCP server runs from RYOS's source: [`uv`](https://docs.astral.sh/uv/) and a copy of RYOS (a clone, or the extracted **RYOS-portable.zip**). It is not in the Windows download yet. In the commands below, replace `C:\Tools\RYOS` with that folder.

**Claude Code**, in a terminal:

```text
claude mcp add ryos -- uv run --directory C:\Tools\RYOS --extra mcp ryos mcp
```

**Claude Desktop**: open *Settings → Developer → Edit Config* and add RYOS to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ryos": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\Tools\\RYOS", "--extra", "mcp", "ryos", "mcp"]
    }
  }
}
```

Restart Claude Desktop. Ask it to *"list my RYOS scripts"* to check it's connected.

The agent's runs appear in **Run history** like any other, and the window's rows update when they finish.

> **Output is just text.** A script's output goes back to the agent as-is. If a script prints something that looks like an instruction, a careful agent reports it rather than doing what it says, but keep that in mind before making a script that reads web pages or e-mail available.

---
[← Tips](12-tips.md) · [Contents](README.md)
