# demystify

Two Claude Code skills for explaining a branch or pull request in plain language.

- `demystify/` — interactive chat walkthrough, one logical change at a time, with comprehension checks.
- `demystify-html/` — generates a single self-contained HTML page: the full diff with margin annotation cards connected to the lines they explain, test diffs collapsed at the bottom.

## Install

Symlink (or copy) each skill folder into your skills directory:

```bash
ln -s "$PWD/demystify" ~/.claude/skills/demystify
ln -s "$PWD/demystify-html" ~/.claude/skills/demystify-html
```
