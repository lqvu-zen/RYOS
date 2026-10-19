# Testing the MCP builds on your own PC (v2.3.1)

The manual check that `ryos-cli.exe mcp` in `RYOS-windows-ai` works for real Claude Desktop and Claude Code **with no Python or `uv` on `PATH`**. `release_check.py` talks MCP as plain JSON-RPC; only a real client shows how Claude Desktop and Claude Code start the server and read its tools. Run it for each release candidate, with that candidate's zips. Your PC has both installed, so the test hides them from RYOS's MCP server, and it points the server at a throwaway data folder so your real `%APPDATA%\RYOS` is never touched.

## 1. Build the zips (in the repo, about 5 minutes)

```powershell
cd D:\Projects\RYOS
uv run --extra mcp --with cx_Freeze python build_release.py
```

It should end with `build_release done`, and `dist\` should hold four zips plus `SHA256SUMS.txt`.

## 2. Extract them outside the repo

Use a folder outside the repo, so nothing can quietly import the source.

```powershell
mkdir C:\RYOS-test
Expand-Archive D:\Projects\RYOS\dist\RYOS-windows-ai.zip C:\RYOS-test\windows-ai
Expand-Archive D:\Projects\RYOS\dist\RYOS-windows.zip    C:\RYOS-test\windows
mkdir C:\RYOS-test\data
```

If `ryos-cli.exe` ends up one level deeper, for example in `C:\RYOS-test\windows-ai\RYOS\`, use that path everywhere below.

## 3. Make two test scripts

Save `C:\RYOS-test\hello.bat`:

```bat
@echo off
echo Hello from RYOS
```

Save `C:\RYOS-test\slow.bat`. It runs for about a minute, so there's time to poll it and stop it:

```bat
@echo off
for /L %%i in (1,1,60) do (
  echo tick %%i
  ping -n 2 127.0.0.1 >nul
)
```

Batch files run with `cmd.exe`, which is always on the system `PATH`. That's why the test uses `.bat` and not `.py`: there's no Python in this test on purpose.

## 4. Add them to the test data with the CLI (Command Prompt, not PowerShell)

```bat
set APPDATA=C:\RYOS-test\data
set PATH=C:\Windows\System32;C:\Windows
set PYTHONPATH=
set PYTHONHOME=
cd /d C:\RYOS-test\windows-ai

ryos-cli --version
where python
ryos-cli add C:\RYOS-test\hello.bat --group Test --expose --yes
ryos-cli add C:\RYOS-test\slow.bat  --group Test --expose --yes
ryos-cli list
ryos-cli run Test/hello
```

What you should see:

- `--version` names 2.3.1 (or the candidate you are testing) and says it's the Windows build with AI agents.
- `where python` finds nothing, which proves Python is hidden.
- `list` shows both scripts as available to agents.
- `run` prints "Hello from RYOS".

Keep this window open for steps 7 and 8.

## 5. Claude Desktop

1. **Open the config file:** *Settings → Developer → Edit Config*. That opens `%APPDATA%\Claude\claude_desktop_config.json`.
2. **Add this** inside `"mcpServers"`, keeping any servers you already have:

   ```json
   "ryos-test": {
     "command": "C:\\RYOS-test\\windows-ai\\ryos-cli.exe",
     "args": ["mcp"],
     "env": {
       "APPDATA": "C:\\RYOS-test\\data",
       "PATH": "C:\\Windows\\System32;C:\\Windows"
     }
   }
   ```

3. **Quit Claude Desktop completely,** including from the tray, and open it again. `ryos-test` should appear in the tools/connectors menu with six tools: `list_scripts`, `list_pipelines`, `run_script`, `run_pipeline`, `get_run` and `stop_run`.
4. **In a new chat, ask in turn:**
   - "List my RYOS scripts." You should see `Test/hello` and `Test/slow`.
   - "Run Test/hello and show me the output." You should get "Hello from RYOS".
   - "Run Test/slow." You should get back a run ID.
   - "Check its output." The ticks so far should appear, and asking again should show more.
   - "Stop it." The run should stop before tick 60.

## 6. Claude Code

```powershell
claude mcp add ryos-test --scope user -e "APPDATA=C:\RYOS-test\data" -e "PATH=C:\Windows\System32;C:\Windows" -- C:\RYOS-test\windows-ai\ryos-cli.exe mcp
claude mcp list
```

`claude mcp list` should show `ryos-test` as connected. Start `claude` in any folder, check `/mcp`, and then ask the same five things as in step 5.

## 7. Check what RYOS recorded

In the Command Prompt from step 4:

```bat
ryos-cli history
```

The runs Claude started should be listed as started by an agent. The `slow` run should show as stopped.

## 8. The no-AI build refuses

In the same Command Prompt:

```bat
cd /d C:\RYOS-test\windows
ryos-cli mcp
echo %ERRORLEVEL%
```

You should get one line saying MCP isn't in this download, then `125`. There should be no traceback.

## 9. Clean up

- Remove the `ryos-test` entry from `claude_desktop_config.json`, then restart Claude Desktop.
- Run `claude mcp remove ryos-test --scope user`.
- Delete `C:\RYOS-test`.

## Tell the secretary

Report one line per step: passed, or what you saw instead. Screenshots of failures help.
