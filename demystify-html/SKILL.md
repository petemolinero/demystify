---
name: demystify-html
description: Generate a single scrollable HTML page that shows the complete annotated diff of a branch or PR versus its base branch - every hunk rendered as a standard git diff, grouped into logical changes, with plain-language annotation cards in the left and right margins connected by lines to the exact code lines they describe. Use when the user wants an annotated diff page, an HTML explanation of a branch or PR, a scrollable/visual demystify, or says "demystify-html". For an interactive chat walkthrough instead, use the demystify skill.
---

# Demystify HTML

Produce one self-contained HTML file: the full diff of a branch/PR against its base rendered as standard git diffs, with plain-language annotation cards in the side rails pointing (via connector lines) at the exact lines they explain. Hovering a card highlights its lines and vice versa; on narrow screens cards stack inline above their diff block. The page also has a built-in feedback loop: the reader can select any text (code, annotation, or prose), click **Comment**, and keep going; a sticky **Copy prompt** button in the bottom-right turns all comments into one numbered prompt (quoted text, then the comment) that they can paste back to an agent. The bundled script renders the page and enforces 100% coverage — it fails and lists any hunk you haven't annotated. Your job is the understanding and the writing; the script's job is the HTML.

## Step 1: Resolve the target and base

- PR number/URL: `gh pr view <ref> --json baseRefName,headRefName,title,body,url`. Base = `baseRefName`, target = `headRefName`. Keep the URL for `--pr-url`.
- Branch name: base = the repo's main branch (`git remote show origin | grep 'HEAD branch'`, or the obvious default like `main`).
- Nothing given: use the current branch; if it IS the main branch, ask which branch/PR to demystify.
- `git fetch origin` first so the comparison is current.

## Step 2: Enumerate the hunks

Run the script once with an empty annotations file to get the authoritative hunk list:

```bash
echo '{"sections": [], "hunks": {}}' > /tmp/ann.json
python3 <skill_dir>/scripts/build.py --repo <repo> --base origin/<base> --target <target> \
  --annotations /tmp/ann.json --out /tmp/preview.html --allow-unannotated
```

The stderr "MISSING annotations" list is every hunk key you must cover, in the form `path/to/file#<hunk-index>` (0-based per file; binary/rename-only files get a single pseudo-hunk `#0`).

## Step 3: Understand the changes

- Read the full diff (`git diff origin/<base>...<target>`), the commit log, and the PR title/body for intent.
- For anything non-obvious, read the pre-change code (`git show origin/<base>:<file>`) so "before" explanations are grounded, not guessed from hunks.
- Group hunks into ordered **logical changes** (a feature, a fix, a refactor step — not one per file). Trivial leftovers (version bumps, whitespace) get their own small section such as "Housekeeping".
- **Tests go in their own collapsed section at the bottom.** Every hunk in a test file (`tests/`, `__tests__/`, `*.test.*`, `*.spec.*`, `*Test.php`, fixtures/snapshots/factories used only by tests) belongs to a single section with `"collapsed": true`, titled "Tests" or similar. Never mix test hunks into the narrative sections; instead, when a narrative section's behavior is covered by a test, mention that in its explanation in one clause ("the Tests section at the bottom checks this for both plan types"). The script forces collapsed sections to the bottom regardless of where they sit in the list.
- **Find the narrative before you write anything.** Work out, in one or two sentences, what problem this PR exists to solve. Then ask: if someone sat down to solve that problem, what sub-problems would they have to work through, and in what order? Those sub-problems are your sections. Order them the way a person would think through the problem (the thing you must have first, then what builds on it, then the loose ends it creates), not by file path or by the order hunks appear in the diff. Each section should feel like the next step in a chain of reasoning: "we did X, but that alone leaves us with problem Y, so next we…".

## Step 4: Write the annotations JSON

Work in the scratchpad directory. Shape:

```json
{
  "title": "Short page title (PR title or branch purpose)",
  "subtitle": "One plain-English sentence on what this branch/PR is for",
  "intro": "<p>The problem this PR solves and why it matters, then the plan: 'to solve this we need to do X, Y, and Z'. One short paragraph naming each step so the reader knows the shape of the story before reading it.</p>",
  "sections": [
    {"id": "sec-1", "title": "Plain-English change title",
     "explanation": "<p>Where we are in the story ('First up, X…' / 'With X in place, the next problem is Y…'), how things worked before, what we needed instead and why, how this group of edits gets us there, and what it sets up for the next section. Layman's terms; define any unavoidable jargon inline.</p>"},
    {"id": "tests", "title": "Tests", "collapsed": true,
     "explanation": "<p>One short paragraph: what behaviors the tests pin down, in plain English. The section renders closed with a click-to-expand heading and always sits last.</p>"}
  ],
  "hunks": {
    "src/foo.php#0": {
      "section": "sec-1",
      "annotations": [
        {"note": "What these lines do and why, in 1-3 plain sentences.", "new": 123, "count": 3, "side": "right"},
        {"note": "Note about a deleted line.", "old": 45}
      ]
    }
  }
}
```

Annotation anchoring (each annotation becomes a margin card with a connector line to its code line):

- `new`: line number in the NEW file (use for added/context lines) — read it straight off the `+` side of the hunk header math, or from the rendered preview's line-number column.
- `old`: line number in the OLD file (use for deleted lines).
- Omit both to anchor to the hunk's first changed line. The script warns if a given number isn't in that hunk (and falls back to the first change) — treat those warnings as errors and fix them.
- `count`: how many consecutive rendered lines the note covers (highlight span, default 1).
- `side`: `left` or `right` rail; omit to auto-alternate. Put related notes on opposite sides when they'd otherwise crowd.
- Test hunks still need real annotations (coverage is enforced for them too), but keep each note to one sentence saying what behavior that test asserts.

Rules for the writing:

- **Tell it as a narrative, not a changelog.** The page should read like someone walking the reader through how they would think about the problem: "To pull this off we need to do X, Y, and Z. First up, X: here's why it's needed and how we did it. With X in place we can tackle Y… Finally, Z, so that we don't end up with <such-and-such problem>." Don't reuse that wording verbatim every time; do keep the shape: problem, plan, then each step motivated by the one before it. A reader who only reads the intro plus the section explanations should understand the whole PR and why each step exists.
- **Layman's terms everywhere.** Describe behavior ("when a visitor clicks X, the site now does Y"), not code structure. Define any unavoidable technical term the first time it appears.
- **Spell the company "Medbridge"** (lowercase b) everywhere in the title, intro, sections, and notes, even where the code, PR title, or ticket writes "MedBridge". Leave identifiers inside `<code>` exactly as they appear in the code.
- **The intro** states the problem and lays out the plan (the sections, in order, in one sentence each). **Section explanations** each pick up where the previous one left off: why this step is next, before / desired / how / why, and what it hands off to the next step. A short paragraph or two. Simple HTML (`<p>`, `<strong>`, `<code>`) is allowed.
- **Motivate, don't just describe.** Every step should answer "why did we need this?" in terms of the problem, not the code: "without this, the form would submit twice", not "this adds a guard". If a step exists only to avoid a problem a previous step introduced, say so explicitly; that's the most useful part of the story.
- **Anchor notes to the line that matters** — the note sits beside the code, so point it at the specific line(s) it discusses, not just the top of the hunk. A big hunk with several interesting spots deserves several annotations.
- **Each note is specific to its lines** — what these exact lines change and why the edit was necessary. Never a generic "part of the above"; say what THIS piece contributes to the step its section is about.
- Every key from Step 2's missing list must appear in `hunks` with at least one annotation, assigned to a real section id. `{"note": "..."}` on a hunk is shorthand for one annotation anchored to its first change — fine for trivial hunks (lockfiles, version bumps).

## Step 5: Build, verify, deliver

```bash
python3 <skill_dir>/scripts/build.py --repo <repo> --base origin/<base> --target <target> \
  --annotations <scratchpad>/annotations.json --out <scratchpad>/demystified-<branch>.html \
  --pr-url <url-if-pr>
```

- The script exits 1 and lists missing keys if any hunk is unannotated — fix the JSON and rerun until it reports full coverage (the page footer shows "N/N hunks annotated"). Never ship with `--allow-unannotated`.
- Also fix any "nonexistent hunk key" warnings (usually a typo'd path or index).
- Send the finished HTML to the user with SendUserFile (`display: "render"`), with a one-line caption naming the branch/PR and the number of changes covered, plus a reminder that they can select text, click Comment, and use Copy prompt to send feedback back. Do not commit the file to the repo.
- When the user pastes such a prompt back ("Work through this feedback one item at a time…"), each numbered item quotes page text and gives a location like `src/foo.php line 12` or `section "…"`. Address them in order: fix the code, the annotation text, or the section explanation as appropriate, rebuild the page, and resend it.
