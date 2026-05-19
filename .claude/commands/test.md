Run the RYOS unit test suite and automatically fix any failures.

## Steps

1. Run the full test suite:
```bash
cd D:/Projects/RYOS && uv run python -m unittest discover -s tests -v 2>&1
```

2. **If all tests pass** — report "All tests passed" with the count and stop.

3. **If there are failures or errors** — for each failing test:
   a. Read the relevant section of `tests/test_ryos.py` and `script_runner.py` to understand what broke.
   b. Determine whether the bug is in the source code (`script_runner.py`) or in the test itself:
      - If the source code has a real bug: fix `script_runner.py`.
      - If the test expectation is wrong (e.g. platform-specific behavior, wrong assumption): fix `tests/test_ryos.py`.
   c. Apply the fix with the Edit tool.

4. Re-run the tests after fixing:
```bash
cd D:/Projects/RYOS && uv run python -m unittest discover -s tests -v 2>&1
```

5. Repeat steps 3–4 until all tests pass (max 3 fix iterations — if still failing after that, report what's left and ask the user).

6. Report a summary: how many tests passed, what was fixed and in which file.
