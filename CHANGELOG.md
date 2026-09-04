# Changelog

Versions before 1.0 use: **minor** (0.x.0) for a new capability or a change in
behaviour, **patch** (0.x.y) for a fix with no new capability.

**1.0.0 is reserved** for the point at which the deterministic cleaner is trusted
against real content *and* the WordPress round trip has been verified end to end
in a live install. Handoff §30 is explicit that this comes before new features,
and the block-markup output has still not been confirmed in WordPress.

Up to and including 0.10.2 the version number existed only in the name of the
packaged zip: `pyproject.toml` and the running app both still said `0.5.0`, and a
test asserted that literal, so bumping it would have failed the suite. From
0.11.0 the version lives in `app/version.py` alone and is shown in the interface.

---

## 0.15.0

Image preparation. Point the app at a folder of a post's images and it pairs each
`<img>` with a file, processes the files, and replaces each tag with a visible
placeholder to be filled in by hand.

* Resized to 1200px wide, never enlarged, converted to WebP, renamed
  `blog_<post-slug>_NN.webp` in document order.
* Compression is chosen per image: near-lossless for screenshots, quality-82 for
  photographs. Lossy WebP rings around monospaced glyphs, and most images in
  these posts are APL session output. The choice is reported per image.
* EXIF is stripped, so camera and location data from a photograph does not reach
  a public site.
* Matching is by filename, so an absolute `src` on the old site still finds a
  local file. An `<img>` with no matching file is reported, never guessed at, and
  so is a file in the folder that no `<img>` references.
* Alt text and titles go to a text file beside the images. Existing alt text is
  carried through and marked `KEPT`; a model draft is marked `UNREVIEWED`; with
  no API key the entry is `TODO` and blank. A filename is never turned into a
  description — "screenshot-3.png" says nothing about what the screenshot shows,
  and a plausible guess is worse than an obvious gap because it survives review.
* AI drafting is opt-in and needs your own `ANTHROPIC_API_KEY`. It has only been
  tested against a stubbed API.
* Originals are read only; an existing output file is never replaced unless asked.
* New dependency: Pillow.

## 0.14.1

* Syntax-highlighter spans (`<span class="token …">` from Prism, `hljs-*` from
  highlight.js) are unwrapped, keeping their text. They are generated at render
  time by whatever highlighter the old site used, so they are cruft in the same
  family as `code-line`, and the new site highlights code itself.
* Fixed the copy guard's idea of visible text. It extracted with a separator at
  every element boundary, so `<span>x</span>y` read as "x y" when a browser
  renders "xy". Any change that added or removed an inline wrapper mid-word
  looked like a copy change, and the guard rolled back the entire cleanup rule.
  Only block boundaries separate words now.
* HTML comments are no longer treated as visible text, and are no longer wrapped
  in a paragraph by the block serialiser. Re-importing block markup was leaking
  `wp:paragraph` into the document as copy.

## 0.14.0

* `URL-HOST-001` flags any link still on `dyalog.com` or `www.dyalog.com` and
  offers to repoint it at `dyalogprod.gos.dyalog.com`, with the target in an
  editable box. It is a suggestion, not an automatic rewrite: only the paths
  named in `url_rewrites.rewrites` are established migrations, and handoff 6.3
  forbids guessing whether any other path exists on the new host. The mapping is
  configuration, so reversing it at go-live is a config change.
* A **Links** tab checks whether the links in the document resolve. It makes real
  network requests, so it runs only when asked and never as part of the analysis
  — the rules stay deterministic and offline. A 403 or 429 is reported as
  *inconclusive* rather than broken, since many sites answer that way to scripts.
  Private and reserved addresses are never requested, including after a redirect.

## 0.13.1

* Blank lines separate paragraphs in classic WordPress content. Older Dyalog
  posts have no `<p>` tags at all, and the run-grouping added in 0.6.1 treated
  the blank lines between paragraphs as continuation, merging a whole post into
  one enormous paragraph block.

## 0.13.0

* Findings are grouped into one accordion per rule. A real post produced 457
  findings across 9 rules; the flat list buried the shape of the work. Open
  warnings and errors start expanded, completed clean-up starts collapsed, and
  filtering hides groups with nothing left to show.
* The **Fixed** counter expands into a list of every applied change, each with
  its own Undo, so any fix can be removed rather than only the most recent.
  Removing an earlier fix keeps the later ones where they still apply.

## 0.12.0

* A duplicate id is now reported on *every* occurrence, not only the later ones,
  so either side of the collision can be renamed. Each finding shows what it
  collides with, and each suggests a slug from its own element's text.
* Renaming the first occurrence is marked as the riskier choice, since that is
  the one existing anchor links reach.
* Copying or downloading with warnings still open asks for confirmation first,
  and the export toolbars show how many remain. Errors still block export
  outright; warnings only ask.

## 0.11.0

* Status colours are solid fills only; the tints are gone. Text on each fill is
  inverted to whichever of raisin `#232222` or white gives more contrast —
  raisin on green (7.45:1) and yellow (11.37:1), white on red (5.22:1).
* The version is shown in the page header and footer, returned by `/health`, and
  sent in the fetcher's user agent.
* Single source of truth for the version in `app/version.py`; `pyproject.toml`
  reads it dynamically.

## 0.10.2

* Fixed a 500 on every **Split here** click. The action parameters were written
  into a form attribute with Jinja's `tojson`, which returns markup that
  autoescaping skips and which does not escape double quotes, so the attribute
  terminated early and the posted JSON was malformed.
* Added `tests/test_browser_forms.py`, which parses the rendered page and submits
  its forms as a browser would. Every prior test hand-built the POST body, so the
  form could be broken in any way and the suite stayed green.

## 0.10.1

* Action previews show the resulting elements as separate readable blocks and
  highlight exactly which markup would be inserted.

## 0.10.0

* Separated the counters. **Safe** is measured once against the source and no
  longer collapses to zero after a fix; **Suggestions**/**Warnings** track what
  is still open; **Fixed** counts applied changes and can be undone.
* Undo, by replaying the remaining fixes from the original rather than reversing
  them.
* A **What do these mean?** key for the severities.

## 0.9.1

* `SEO-DUPLICATE-ID-001` offers an editable rename with a suggested unique id.
  Only occurrences after the first are offered, so existing anchors still work.
* Applied the supplied status palette.

## 0.9.0

* Findings can carry an action the user may choose to apply: remove a class,
  demote a heading, promote a bold paragraph, split a long paragraph. Nothing is
  automatic, and every action refuses to run if it would change a word.

## 0.8.1

* Full HTML documents are reduced to their `<body>` content. An exported page
  kept its `<html>`/`<head>` wrapper, which made the block serialiser wrap the
  entire post in a single Custom HTML block.
* Added the real post as an end-to-end fixture.

## 0.8.0

* Report-only SEO and structure checks: `<h1>` in the body, duplicate ids,
  skipped heading levels, bold paragraphs used as headings, missing alt text,
  vague link text.

## 0.7.0

* One rule set instead of two byte-identical profiles, and no profile chooser in
  the interface (handoff §19).
* Removed the JSON report tab.

## 0.6.1

* Code blocks put the language on the `<pre>` as the block's `className`. A class
  on the inner `<code>` is dropped when Gutenberg validates the block, which made
  every code block in a real post report invalid content.
* Loose inline content at the top level joins the surrounding paragraph instead
  of becoming its own Custom HTML block and tearing a sentence into three.

## 0.6.0

* Block-markup output for pasting into the WordPress Code editor, after testing
  showed the paste sanitiser strips `language-apl` and `ex-link` while the block
  parser does not.

## 0.5.2 — withdrawn

Removed `language-apl` from inline code. Reverted at the user's request in the
same session; no build was kept. Recorded because the reversal is why the rule
is pinned by tests on both sides.

## 0.5.1

Five violations found by auditing v0.5.0 against the handoff rather than against
its own tests:

* Unknown classes were destroyed by an allowlist (§4.3); now kept and reported.
* Existing anchor classes were deleted when adding `ex-link` (§5.1).
* A large screenshot whose filename contained "pdf" was destroyed as a legacy
  resource icon (§11); declared dimensions now win over filename guesswork.
* Raw-APL detection wrapped ordinary prose characters such as `×` and `→` (§3.5);
  these are now reported rather than marked up.
* Inline icon removal left a doubled space.

Six existing tests had to change because they encoded the wrong behaviour.

## 0.5.0

Starting point, as handed over.
