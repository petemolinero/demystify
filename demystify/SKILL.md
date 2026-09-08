---
name: demystify
description: Walk the user through every change in a branch or PR compared to its base branch, one logical change at a time, in plain layman's terms. For each change it explains how the code worked before, what the desired change was, how it was accomplished, and why each edit was necessary, pausing after each explanation for comprehension checks and follow-up questions. Use when the user wants a branch or PR explained, demystified, or walked through, asks "what does this PR/branch actually do", or wants to understand someone else's (or an agent's) changes without reading the diff themselves.
---

# Demystify

Interactive, plain-English walkthrough of everything a branch or PR changes relative to its base. The user is not assumed to know the codebase, the framework, or advanced programming jargon. The deliverable is understanding, not a summary dump: never explain more than one logical change between comprehension checks.

## Step 1: Resolve the target and base

- If the user gave a PR number/URL: `gh pr view <ref> --json baseRefName,headRefName,title,body,url`. Base = `baseRefName`, target = `headRefName`. Immediately post the PR as a markdown link in chat — both the PR itself and its diff view (`<url>/files`) — so the user can open the diff alongside the conversation and follow along as you walk through it.
- If the user gave a branch name: base = the repo's main branch (`git remote show origin | grep 'HEAD branch'` or the obvious default like `main`).
- If the user gave nothing, use the current branch; if the current branch IS the main branch, ask which branch or PR to demystify.
- Fetch first (`git fetch origin`) so the comparison is current.

## Step 2: Study the full diff privately

Do this work silently; don't dump it on the user.

1. Get the change list: `git diff --stat origin/<base>...<target>` and the full diff `git diff origin/<base>...<target>`. Use the three-dot form so you only see the branch's own changes.
2. Read `git log origin/<base>..<target> --oneline` and the PR title/body/linked ticket if available, to learn the *intent* behind the changes.
3. For each changed file, read enough surrounding pre-change code (`git show origin/<base>:<file>`) to genuinely understand how it worked BEFORE. You cannot explain "before vs after" from the diff hunks alone.
4. Group the changes into an ordered list of **logical changes** (a feature, a fix, a refactor step) — not one entry per file. Related edits across files that serve one purpose are one item.
5. **Find the narrative.** State, in a sentence or two, the problem this branch exists to solve. Then ask: if someone sat down to solve that problem, what sub-problems would they have to work through, and in what order? Those sub-problems are your logical changes. Order them the way a person would think through the problem (the thing you must have first, then what builds on it, then the loose ends it creates), not by file path or diff order. Each item should be the next step in a chain of reasoning: "we did X, but that alone leaves us with problem Y, so next we…".
6. Build a **coverage ledger**: every hunk in the diff (file + line range) assigned to exactly one logical change. Nothing may be left unassigned — if a hunk fits nowhere, it becomes its own item (even trivial ones like a version bump or whitespace fix, which can be covered in one sentence). Keep this ledger and mark items off as you explain them.

## Step 3: Present the roadmap

Give the user a short plain-English overview before diving in. This is the "here's the problem, here's the plan" beat of the story:

- One or two sentences on the problem the branch/PR solves and why it matters.
- The plan as a numbered list of the logical changes you'll walk through, phrased as steps toward solving that problem ("to get there we need to X, then Y, then Z"), one short line each.

Then start with change #1 — no need to ask permission to begin.

## Step 4: Walk through each logical change

Narrate each item as the next step in solving the problem, not as an isolated change. Open by placing it in the story ("First up, X…", "With X in place, the next problem is Y…", "Finally, Z, so we don't end up with <such-and-such>…"). Vary the wording; keep the shape. Then explain in this order, always in layman's terms:

1. **How it worked before** — what the old code did, described as behavior ("when a visitor clicked X, the site did Y"), not as code structure. Show the relevant old code (from `git show origin/<base>:<file>`) in a fenced snippet and narrate what it says.
2. **What we wanted instead** — the desired functionality or fix, and why the old behavior was a problem.
3. **How the change accomplishes it** — the approach taken, mechanically but simply. Show the new code in a fenced snippet (or a small before/after pair for edits) and walk through what it does. Analogies are welcome when they clarify.
4. **Why each edit was necessary** — connect every hunk in this group to the goal ("the test file changed because...", "this config line was needed so that..."), showing the code for each. No hunk in the group goes unexplained or unshown.
5. **What this sets up** — one sentence on what this step makes possible, or what new problem it leaves for the next step to solve. That hand-off is what makes the walkthrough read as a thought process instead of a list.

Motivate, don't just describe: every step answers "why did we need this?" in terms of the problem ("without this, the form would submit twice"), not the code ("this adds a guard"). If a step exists only to fix a problem an earlier step introduced, say so plainly; that's the most useful part of the story.

Style rules:

- Layman's terms throughout. Introduce any unavoidable technical term with a one-line plain definition the first time it appears.
- Spell the company "Medbridge" (lowercase b) in all your prose, even where the code, PR title, or ticket writes "MedBridge". Leave identifiers inside code snippets exactly as they appear.
- Short paragraphs. Always show the actual code you're describing — never describe a change in prose alone. Trim snippets to the relevant lines (with `...` for elided parts) and always narrate what the code says in plain English.
- Reference files as clickable links (e.g. [foo.ts](src/foo.ts:42)) so the user can jump in.

## Step 5: Comprehension check after EVERY explanation

After each logical change, stop and use AskUserQuestion (multiple choice):

- Question: "Did that explanation make sense?"
- Options: "Yes, makes sense — continue" (first), "Mostly, but I have a follow-up question", "No — explain it again more simply".

Handling answers:

- **Continue** → move to the next logical change.
- **Follow-up** → answer the question (in the same plain style; go read more code if needed). Then ask again with AskUserQuestion: "Ready to continue, or more questions?" with options "Continue to the next change", "Another follow-up question". Loop until they choose continue.
- **Explain again** → re-explain the same change more simply, with a different angle or analogy, then re-ask the comprehension check.

Never explain two changes back-to-back without a check in between, and never skip the check on the last change.

## Step 6: Verify coverage, then wrap up

Before the recap, audit the coverage ledger against the actual diff (`git diff --stat origin/<base>...<target>`): every file and every hunk must have been shown and explained in one of the walkthrough items. If anything was missed, walk through it now (with its own comprehension check) — 100% of the code changes must be covered before wrapping up.

After the final change is understood, close with a 3–5 sentence recap of the whole branch/PR in plain English: what it does now that it didn't before, and anything the user should watch for (risks, follow-ups, things not covered by the branch). Offer to answer any remaining questions.
