# Lens 1: critique (first look, hierarchy, usability)

Adapted from the `design:design-critique` skill and the desktop parts of
`qt-development-skills:qt-ui-design`, for a native desktop tool. Run it on
the screenshots before reading any code: it is about what a person sees.

## The two-second look

For each screenshot, before anything else, write down:

- **What the eye lands on first.** On the main window it should be the list
  of things to run, and on a row the name, then Run. If it is the header,
  a badge, a scrollbar or an empty area, that is the first finding.
- **Whether the purpose is clear.** Would someone who has never seen RYOS
  know this is "a list of my scripts, press the green button"?
- **The reading order.** Follow the eye: header → group pills → sections →
  rows → output. Name where it stalls or jumps.

## Usability: the tasks that matter

Walk each through the screenshots and the source. Count the steps, and note
anything a person has to remember rather than see.

| Task | Good means |
| --- | --- |
| Run a script | One click on the row's Run, from rest |
| Run with other parameters | Pick the preset chip, or ▶+ / Run with…, without opening Edit |
| See why a run failed | The row says Failed; one click shows the output tab |
| Run it again | Retry is where Run was |
| Add a script | + Script, or drop a file on the window |
| Find a script among many | Type in the filter; the count says how many match |
| Group scripts | + Group, drag a row onto a pill |
| Chain scripts | + Pipeline; the editor shows the order and what happens on failure |

## Laws worth applying here

- **Hick**: fewer choices, faster decisions. Count the controls visible at
  rest on a row and in each dialog; ask what could wait for the pointer or
  a menu.
- **Fitts**: frequent actions get big, near targets. Run is the most
  pressed control in the app; it should be the easiest to hit.
- **Recognition over recall**: show the options (preset chips, the steps
  list) rather than asking for typed parameters from memory.
- **Proximity and similarity**: things that belong together sit together and
  look alike (a row's kind, name and outcome; a dialog's related fields).
- **Von Restorff**: one distinct thing draws the eye. There should be one
  per area (Run, + Script, Save); two competing is a finding.
- **Doherty**: feedback within 400 ms. Pressing Run should change something
  on screen at once, before the script prints anything.
- **Peak-end**: people remember the worst moment and the ending. A failed
  run and the end of a run deserve the most care.
- **Wayfinding**: people always know where they are: the chosen group pill,
  the chosen row (maximised), the output tab in front.

## Output for this lens

- The two-second look for each screen, in a sentence or two.
- Usability findings in the report's severity sections, tagged `[critique]`.
- A **What works** list: patterns to keep. Name them specifically ("Run sits
  at the same x on every row") so they survive the next pass.
