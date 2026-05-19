Commit and push the latest changes to GitHub.

## Steps

1. Check what has changed:
```bash
cd D:/Projects/RYOS && git status 2>&1
```
```bash
cd D:/Projects/RYOS && git diff 2>&1
```

2. If there are no changes, report "Nothing to commit" and stop.

3. Review the diff and write a concise commit message that describes what changed and why (not just what files changed). Follow the existing commit style from:
```bash
cd D:/Projects/RYOS && git log --oneline -5 2>&1
```

4. Stage and commit:
```bash
cd D:/Projects/RYOS && git add -p -- script_runner.py tests/ .claude/ README.md CLAUDE.md *.spec *.bat 2>&1
```
> Stage only tracked/relevant files — never stage `.env`, `scripts.db`, `dist/`, `build/`, or `__pycache__`.

Actually use targeted adds based on what `git status` showed is modified. For example:
```bash
cd D:/Projects/RYOS && git add <file1> <file2> ... 2>&1
```

5. Commit with a clear message:
```bash
cd D:/Projects/RYOS && git commit -m "$(cat <<'EOF'
<commit message here>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)" 2>&1
```

6. Push:
```bash
cd D:/Projects/RYOS && git push 2>&1
```

7. Report the commit hash and message.
