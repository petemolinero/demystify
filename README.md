# demystify

A Claude Code skill that explains a branch or pull request in plain language.

`demystify/` generates a single self-contained HTML page, published as a Claude artifact: the full diff versus the base branch, grouped into logical changes and told as a problem-first narrative, with margin annotation cards connected to the exact lines they explain. Test diffs sit in a collapsed section at the bottom. Readers can select any text, comment on it, and copy all comments as one numbered prompt to send back.

## Install

Symlink (or copy) the skill folder into your skills directory:

```bash
ln -s "$PWD/demystify" ~/.claude/skills/demystify
```
