RYOS samples -- scripts for trying the app.

Load them
  1. uv run python samples/make_import.py
     (writes samples/ryos-samples.json for wherever this folder is)
  2. In RYOS: Options -> Import config -> ryos-samples.json -> No (merge).
     A "Samples" group appears, with this folder as its base folder.
  To remove them: right-click the Samples tab -> Delete, then delete its
  cards, or Options -> Delete All if you have nothing else.

Scripts
  Say hello        Run it; pick a preset in its drop-down; use the +
                   button beside Run to type new parameters. Its
                   environment sets RYOS_SAMPLE, which it prints.
  Always fails     Exit code 3: the Run button turns into Retry, stderr
                   shows red. Highlighted red.
  Flaky            Fails about half the time.
  Count a minute   Try Stop, the Running list, and closing to the tray.
  Lots of output   3000 lines: try Find, Errors only and the line cap.
  Ask each run     Asks for a parameter every time it runs.
  Write a report   Writes a timestamped file into reports/.
  Cleanup          Used by the Resilient pipeline.
  List folder      A .bat file (runs with cmd).
  System info      A .ps1 file (runs with PowerShell).

Pipelines
  Morning report   Say hello, then Write a report.
  Resilient        Flaky (3 retries, keep going) -> Always fails (keep
                   going) -> Cleanup (only if something failed) -> Say hello.
  Side by side     Count a minute and Lots of output at the same time.

Also try
  Quick Run (type "hello" in the Samples tab), search, select mode
  (Options), favourites, highlight colours (right-click), a schedule
  (right-click -> Schedule), dragging cards to reorder, and themes
  (Options -> Appearance).
