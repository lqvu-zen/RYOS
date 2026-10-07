# Adding a script

A *script* is any file you can run: Python (`.py`), batch (`.bat`, `.cmd`), PowerShell (`.ps1`), shell (`.sh`), JavaScript, and more. Add it once and it's a row you can run with one click.

## The quickest way: drop files in

Drag one or more script files from File Explorer onto the RYOS window. Each becomes a script in the group on screen, named after the file, with the right interpreter picked for you. If the group has a folder, files from outside it are skipped and RYOS says which.

## With the dialog

Click **+ Script** in the header (or **File → New Script…**). Fill in the dialog and click **Save**.

![The script dialog filled in: Name "Backup notes", the group's base folder, Path "backup.py" with Browse…, Parameters "--full" with + Preset, an empty Presets list, Interpreter, Group, three options, Working folder, Environment, and Save and Cancel](images/02-add-script-dialog.png)

| Field | What to enter |
| --- | --- |
| **Name** | What the row shows, e.g. *Backup notes*. |
| **Base folder** | The group's folder, shown for reference: paths below are relative to it. |
| **Path** | The script file. Type it or click **Browse…**. |
| **Parameters** | *(optional)* Arguments to pass on every run. See [Parameters and presets](05-parameters-and-presets.md). |
| **+ Preset** / **Presets** | *(optional)* Saved sets of parameters to pick from. |
| **Interpreter** | *(optional)* Leave blank and RYOS picks one from the file's extension. |
| **Group** | Which group the script belongs to. |
| **Ask for a temporary parameter on each run** | RYOS asks for extra arguments every time you run it. |
| **Launcher** | For a script that opens an app or project and leaves it running: RYOS doesn't keep it in the Running list. |
| **Available to agents** | Lets an AI agent connected to RYOS run it. Off unless you tick it. See [The command line and AI agents](13-command-line-and-agents.md). |
| **Working folder** | *(optional)* The folder it runs in. Blank means the script's own folder. |
| **Environment** | *(optional)* Extra variables, one `KEY=value` per line. |

To change a script later, point at its row and click the pencil, or right-click it and choose **Edit…**. The same dialog has a **Delete** button at the bottom left.

---
[← The main window](01-main-window.md) · [Contents](README.md) · [Next: Running a script →](03-running-and-output.md)
