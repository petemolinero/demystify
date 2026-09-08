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

/* Feedback: select text, comment on it, copy all comments as a prompt. */
::highlight(cm-mark) { background-color:rgba(255,196,0,.45); }
::highlight(cm-mark-hot) { background-color:rgba(255,140,0,.6); }
.cm-fab { position:absolute; z-index:40; display:none; background:var(--fg); color:var(--bg); border:0;
  border-radius:6px; padding:4px 10px; font:600 12.5px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  cursor:pointer; box-shadow:0 2px 8px rgba(0,0,0,.25); }
.cm-fab.show { display:block; }
.cm-pop { position:absolute; z-index:41; display:none; width:320px; background:var(--bg); color:var(--fg);
  border:1px solid var(--border); border-radius:8px; padding:10px; box-shadow:0 6px 24px rgba(0,0,0,.25); }
.cm-pop.show { display:block; }
.cm-pop blockquote { margin:0 0 8px; padding:4px 10px; border-left:3px solid var(--warn-border);
  color:var(--muted); font-size:12.5px; line-height:1.4; max-height:72px; overflow:hidden; }
.cm-pop textarea, .cm-item textarea { width:100%; min-height:64px; resize:vertical; font-family:inherit; font-size:13px; line-height:1.45;
  border:1px solid var(--border); border-radius:6px; padding:6px 8px; background:var(--bg); color:var(--fg); }
.cm-row { display:flex; gap:8px; justify-content:flex-end; margin-top:8px; align-items:center; }
.cm-row .hint { margin-right:auto; color:var(--muted); font-size:11.5px; }
.cm-b { border:1px solid var(--border); background:var(--file-bg); color:var(--fg); border-radius:6px;
  padding:5px 11px; font:600 12.5px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; cursor:pointer; }
.cm-b.primary { background:var(--note-border); border-color:var(--note-border); color:#fff; }
.cm-b:disabled { opacity:.5; cursor:default; }
.cm-dock { position:fixed; right:20px; bottom:20px; z-index:50; display:flex; flex-direction:column;
  align-items:flex-end; gap:8px; font:13px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
.cm-dock .cm-bar { display:flex; gap:8px; }
.cm-dock .cm-b { padding:9px 14px; font-size:13.5px; box-shadow:0 2px 10px rgba(0,0,0,.2); }
.cm-dock .badge { display:inline-block; min-width:18px; padding:0 5px; margin-left:6px; border-radius:9px;
  background:var(--bg); color:var(--fg); font-size:11.5px; line-height:18px; text-align:center; }
.cm-dock .cm-b.primary .badge { background:rgba(255,255,255,.25); color:#fff; }
.cm-panel { display:none; width:min(420px, calc(100vw - 40px)); max-height:min(60vh, 560px); overflow:auto;
  background:var(--bg); border:1px solid var(--border); border-radius:10px; box-shadow:0 8px 30px rgba(0,0,0,.3);
  padding:10px; }
.cm-panel.show { display:block; }
.cm-panel .empty { color:var(--muted); padding:8px 4px; }
.cm-item { border:1px solid var(--border); border-radius:8px; padding:8px 10px; margin-bottom:8px; }
.cm-item .n { font-weight:700; color:var(--muted); font-size:12px; }
.cm-item .ctx { color:var(--muted); font:11.5px/1.4 ui-monospace,Menlo,monospace; margin-left:6px; }
.cm-item blockquote { margin:4px 0 6px; padding:2px 10px; border-left:3px solid var(--warn-border);
  color:var(--muted); font-size:12.5px; line-height:1.4; cursor:pointer; white-space:pre-wrap; }
.cm-item blockquote:hover { color:var(--fg); }
.cm-item .cm-row { margin-top:6px; }
.cm-item .del, .cm-foot .del { color:var(--muted); background:none; border:0; cursor:pointer; font-size:12px; padding:2px 4px; }
.cm-item .del:hover, .cm-foot .del:hover { color:#c00; }
.cm-panel .cm-foot { display:flex; justify-content:space-between; align-items:center; margin-top:4px;
  color:var(--muted); font-size:12px; }
.cm-toast { position:fixed; right:20px; bottom:80px; z-index:60; background:var(--fg); color:var(--bg);
  padding:8px 14px; border-radius:8px; font-size:13px; opacity:0; transition:opacity .2s; pointer-events:none; }
.cm-toast.show { opacity:1; }
.cm-out { display:none; position:fixed; inset:10vh 15vw; z-index:70; background:var(--bg); color:var(--fg);
  border:1px solid var(--border); border-radius:10px; padding:14px; box-shadow:0 10px 40px rgba(0,0,0,.4);
  flex-direction:column; gap:10px; }
.cm-out.show { display:flex; }
.cm-out textarea { flex:1; width:100%; font:12.5px/1.5 ui-monospace,Menlo,monospace; border:1px solid var(--border);
  border-radius:6px; padding:8px; background:var(--file-bg); color:var(--fg); resize:none; }
"""

JS = r"""
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

/* ---------- Feedback: highlight text, comment, copy prompt ---------- */
(function () {
  var main = document.querySelector('main');
  if (!main) return;
  var meta = document.querySelector('header .meta');
  var storeKey = 'demystify-comments:' + document.title + ':' + (meta ? meta.textContent : '');
  var comments = [];   // {id, quote, ctx, text, range|null}
  var seq = 0;
  var hasHL = typeof Highlight !== 'undefined' && CSS.highlights;
  var hl = hasHL ? new Highlight() : null;
  var hlHot = hasHL ? new Highlight() : null;
  if (hasHL) { CSS.highlights.set('cm-mark', hl); CSS.highlights.set('cm-mark-hot', hlHot); }

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function escapeHtml(t) {
    return String(t).replace(/[&<>"]/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c];
    });
  }
  function elementOf(node) { return node.nodeType === 1 ? node : node.parentNode; }

  // UI pieces
  var fab = el('button', 'cm-fab', 'Comment');
  var pop = el('div', 'cm-pop');
  pop.innerHTML = '<blockquote></blockquote><textarea placeholder="Your comment on the highlighted text…"></textarea>' +
    '<div class="cm-row"><span class="hint">⌘/Ctrl+Enter to save</span>' +
    '<button class="cm-b cancel">Cancel</button><button class="cm-b primary save">Save comment</button></div>';
  var dock = el('div', 'cm-dock');
  var panel = el('div', 'cm-panel');
  var bar = el('div', 'cm-bar');
  var listBtn = el('button', 'cm-b', 'Comments<span class="badge">0</span>');
  var copyBtn = el('button', 'cm-b primary', 'Copy prompt<span class="badge">0</span>');
  bar.appendChild(listBtn); bar.appendChild(copyBtn);
  dock.appendChild(panel); dock.appendChild(bar);
  var toast = el('div', 'cm-toast');
  var out = el('div', 'cm-out');
  out.innerHTML = '<div class="cm-row" style="margin:0"><span class="hint">Clipboard unavailable — select all and copy manually.</span>' +
    '<button class="cm-b close">Close</button></div><textarea readonly></textarea>';
  document.body.appendChild(fab); document.body.appendChild(pop); document.body.appendChild(dock);
  document.body.appendChild(toast); document.body.appendChild(out);
  out.querySelector('.close').addEventListener('click', function () { out.classList.remove('show'); });

  var popQuote = pop.querySelector('blockquote'), popText = pop.querySelector('textarea');
  var pending = null; // {range, quote, ctx}

  function showToast(msg) {
    toast.textContent = msg; toast.classList.add('show');
    clearTimeout(showToast.t); showToast.t = setTimeout(function () { toast.classList.remove('show'); }, 1800);
  }

  function lineNo(tr) {
    if (!tr) return '';
    var nos = tr.querySelectorAll('td.no');
    return (nos[1] && nos[1].textContent.trim()) || (nos[0] && nos[0].textContent.trim()) || '';
  }

  // Where is this selection? File + line for diff rows, otherwise the section title.
  function contextOf(range) {
    var node = elementOf(range.startContainer);
    var diff = node.closest('.diff');
    if (diff) {
      var head = diff.querySelector('.filehead');
      var file = head ? head.textContent.replace(/\s*\([^)]*\)\s*$/, '').trim() : '';
      var a = lineNo(node.closest('tr'));
      var b = lineNo(elementOf(range.endContainer).closest('tr')) || a;
      var lineTxt = !a ? '' : (a === b ? ' line ' + a : ' lines ' + a + '-' + b);
      return file + lineTxt;
    }
    var card = node.closest('.card');
    if (card) {
      var loc = card.querySelector('.loc');
      return 'annotation' + (loc ? ' on ' + loc.textContent.trim() : '');
    }
    var sec = node.closest('.change');
    if (sec) {
      var h = sec.querySelector('h2');
      var hint = h && h.querySelector('.hint');
      var title = h ? (hint ? h.textContent.replace(hint.textContent, '') : h.textContent).trim() : '';
      return 'section "' + title + '"';
    }
    if (node.closest('.intro')) return 'intro';
    if (node.closest('header')) return 'page header';
    return '';
  }

  function currentSelection() {
    var sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
    var range = sel.getRangeAt(0);
    var text = sel.toString().split('\n').map(function (l) { return l.replace(/\s+$/, ''); }).join('\n').trim();
    if (!text) return null;
    var anc = elementOf(range.commonAncestorContainer);
    if (!main.contains(anc)) return null;
    return {range: range, text: text};
  }

  function placeNear(node, rect) {
    var x = Math.min(window.innerWidth - node.offsetWidth - 12, Math.max(8, rect.left + window.scrollX));
    node.style.left = x + 'px';
    node.style.top = (rect.bottom + window.scrollY + 6) + 'px';
  }

  document.addEventListener('mouseup', function (e) {
    if (fab.contains(e.target) || pop.contains(e.target) || dock.contains(e.target) || out.contains(e.target)) return;
    setTimeout(function () {
      var cur = currentSelection();
      if (!cur) { fab.classList.remove('show'); return; }
      fab.classList.add('show');
      placeNear(fab, cur.range.getBoundingClientRect());
    }, 0);
  });
  document.addEventListener('mousedown', function (e) {
    if (fab.contains(e.target) || pop.contains(e.target)) return;
    fab.classList.remove('show');
    closePop();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { closePop(); fab.classList.remove('show'); out.classList.remove('show'); }
  });

  function closePop() { pop.classList.remove('show'); pending = null; }

  fab.addEventListener('mousedown', function (e) { e.preventDefault(); });
  fab.addEventListener('click', function () {
    var cur = currentSelection();
    if (!cur) return;
    pending = {range: cur.range.cloneRange(), quote: cur.text, ctx: contextOf(cur.range)};
    popQuote.textContent = cur.text.length > 220 ? cur.text.slice(0, 220) + '…' : cur.text;
    popText.value = '';
    pop.classList.add('show');
    placeNear(pop, cur.range.getBoundingClientRect());
    fab.classList.remove('show');
    popText.focus();
  });
  pop.querySelector('.cancel').addEventListener('click', closePop);
  pop.querySelector('.save').addEventListener('click', saveComment);
  popText.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); saveComment(); }
  });

  function saveComment() {
    if (!pending) return;
    var text = popText.value.trim();
    if (!text) { popText.focus(); return; }
    comments.push({id: ++seq, quote: pending.quote, ctx: pending.ctx, text: text, range: pending.range});
    if (hasHL) hl.add(pending.range);
    closePop();
    try { window.getSelection().removeAllRanges(); } catch (_) {}
    persist(); render();
    showToast('Comment ' + comments.length + ' saved');
  }

  function removeComment(id) {
    comments = comments.filter(function (c) {
      if (c.id !== id) return true;
      if (hasHL && c.range) { hl.delete(c.range); hlHot.delete(c.range); }
      return false;
    });
    persist(); render();
  }

  function render() {
    var n = comments.length;
    listBtn.querySelector('.badge').textContent = n;
    copyBtn.querySelector('.badge').textContent = n;
    copyBtn.disabled = n === 0;
    panel.innerHTML = '';
    if (!n) {
      panel.appendChild(el('div', 'empty', 'Select any text on the page and click <strong>Comment</strong>. ' +
        'Your comments collect here; <strong>Copy prompt</strong> turns them into one numbered prompt.'));
      return;
    }
    comments.forEach(function (c, i) {
      var item = el('div', 'cm-item');
      item.innerHTML = '<span class="n">' + (i + 1) + '.</span>' +
        (c.ctx ? '<span class="ctx">' + escapeHtml(c.ctx) + '</span>' : '') +
        '<blockquote title="Scroll to this text">' +
        escapeHtml(c.quote.length > 160 ? c.quote.slice(0, 160) + '…' : c.quote) + '</blockquote>' +
        '<textarea></textarea><div class="cm-row"><button class="del">Delete</button></div>';
      var ta = item.querySelector('textarea');
      ta.value = c.text;
      ta.addEventListener('input', function () { c.text = ta.value; persist(); });
      item.querySelector('.del').addEventListener('click', function () { removeComment(c.id); });
      item.querySelector('blockquote').addEventListener('click', function () {
        if (!c.range) return;
        var d = elementOf(c.range.startContainer).closest('details');
        if (d && !d.open) d.open = true;
        var r = c.range.getBoundingClientRect();
        window.scrollTo({top: r.top + window.scrollY - window.innerHeight / 3, behavior: 'smooth'});
      });
      item.addEventListener('mouseenter', function () { if (hasHL && c.range) hlHot.add(c.range); });
      item.addEventListener('mouseleave', function () { if (hasHL && c.range) hlHot.delete(c.range); });
      panel.appendChild(item);
    });
    var foot = el('div', 'cm-foot');
    foot.innerHTML = '<span>' + n + ' comment' + (n === 1 ? '' : 's') + '</span><button class="del">Clear all</button>';
    foot.querySelector('.del').addEventListener('click', function () {
      if (!confirm('Delete all ' + n + ' comments?')) return;
      if (hasHL) { hl.clear(); hlHot.clear(); }
      comments = []; persist(); render();
    });
    panel.appendChild(foot);
  }

  listBtn.addEventListener('click', function () { panel.classList.toggle('show'); });

  function buildPrompt() {
    var lines = ["Work through this feedback one item at a time until I'm satisfied:", ''];
    comments.forEach(function (c, i) {
      lines.push((i + 1) + '.' + (c.ctx ? ' (' + c.ctx + ')' : ''));
      c.quote.split('\n').forEach(function (q) { lines.push('   > ' + q); });
      lines.push('');
      c.text.split('\n').forEach(function (t) { lines.push('   ' + t); });
      lines.push('');
    });
    return lines.join('\n').replace(/\n+$/, '\n');
  }
  window.__demystifyPrompt = buildPrompt; // for debugging / automation

  copyBtn.addEventListener('click', function () {
    if (!comments.length) return;
    var text = buildPrompt();
    function done() { showToast('Prompt copied (' + comments.length + ' items)'); }
    function fallback() {
      var ok = false;
      try {
        var ta = document.createElement('textarea');
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select(); ok = document.execCommand('copy'); document.body.removeChild(ta);
      } catch (_) { ok = false; }
      if (ok) done();
      else { out.querySelector('textarea').value = text; out.classList.add('show'); out.querySelector('textarea').select(); }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, fallback);
    } else fallback();
  });

  // Persist text only (ranges can't be serialized); restored comments keep working but lose their highlight.
  function persist() {
    try {
      localStorage.setItem(storeKey, JSON.stringify(comments.map(function (c) {
        return {quote: c.quote, ctx: c.ctx, text: c.text};
      })));
    } catch (_) {}
  }
  try {
    var saved = JSON.parse(localStorage.getItem(storeKey) || '[]');
    saved.forEach(function (c) { comments.push({id: ++seq, quote: c.quote, ctx: c.ctx, text: c.text, range: null}); });
  } catch (_) {}
  render();
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
