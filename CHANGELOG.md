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

## 0.19.6

* `IMAGE-TOO-SMALL-001` and `IMAGE-NOT-FOUND-001` now have a **Remove the
  placeholder** button, so an image not being carried over can be dropped and
  the warning resolved. It takes the wrapping paragraph with it when the
  placeholder was all of it, and leaves the sentence intact when it was inline.
* That is the only action allowed to remove text, and it does not get an
  exemption from the copy guard: it checks that what disappeared was the app's
  own placeholder wording and refuses if anything of yours went with it. A test
  asserts no other action has the flag.
* Fixed the placeholder running into the following word. Old markup often had
  an image hard against the text it floated beside, which produced
  `…jpeg]</strong>When Martin joined`. A single space is inserted, and not
  doubled where one already exists.

## 0.19.5

* The image placeholder no longer carries `class="image-placeholder"`. The app
  was generating a class of its own invention — cruft on the new site, which
  handoff 4.2 forbids — and then reporting it back as an unrecognised class. The
  bold text is conspicuous enough on its own.
* Image problems now appear in the **Changes** tab, not only in the Images
  table. `IMAGE-TOO-SMALL-001` and `IMAGE-NOT-FOUND-001` are Warnings;
  `IMAGE-UNUSED-001`, for a file in the folder no `<img>` refers to, is a
  Suggestion. The table was the only place they showed, and the Changes tab is
  where the work happens.

## 0.19.4

Three problems reported while processing a real post's images.

* **The post URL is now required.** It names every output file, so leaving it
  blank produced `blog_post_01.webp` and no way to tell one post's images from
  another's.
* **Images can be processed again.** The step used to substitute placeholders
  into the source and hand that back, so a second run found no `<img>` tags and
  reported nothing processed. The substitution was also redundant: the
  `image_placeholder` rule has replaced every `<img>` on every analysis since
  0.16.0. Removed, so the source is left alone and re-running always works.
* **An image far below 1200px is flagged.** A 250px-wide file is usually a
  WordPress thumbnail rather than the original; enlarging it would only make it
  soft. It is still converted at its own size and reported as *too small*, in
  the table and in the sidecar, with a note to find the full-size file or drop
  the image. Not deleted: whether to keep it is an editorial decision.

Consequence of the second fix: the placeholder in the post names the **original**
file, since the rule runs on every analysis and knows nothing about a particular
processing run. The Images table and the sidecar carry the mapping to the
processed name, and the panel says so.

## 0.19.3

* Fixed the quote block failing validation in WordPress. `core/quote` holds
  paragraph *blocks*, not loose text, so

      <blockquote class="wp-block-quote">If it walks like a duck.</blockquote>

  gave "Block contains unexpected or invalid content". The text now goes in a
  `<p>`, and each paragraph inside a quote gets its own `wp:paragraph`
  delimiters, which is what Gutenberg itself saves. A `<cite>` stays with the
  block.
* `convert_to_blockquote` wraps the text in a `<p>` too, so the plain HTML
  output is valid for the same reason.
* Blocks can now nest, so the delimiter checks use a stack rather than comparing
  two flat lists — the old check would have called a correctly nested quote
  unbalanced.

## 0.19.2

* The link checker found broken links and offered no way to fix them. Every row
  that is not **ok** now carries the URL in an editable box with an **Update
  link** button, and a **Remove the link, keep the text** button for a target
  that has simply gone. Unlinking keeps the wording exactly: deleting the words
  is a copy change and handoff 2 reserves that for you.
* Fixing a link stays on the Links tab, and the panel says to check again
  afterwards, since the results are from before the fix.
* **One definition of visible text**, in `app/text.py`, shared by both copy
  guards. There were two, and they behaved differently: the engine's was
  corrected in 0.14.1 to stop treating inline element boundaries as whitespace,
  the per-action one was not. That is why unlinking an anchor sitting before a
  full stop was refused — "See notes ." and "See notes." looked like different
  copy. Pinned by a test comparing the two.

## 0.19.1

* Fixed forms throwing you onto a different tab. Every form on the results page
  posts back to it, and the page always re-rendered on **Clean HTML** — so
  pressing *Check links* did the work and then dumped you somewhere else, and the
  same happened to Apply, Undo, Process images and Draft Yoast fields. Each form
  now says which tab it came from and the page returns to it. Only clicking a tab
  changes tab.
* `SEO-HEADING-ORDER-001` now has a button. It promotes the whole run of
  headings at that level, not one: the post that raised this had four `<h4>`s
  under an `<h2>`, and fixing one would have left three skipping two levels. The
  run stops at the next shallower heading, so a later section is untouched. The
  message says it may have been a styling choice, since it may well have been.
* `SEO-FAKE-HEADING-ALL-001` converts every all-bold paragraph to a heading in
  one press, alongside the individual suggestions. One post had four.

## 0.19.0

Built from running 22 real posts through the app. The frequency mattered: a
pattern in one post is a curiosity, one in seventeen is a rule.

The posts themselves are **not** in the repository — they are Dyalog content, not
part of the app. `tests/test_corpus.py` runs whatever is in `tests/fixtures/` and
skips when it is empty, so you can copy real posts in to check a change and they
will never be committed. Only `hashing-it-out.html` is kept, because handoff 15
names it as a required regression fixture.

**Old-site links — 17 of 22 posts, 40 links.**

* `URL-HOST-ALL-001` offers one action to repoint every link on a host. Only the
  host changes; path, query and fragment are preserved exactly. The per-URL
  suggestions remain for anything needing individual attention.
* The **Links** tab can now check *where old-site links would point*, rather than
  where they point now. Anything broken there is a file not yet uploaded to the
  dev site — repointing a link to a URL that does not exist would turn a working
  link into a dead one. The host mapping is configuration, so the eventual switch
  back to `dyalog.com` is a config edit.

**Smaller things found across the set.**

* `class=" language-apl"` with a leading space appeared in 6 posts, 180 times.
  The parser always normalised it correctly, but silently: one post had 58 such
  elements and produced almost no findings. Now reported.
* `[embedyt]…[/embedyt]` video shortcodes become a real link, which then gets the
  external-link policy. Gutenberg does not interpret the shortcode.
* A paragraph containing only `&nbsp;` is removed; in Gutenberg it becomes an
  empty block. A paragraph holding only an image is not "empty".
* `width=` and `height=` on tables and cells are removed: sizing belongs to the
  stylesheet, in the same family as `align=` (handoff 4.1).
* `INDENTED-DIV-001` suggests turning a margin-indented `<div>` into a
  `<blockquote>`. Two posts used one as a pull-quote, and they were the only two
  things in the whole corpus landing in a Custom HTML block. Applying it clears
  the last fallbacks.
* `VIDEO-ID-001` warns when a YouTube id is not 11 valid characters. One post's
  source had `?v=https:aIqDxwlcoVU`, which the migration faithfully carried into
  a dead URL. Handoff 6.3 forbids repairing it, so it is reported.
* `NESTED-CODE-001` warns about a `<code>` inside a `<code>`, which one post's
  malformed source produced.

## 0.18.0

Both found by running a post about AI coding agents through the app.

* **Code that is evidently not APL is no longer labelled as APL.** Handoff 3.2
  makes unclassified `<code>` APL, which was right for the old release pages;
  newer posts mix in shell, CLI flags and other languages, and labelling those
  `language-apl` makes the site's highlighter render bash as APL. Detection is
  evidence-based — a shell prompt, a shebang, a long `--flag`, Python or
  JavaScript syntax, HTML, a foreign filename — and an APL glyph anywhere
  settles it the other way. Without such evidence, code is still APL.
  `APL-NOT-APL-001` reports it with a suggested language you can edit; set
  `apl_markup.flag_non_apl_code: false` for the old behaviour.
* Unlabelled non-APL code is now a Suggestion (`OUTPUT-CODE-CLASS-002`) rather
  than an Error. Unlabelled *APL* is still an Error: that invariant is the one
  that matters and it is tested from both sides.
* Classic `[caption ...]` shortcodes are removed, keeping the caption wording.
  Gutenberg does not interpret them, so they rendered as literal text. They are
  stripped while preparing the source, before the copy guard takes its baseline:
  the guard would otherwise see `attachment_9685` and `aligncenter` as words
  being deleted, which is what happened when this was first written as a rule.

## 0.17.0

* An API key can live in a `.env` file beside `pyproject.toml` rather than having
  to be set in the environment before every run. `.env` is gitignored, and
  `.env.example` shows the format.
* A **Yoast** tab drafts a focus keyphrase, a meta description and an SEO title
  from the post's own words. Nothing is written into the HTML — these are fields
  to paste into Yoast — and every draft is marked unreviewed.
* Drafts are checked against the post rather than trusted: a keyphrase the post
  never uses is flagged, because Yoast will score it green while the page ranks
  for nothing. A meta description outside 120-155 characters and an SEO title
  over 60 are flagged too.

## 0.16.0

Found by pasting a real post's output into WordPress.

* **Images never reach the new markup.** Every `<img>` becomes a placeholder
  naming the file it stood for. The block serialiser had been emitting
  `wp:image` blocks whose `src` still pointed at `www.dyalog.com`, which would
  publish a hotlink to the site being migrated away from. This overrides handoff
  section 11, "normal images must survive" — that rule was written when the app
  destroyed images silently, and nothing is destroyed here: the filename is in
  the placeholder and the original alt text is in the finding.
* A thumbnail that links somewhere keeps its link.
  `<a href="report.pdf"><img></a>` is a link to the report, and swallowing the
  anchor with the image lost the PDF entirely. Found by an existing test.
* The SEO missing-alt check runs before images are replaced, so it still fires.
* `PARAGRAPH-LINES-001` flags a single `<p>` holding several paragraphs' worth of
  text, with one action to split at every line break. One real post arrived as
  the whole article inside a single `<p>`, its paragraph breaks surviving only as
  newlines.
* The action copy check normalises whitespace, so a newline and a space compare
  equal. Splitting at a newline was being refused as a copy change.

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
