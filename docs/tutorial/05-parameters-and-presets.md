# Parameters and presets

Many scripts take *parameters* — extra words on the command line that change what they do, like `--name RYOS` or `--loud`. RYOS gives you three ways to pass them.

## Saved parameters

Type them into **Parameters** in the script dialog. They're passed on every run. Quoting works as you'd expect: `--title "My report"` is one value.

## Presets: several sets to choose from

If you run a script with a few different sets of parameters, save each as a **preset**: type it into **Parameters** and click **+ Preset**. The **Presets** list below holds them; **Use** puts one back into Parameters, **Edit** changes it, **Remove** deletes it.

![The script dialog for Say hello with three presets: "--name RYOS", "--loud" and "--loud --name Team", and Use, Edit and Remove under the list](images/05-script-presets.png)

A script with presets shows the one Run will use on its row, next to the file name. Click it to pick another:

![The preset menu under a row: (no parameters), --name RYOS (ticked), --loud and --loud --name Team](images/05-preset-menu.png)

## Just this once

- **Run with parameters…** — point at a row and click the play-with-a-plus button, or right-click → **Run with parameters…**. Type the parameters and run. They're remembered as the script's parameters and added as a preset.
- **Ask for a temporary parameter on each run** — tick this in the script dialog and RYOS asks for **Parameters for this run** every time you press Run; **Run** goes ahead. What you type is used for that run only and added after the saved parameters; nothing is kept.

![The prompt that appears before a run: "Parameters for this run" holding "--name Friday", a note that it is used for this run only and nothing is kept, and Run and Cancel](images/05-ask-each-run.png)

---
[← Groups](04-groups.md) · [Contents](README.md) · [Next: Pipelines →](06-pipelines.md)
