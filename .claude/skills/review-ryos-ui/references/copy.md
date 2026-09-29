# Lens 3: copy (buttons, messages, empty states)

Adapted from the `design:ux-copy` skill. Words are part of the interface:
a vague button or a message that says only "Error" costs as much as a
misplaced control.

## Where the words live

Wording that decides what shows is kept in the rule modules, not the Qt code,
so read those first:

| Words | Module |
| --- | --- |
| Section headers, empty texts, All tab, + Script | `ryos/sections.py` |
| Card and tab menus, delete prompts | `ryos/cardmenu.py` |
| Run/Retry tooltips, badges, status words, steps summary | `ryos/cardstyle.py` |
| Select mode bar, delete-selected prompt | `ryos/selection.py` |
| Output panel buttons and messages | `ryos/outputpanel.py` |
| Export, import, Delete All | `ryos/configio.py` |
| Tray, close, quit prompts | `ryos/traypolicy.py` |
| Script dialog, parameters, ask-each-run | `ryos/scriptform.py` |
| Pipeline editor, step policies | `ryos/pipelinesteps.py` |
| Schedule dialog | `ryos/scheduleform.py` |
| Options labels | `ryos/settings_schema.py` |
| Maximised pane | `ryos/detail.py` |

Changing wording there means updating the unit tests that pin it; that is
intended -- the words were chosen, and the test says so.

## Patterns

- **Buttons start with a verb and say the outcome**: "Run", "Save",
  "Delete script" -- not "OK", "Submit", "Go". A dialog's primary button
  names what it does ("Save", "Create group").
- **Errors: what happened, why, what to do.** "Couldn't find hello.py. It was
  moved or deleted -- edit the script to point at it again." Not "File not
  found".
- **Empty states: what goes here, and how to start.** "No scripts yet -- drop
  a file here or click + Script."
- **Confirmations name the thing and the consequence.** "Delete 'Build'? It
  is used in 2 pipelines, which lose that step." Buttons: "Delete" /
  "Keep", not "Yes" / "No".
- **Tooltips add something.** "Run" on a green ▶ is fine; a tooltip that
  repeats a visible label is noise.
- **One word per thing.** Pick "favorites" or "favourites", "parameters" or
  "arguments", "group" or "tab", and use it everywhere (menus, dialogs,
  tooltips, the tutorial).
- **Sentence case** for labels and buttons ("Run with parameters…"); title
  case only for the window title. An ellipsis (…) marks a button that opens
  a dialog before acting.
- **Plain words.** The people using RYOS write scripts, but "stdout" and
  "exit code 3" belong in the output, not in a message.

## Output for this lens

Findings tagged `[copy]`, each with the current text, the proposed text and
the file it lives in. Group repeated problems (the same term used two ways)
into one finding listing every place.
