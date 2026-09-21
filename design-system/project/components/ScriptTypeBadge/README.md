# ScriptTypeBadge

The language chip leading a card's name row. `_script_tag()` in
`ryos/interpreter.py`.

Maps a file extension to `(label, fill)` — thirteen known types plus a fallback
that upper-cases the extension onto `tag-unknown`. `badge` type, `fg_on_dark`
on the fill.

These fills **do not theme**. The badge names the language, and the colour is
part of that label the way a language's own brand colour is: Python's navy,
Shell's green, VS Code's blue. A user switching to Sepia still expects
PowerShell to be PowerShell.

## Rules

- Extend the `tags` dict; don't special-case at a call site. The same map feeds
  the card, the pipeline step editor and the hover preview.
- An unknown extension falls back to the upper-cased extension on
  `tag-unknown` — never to a blank badge or to `accent`.
- `.bat` and `.cmd` share `tag-batch`; `.exe` is its own darker grey.
