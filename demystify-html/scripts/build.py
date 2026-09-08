#!/usr/bin/env python3
"""Render an annotated diff HTML page from a git diff plus an annotations JSON.

Usage:
  build.py --base origin/main --target my-branch --annotations ann.json --out out.html
           [--repo /path/to/repo] [--pr-url URL] [--allow-unannotated]

Annotations JSON shape:
{
  "title": "Page title",
  "subtitle": "optional one-liner",
  "intro": "<p>Plain-language overview HTML</p>",
  "sections": [
    {"id": "sec-1", "title": "Section title", "explanation": "<p>HTML</p>"},
    {"id": "tests", "title": "Tests", "explanation": "<p>HTML</p>", "collapsed": true}
  ],
  "hunks": {
    "path/to/file.ext#0": {
      "section": "sec-1",
      "annotations": [
        {"note": "Plain-language note", "new": 123, "count": 3, "side": "right"},
        {"note": "Another note", "old": 45}
      ]
    }
  }
}

Hunk keys are "<new file path>#<hunk index within that file, 0-based>".
Each annotation anchors to a code line: "new" = line number in the new file
(add/context lines), "old" = line number in the old file (deleted/context
lines); omit both to anchor to the hunk's first changed line. "count" extends
the highlight over that many rendered rows (default 1). "side" is left/right
(auto-alternates when omitted). Notes render as cards in the side rails with
connector lines pointing at their line. {"note": "..."} alone on a hunk is
shorthand for one annotation. A section with "collapsed": true renders as a
closed, click-to-expand block and is always placed at the bottom of the page
(used for tests).

Binary or metadata-only file changes get a single pseudo-hunk with index 0
(anchor is the file header). Every hunk needs at least one annotation;
unannotated hunks land in a highlighted "Not yet annotated" section and the
script exits 1 (unless --allow-unannotated), printing the missing keys.
"""
import argparse
import html
import json
import re
import subprocess
import sys


def run_git(repo, args):
    return subprocess.run(["git", "-C", repo] + args, capture_output=True,
                          text=True, check=True).stdout


def parse_diff(text):
    """Return list of files: {path, old_path, status, binary, hunks:[{header, lines:[(tag, old_no, new_no, text)]}]}"""
    files = []
    cur = None
    hunk = None
    old_no = new_no = 0
    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            m = re.match(r'diff --git "?a/(.*?)"? "?b/(.*?)"?$', raw)
            cur = {"path": m.group(2) if m else raw, "old_path": m.group(1) if m else raw,
                   "status": "modified", "binary": False, "hunks": []}
            files.append(cur)
            hunk = None
        elif cur is None:
            continue
        elif raw.startswith("new file mode"):
            cur["status"] = "added"
        elif raw.startswith("deleted file mode"):
            cur["status"] = "deleted"
        elif raw.startswith("rename from "):
            cur["old_path"] = raw[len("rename from "):]
            cur["status"] = "renamed"
        elif raw.startswith("rename to "):
            cur["path"] = raw[len("rename to "):]
        elif raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
            cur["binary"] = True
        elif raw.startswith("@@"):
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)", raw)
            old_no, new_no = int(m.group(1)), int(m.group(2))
            hunk = {"header": raw, "lines": []}
            cur["hunks"].append(hunk)
        elif hunk is not None:
            if raw.startswith("+"):
                hunk["lines"].append(("add", None, new_no, raw[1:]))
                new_no += 1
            elif raw.startswith("-"):
                hunk["lines"].append(("del", old_no, None, raw[1:]))
                old_no += 1
            elif raw.startswith("\\"):
                hunk["lines"].append(("meta", None, None, raw))
            else:
                hunk["lines"].append(("ctx", old_no, new_no, raw[1:] if raw else ""))
                old_no += 1
                new_no += 1
    # Files with no hunks (binary, mode/rename only) get one pseudo-hunk so they need coverage too.
    for f in files:
        if not f["hunks"]:
            label = "Binary file changed" if f["binary"] else "File changed with no text diff (rename, mode, or metadata change)"
            f["hunks"].append({"header": label, "lines": [], "pseudo": True})
    return files


CSS = """
:root { --bg:#fff; --fg:#1f2328; --muted:#57606a; --border:#d0d7de; --file-bg:#f6f8fa;
  --add-bg:#e6ffec; --add-strong:#abf2bc; --del-bg:#ffebe9; --del-strong:#ffc0c0;
  --note-bg:#f0f5ff; --note-border:#3b6fd4; --warn-bg:#fff8c5; --warn-border:#d4a72c;
  --lineno:#8c959f; --link:#0969da; --card-shadow:0 1px 4px rgba(31,35,40,.1);
  --tgt-tint:rgba(59,111,212,.14); --tgt-hot:rgba(59,111,212,.28); --warn-tint:rgba(212,167,44,.18); }
@media (prefers-color-scheme: dark) { :root { --bg:#0d1117; --fg:#e6edf3; --muted:#8b949e;
  --border:#30363d; --file-bg:#161b22; --add-bg:#12261e; --add-strong:#1f4429;
  --del-bg:#2d1214; --del-strong:#542426; --note-bg:#111c31; --note-border:#4c7fe0;
  --warn-bg:#2b2611; --warn-border:#b08800; --lineno:#6e7681; --link:#4c9aff;
  --card-shadow:0 1px 4px rgba(0,0,0,.4);
  --tgt-tint:rgba(76,127,224,.16); --tgt-hot:rgba(76,127,224,.32); --warn-tint:rgba(176,136,0,.2); } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
a { color:var(--link); }
.layout { display:flex; max-width:1760px; margin:0 auto; gap:20px; padding:0 16px; }
nav { position:sticky; top:0; align-self:flex-start; width:220px; flex:none;
  max-height:100vh; overflow-y:auto; padding:24px 0; font-size:13.5px; }
nav ol { padding-left:20px; margin:8px 0; }
nav li { margin:6px 0; }
main { flex:1; min-width:0; padding:24px 0 80px; }
header h1 { margin:0 0 4px; font-size:24px; }
header .meta { color:var(--muted); margin-bottom:8px; }
.intro { border:1px solid var(--border); border-radius:8px; padding:4px 16px; margin:16px 0 32px; }
section.change, details.change { margin-bottom:56px; }
section.change > h2, details.change > summary > h2 { border-bottom:2px solid var(--border); padding-bottom:6px; font-size:20px; }
details.change > summary { cursor:pointer; list-style:none; }
details.change > summary::-webkit-details-marker { display:none; }
details.change > summary > h2 { display:flex; align-items:center; gap:10px; margin:0 0 16px; }
details.change > summary > h2::before { content:''; width:0; height:0; border-style:solid; border-width:6px 0 6px 9px;
  border-color:transparent transparent transparent var(--muted); transition:transform .15s; flex:none; }
details.change[open] > summary > h2::before { transform:rotate(90deg); }
details.change > summary .hint { font:400 13px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  color:var(--muted); margin-left:auto; }
details.change[open] > summary .hint { display:none; }
.explanation { margin-bottom:16px; max-width:860px; }
.warn-section > h2 { color:var(--warn-border); }
.annotated { display:grid; grid-template-columns:minmax(170px,250px) minmax(0,1fr) minmax(170px,250px);
  gap:18px; position:relative; }
.rail { position:relative; min-width:0; }
.card { position:absolute; left:0; right:0; background:var(--note-bg);
  border:1px solid var(--note-border); border-radius:8px; padding:8px 12px;
  font-size:13px; line-height:1.5; box-shadow:var(--card-shadow); }
.card.warn { background:var(--warn-bg); border-color:var(--warn-border); }
.card.hot { box-shadow:0 0 0 2px var(--note-border), var(--card-shadow); }
.card .loc { display:block; color:var(--muted); font:11px/1.4 ui-monospace,Menlo,monospace;
  margin-bottom:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
svg.connectors { position:absolute; inset:0; pointer-events:none; overflow:visible; z-index:1; }
svg.connectors path { fill:none; stroke:var(--note-border); stroke-width:1.5; opacity:.5; }
svg.connectors path.warn { stroke:var(--warn-border); }
svg.connectors path.hot { opacity:1; stroke-width:2.25; }
.annotated.stacked { display:block; }
.annotated.stacked .rail { display:none; }
.annotated.stacked svg.connectors { display:none; }
.annotated.stacked .card { position:static; margin:10px 0 6px; }
.diffcol { min-width:0; }
.diff { border:1px solid var(--border); border-radius:8px; overflow:hidden; margin:0 0 20px; }
.diff .filehead { background:var(--file-bg); border-bottom:1px solid var(--border);
  padding:8px 12px; font:600 13px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace; }
.diff .filehead .status { font-weight:400; color:var(--muted); margin-left:8px; }
.diff .hunkhead { background:var(--file-bg); color:var(--muted); padding:2px 12px;
  font:12px/1.8 ui-monospace,Menlo,monospace; border-top:1px solid var(--border); }
.diff .scroll { overflow-x:auto; }
.diff table { border-collapse:collapse; width:100%; font:12.5px/1.7 ui-monospace,SFMono-Regular,Menlo,monospace; }
.diff td { padding:0 10px; white-space:pre; vertical-align:top; }
.diff td.no { width:1%; min-width:44px; text-align:right; color:var(--lineno);
  user-select:none; border-right:1px solid var(--border); }
.diff tr.add td.code { background-color:var(--add-bg); }
.diff tr.add td.no { background-color:var(--add-strong); }
.diff tr.del td.code { background-color:var(--del-bg); }
.diff tr.del td.no { background-color:var(--del-strong); }
.diff tr.meta td.code { color:var(--muted); font-style:italic; }
.diff tr.tgt td { background-image:linear-gradient(var(--tgt-tint), var(--tgt-tint)); }
.diff tr.tgt td.no:first-child { box-shadow:inset 3px 0 0 var(--note-border); }
.diff tr.tgt.warn-tgt td { background-image:linear-gradient(var(--warn-tint), var(--warn-tint)); }
.diff tr.tgt.warn-tgt td.no:first-child { box-shadow:inset 3px 0 0 var(--warn-border); }
.diff tr.hot td { background-image:linear-gradient(var(--tgt-hot), var(--tgt-hot)); }
.coverage { border:1px solid var(--border); border-radius:8px; padding:12px 16px;
  color:var(--muted); font-size:14px; }
@media (max-width: 900px) { .layout { flex-direction:column; } nav { position:static; width:auto; } }
"""

JS = """
(function () {
  // Hash navigation breaks in sandboxed/blob previewers; scroll directly instead.
  document.querySelectorAll('nav a[href^="#"]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var el = document.getElementById(a.getAttribute('href').slice(1));
      if (el) {
        e.preventDefault();
        if (el.tagName === 'DETAILS' && !el.open) el.open = true;
        el.scrollIntoView({behavior: 'smooth', block: 'start'});
      }
    });
  });

  // Collapsed sections have no layout while closed; wire connectors once opened.
  document.querySelectorAll('details.change').forEach(function (d) {
    d.addEventListener('toggle', function () {
      if (d.open) d.querySelectorAll('.annotated').forEach(layout);
    });
  });

  var NS = 'http://www.w3.org/2000/svg';

  function targetRows(card) {
    var row = document.getElementById(card.dataset.target);
    if (!row) return [];
    var rows = [row];
    if (row.tagName === 'TR') {
      var n = parseInt(card.dataset.span || '1', 10);
      var sib = row.nextElementSibling;
      while (rows.length < n && sib) { rows.push(sib); sib = sib.nextElementSibling; }
    }
    return rows;
  }

  function wire(card) {
    var rows = targetRows(card);
    rows.forEach(function (r) {
      r.classList.add('tgt');
      if (card.classList.contains('warn')) r.classList.add('warn-tgt');
    });
    function set(on) {
      card.classList.toggle('hot', on);
      rows.forEach(function (r) { r.classList.toggle('hot', on); });
      var p = document.getElementById('path-' + card.id);
      if (p) p.classList.toggle('hot', on);
    }
    card.addEventListener('mouseenter', function () { set(true); });
    card.addEventListener('mouseleave', function () { set(false); });
    rows.forEach(function (r) {
      r.addEventListener('mouseenter', function () { set(true); });
      r.addEventListener('mouseleave', function () { set(false); });
    });
  }

  function layout(w) {
    var cards = Array.prototype.slice.call(w.querySelectorAll('.card'));
    var svg = w.querySelector('svg.connectors');
    var narrow = w.offsetWidth < 820;
    w.classList.toggle('stacked', narrow);
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    if (narrow) {
      // Stack each card inline, just above the diff block that holds its line.
      cards.forEach(function (c) {
        var block = document.getElementById(c.dataset.diff);
        if (block) block.parentNode.insertBefore(c, block);
        c.style.top = '';
      });
      w.style.minHeight = '';
      return;
    }

    // Home the cards back into their rails (after a stacked pass or on first run).
    cards.forEach(function (c) {
      var rail = w.querySelector(c.dataset.side === 'left' ? '.rail-left' : '.rail-right');
      if (c.parentNode !== rail) rail.appendChild(c);
    });

    var wr = w.getBoundingClientRect();

    var maxBottom = 0;
    ['left', 'right'].forEach(function (side) {
      var sideCards = cards.filter(function (c) { return c.dataset.side === side; });
      sideCards.forEach(function (c) {
        var rows = targetRows(c);
        c._ty = rows.length ? rows[0].getBoundingClientRect().top - wr.top : 0;
      });
      sideCards.sort(function (a, b) { return a._ty - b._ty; });
      var prevBottom = 0;
      sideCards.forEach(function (c) {
        var top = Math.max(c._ty - 4, prevBottom);
        c.style.top = top + 'px';
        prevBottom = top + c.offsetHeight + 14;
      });
      maxBottom = Math.max(maxBottom, prevBottom);
    });
    w.style.minHeight = Math.ceil(maxBottom) + 'px';

    // Size the overlay after minHeight so connectors can reach every card.
    var wh = Math.max(w.offsetHeight, Math.ceil(maxBottom));
    svg.setAttribute('width', w.offsetWidth);
    svg.setAttribute('height', wh);
    svg.setAttribute('viewBox', '0 0 ' + w.offsetWidth + ' ' + wh);

    wr = w.getBoundingClientRect();
    cards.forEach(function (c) {
      var rows = targetRows(c);
      if (!rows.length) return;
      var cr = c.getBoundingClientRect();
      var tr = rows[0].getBoundingClientRect();
      var left = c.dataset.side === 'left';
      var x1 = (left ? cr.right : cr.left) - wr.left;
      var y1 = cr.top + Math.min(16, cr.height / 2) - wr.top;
      var x2 = (left ? tr.left - 5 : tr.right + 5) - wr.left;
      var y2 = tr.top + tr.height / 2 - wr.top;
      var bend = Math.max(18, Math.abs(x2 - x1) * 0.4) * (left ? 1 : -1);
      var p = document.createElementNS(NS, 'path');
      p.setAttribute('d', 'M ' + x1 + ' ' + y1 + ' C ' + (x1 + bend) + ' ' + y1 + ', ' +
        (x2 - bend) + ' ' + y2 + ', ' + x2 + ' ' + y2);
      p.id = 'path-' + c.id;
      if (c.classList.contains('warn')) p.classList.add('warn');
      svg.appendChild(p);
    });
  }

  function layoutAll() {
    document.querySelectorAll('.annotated').forEach(function (w) {
      var d = w.closest('details');
      if (!d || d.open) layout(w);
    });
  }

  document.querySelectorAll('.card').forEach(wire);
  layoutAll();
  window.addEventListener('load', layoutAll);
  var t;
  window.addEventListener('resize', function () { clearTimeout(t); t = setTimeout(layoutAll, 120); });
})();
"""


def esc(s):
    return html.escape(s, quote=True)


def file_label(f):
    status = f["status"]
    name = esc(f["path"]) if status != "deleted" else esc(f["old_path"])
    if status == "renamed" and f["old_path"] != f["path"]:
        name = f"{esc(f['old_path'])} &rarr; {esc(f['path'])}"
    return name, status


def render_hunk_html(f, hunk, fi, hi):
    did = f"d{fi}-{hi}"
    name, status = file_label(f)
    parts = [f'<div class="diff" id="{did}">']
    parts.append(f'<div class="filehead" id="{did}-head">{name}<span class="status">({esc(status)})</span></div>')
    parts.append(f'<div class="hunkhead">{esc(hunk["header"])}</div>')
    if not hunk.get("pseudo"):
        rows = []
        for ri, (tag, o, n, text) in enumerate(hunk["lines"]):
            o = "" if o is None else o
            n = "" if n is None else n
            rows.append(f'<tr id="r{fi}-{hi}-{ri}" class="{tag}"><td class="no">{o}</td>'
                        f'<td class="no">{n}</td><td class="code">{esc(text)}</td></tr>')
        parts.append(f'<div class="scroll"><table>{"".join(rows)}</table></div>')
    parts.append("</div>")
    return "".join(parts)


def resolve_row(hunk, item, key, warnings):
    """Return row index inside hunk for an annotation item, or None for pseudo-hunks."""
    if hunk.get("pseudo"):
        return None
    lines = hunk["lines"]
    if "new" in item:
        for i, (tag, o, n, _) in enumerate(lines):
            if n == item["new"] and tag in ("add", "ctx"):
                return i
        warnings.append(f'{key}: no new-file line {item["new"]} in this hunk; anchored to first change')
    elif "old" in item:
        for i, (tag, o, n, _) in enumerate(lines):
            if o == item["old"] and tag in ("del", "ctx"):
                return i
        warnings.append(f'{key}: no old-file line {item["old"]} in this hunk; anchored to first change')
    for i, (tag, o, n, _) in enumerate(lines):
        if tag in ("add", "del"):
            return i
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--annotations", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--pr-url", default=None)
    ap.add_argument("--allow-unannotated", action="store_true")
    args = ap.parse_args()

    with open(args.annotations) as fh:
        ann = json.load(fh)

    diff_text = run_git(args.repo, ["diff", "--no-color", f"{args.base}...{args.target}"])
    files = parse_diff(diff_text)

    all_keys = []
    hunk_by_key = {}
    for fi, f in enumerate(files):
        for hi, h in enumerate(f["hunks"]):
            key = f'{f["path"]}#{hi}'
            all_keys.append(key)
            hunk_by_key[key] = (fi, hi, f, h)

    hunk_ann = ann.get("hunks", {})
    unknown = [k for k in hunk_ann if k not in hunk_by_key]

    def annotations_of(entry):
        if "annotations" in entry:
            return entry["annotations"]
        if "note" in entry:
            return [{"note": entry["note"]}]
        return []

    missing = [k for k in all_keys
               if k not in hunk_ann or not annotations_of(hunk_ann[k])]

    sections = list(ann.get("sections", []))
    # Collapsed sections (e.g. tests) always sit at the bottom, in the order given.
    sections = [x for x in sections if not x.get("collapsed")] + [x for x in sections if x.get("collapsed")]
    if missing:
        sections.append({"id": "__unannotated__", "title": "Not yet annotated",
                         "explanation": "<p>These changes have not been explained yet.</p>",
                         "_warn": True})

    by_section = {s["id"]: [] for s in sections}
    for key in all_keys:  # diff order within each section
        entry = hunk_ann.get(key)
        if key in missing:
            if "__unannotated__" in by_section:
                by_section["__unannotated__"].append((key, [{"note": "MISSING ANNOTATION"}]))
        elif entry and entry.get("section") in by_section:
            by_section[entry["section"]].append((key, annotations_of(entry)))

    line_warnings = []
    card_seq = 0
    nav_items, body_sections = [], []
    for s in sections:
        sid, stitle = s["id"], s["title"]
        warn = bool(s.get("_warn"))
        cls = "change warn-section" if warn else "change"
        nav_items.append(f'<li><a href="#{esc(sid)}">{esc(stitle)}</a></li>')
        diff_blocks, cards = [], {"left": [], "right": []}
        auto_side = 0
        for key, items in by_section.get(sid, []):
            fi, hi, f, h = hunk_by_key[key]
            diff_blocks.append(render_hunk_html(f, h, fi, hi))
            for item in items:
                side = item.get("side")
                if side not in ("left", "right"):
                    side = "right" if auto_side % 2 == 0 else "left"
                    auto_side += 1
                ri = resolve_row(h, item, key, line_warnings)
                target = f"d{fi}-{hi}-head" if ri is None else f"r{fi}-{hi}-{ri}"
                span = max(1, int(item.get("count", 1)))
                loc = esc(key.rsplit("#", 1)[0])
                card_seq += 1
                card_cls = "card warn" if warn else "card"
                # Notes are authored by the skill and may contain simple inline HTML.
                cards[side].append(
                    f'<div class="{card_cls}" id="card-{card_seq}" data-target="{target}" '
                    f'data-span="{span}" data-side="{side}" data-diff="d{fi}-{hi}">'
                    f'<span class="loc">{loc}</span>{item.get("note", "")}</div>')
        n_in = len(by_section.get(sid, []))
        if s.get("collapsed"):
            hint = f'{n_in} hunk{"s" if n_in != 1 else ""} &middot; click to expand'
            opener = (f'<details class="{cls}" id="{esc(sid)}"><summary><h2>{esc(stitle)}'
                      f'<span class="hint">{hint}</span></h2></summary>')
            closer = '</div></details>'
        else:
            opener = f'<section class="{cls}" id="{esc(sid)}"><h2>{esc(stitle)}</h2>'
            closer = '</div></section>'
        chunks = [opener,
                  f'<div class="explanation">{s.get("explanation", "")}</div>',
                  '<div class="annotated">',
                  f'<div class="rail rail-left">{"".join(cards["left"])}</div>',
                  f'<div class="diffcol">{"".join(diff_blocks)}</div>',
                  f'<div class="rail rail-right">{"".join(cards["right"])}</div>',
                  '<svg class="connectors" xmlns="http://www.w3.org/2000/svg"></svg>',
                  closer]
        body_sections.append("".join(chunks))

    n_files, n_hunks = len(files), len(all_keys)
    covered = n_hunks - len(missing)
    title = ann.get("title", f"Annotated diff: {args.base}...{args.target}")
    pr_link = f' &middot; <a href="{esc(args.pr_url)}">{esc(args.pr_url)}</a>' if args.pr_url else ""
    subtitle = f'<div class="meta">{esc(ann.get("subtitle", ""))}</div>' if ann.get("subtitle") else ""
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title><style>{CSS}</style></head><body>
<div class="layout">
<nav><strong>Changes</strong><ol>{"".join(nav_items)}</ol></nav>
<main>
<header><h1>{esc(title)}</h1>{subtitle}
<div class="meta">{esc(args.base)} &rarr; {esc(args.target)}{pr_link}</div></header>
<div class="intro">{ann.get("intro", "")}</div>
{"".join(body_sections)}
<div class="coverage">Coverage: {covered}/{n_hunks} hunks annotated across {n_files} files.</div>
</main></div>
<script>{JS}</script>
</body></html>"""

    with open(args.out, "w") as fh:
        fh.write(page)

    if unknown:
        print("WARNING: annotations reference nonexistent hunk keys:", file=sys.stderr)
        for k in unknown:
            print(f"  {k}", file=sys.stderr)
    for w in line_warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if missing:
        print(f"MISSING annotations for {len(missing)} hunk(s):", file=sys.stderr)
        for k in missing:
            print(f"  {k}", file=sys.stderr)
        if not args.allow_unannotated:
            sys.exit(1)
    print(f"Wrote {args.out}: {covered}/{n_hunks} hunks annotated, {n_files} files.")


if __name__ == "__main__":
    main()
