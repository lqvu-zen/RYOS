# Tutorial screenshots

Every image here is generated, not hand-captured. From the repo root:

```bash
uv run python .claude/skills/ryos-tutorial-generator/scripts/capture.py
```

It builds the real window off screen (nothing appears on any monitor) on a
throwaway copy of `samples/`, in the Light theme, walks the guide in reading
order and saves each step as `NN-name.png`. Re-run it after any UI change and
the pages, which link to these names, pick the new pictures up.
