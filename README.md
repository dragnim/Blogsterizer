# The Blogsterizer

The Blogsterizer is a small local web app for cleaning Dyalog blog/page HTML and reporting exactly what it changed. It is intentionally a functional editorial utility rather than a CMS or a rewriting tool.

## v0.5.0: full thread audit

This release was re-audited against the concrete editing patterns used to build the app. The regression suite now covers the rules that repeatedly came up during the Dyalog page clean-up work, rather than relying on generic HTML assumptions.

Key corrections in v0.5.0 include:

- broader raw APL recognition, including `↑`, `↓`, `←`, `→`, APL overbar numbers, `]LINK`, `]IN`, `:For`, `:Disposable`, and other Dyalog control words;
- prose punctuation is kept outside code for cases such as `grade up (⍋)`, while expression punctuation remains inside code for expressions such as `(⊃⍋)`;
- bare `<pre>` code blocks are normalised to `<pre><code class="language-apl">…</code></pre>` when they contain only text;
- every unclassified `<code>` element in either Dyalog profile receives `class="language-apl"`, including ASCII-only code such as `words`, `Words`, and `0`;
- plain-text input supports backticks for ASCII-only code that cannot safely be inferred from prose;
- `dir="auto"` is removed as editor cruft without deleting meaningful `dir="rtl"` or `dir="ltr"`;
- copy-changing resource rules are now rolled back if they remove or reorder original words, numbers, or APL tokens;
- copy/download controls are disabled if the final copy guard fails;
- public URL redirects are validated before they are followed, preventing a public URL from redirecting the fetcher to a private/local address;
- automatic URL extraction now prefers `.entry-content` / `.post-content` before a whole `<article>` when no selector is supplied;
- application/package versioning and the launch scripts have been tidied up;
- a final read-only validation pass now re-checks the APL, legacy-class, URL and external-link invariants, so a future regression appears as an Error instead of silently reaching the output.

`AUDIT-v0.5.0-historical.md` is the original v0.5.0 checklist, kept for reference only; see `CHANGELOG.md` for current state.

## What it does

The app accepts:

- pasted HTML;
- pasted plain text; or
- a public webpage URL, optionally narrowed with a CSS selector.

It produces:

- cleaned HTML;
- a sandboxed preview;
- block markup for the WordPress Code editor;
- a unified diff;
- a filterable change/issue report; and
- a copy guard result.

The Results page can filter findings by **All**, **Safe**, **Suggestions**, **Warnings**, and **Errors**.

## Core Dyalog rules

### APL code

The Dyalog profiles enforce these rules:

- `<span class="APLFont">…</span>` → `<code class="language-apl">…</code>`
- `<span class="language-apl">…</span>` → `<code class="language-apl">…</code>`
- unclassified `<code>…</code>` → `<code class="language-apl">…</code>`
- bare text-only `<pre>…</pre>` → `<pre><code class="language-apl">…</code></pre>`
- explicit non-APL code such as `<code class="language-python">…</code>` is preserved
- unmistakable raw APL glyph tokens, system names, user commands and supported control words are wrapped automatically
- characters that are APL primitives but also ordinary maths/typography (`× ÷ ≤ ≥ ≠ ← → ↑ ↓ ⊂ ⊃ ⌈ ⌊ ∊ ∪ ∩ ○ ∘ ¨`) are only
  wrapped inside a larger token (`A←1 2 3`) or when quoted in brackets (`grade up (⍋)`). A lone one in running prose
  ("the grid is 3 × 4") is left alone and reported as a Suggestion

For **plain-text input**, ASCII-only words/numbers cannot be identified as code reliably from prose alone. Put backticks around them, for example:

```text
If a word in `words` isn't found in `Words`, append `0`.
```

They will become `code.language-apl` during analysis.

### Legacy/editor clean-up

The Blogsterizer intentionally produces lean content HTML. It removes:

- `fclear`
- `APLFont`
- `code-line`
- WordPress editor classes (`wp-*`, `has-*`, `is-style-*`, `attachment-*`, `size-*`, `alignleft`/`alignright`/`aligncenter`/`alignnone`)
- syntax-highlighter spans: `<span class="token …">` (Prism) and `hljs-*` (highlight.js) are unwrapped,
  keeping their text, since the new site highlights code itself
- `dir="auto"`
- inline `style`
- legacy `align`
- `data-*`
- HTML comments
- redundant attribute-free `<span>` wrappers
- non-breaking spaces used as layout glue outside code/preformatted content

Required classes are retained:

- `language-apl` (and explicit `language-*` classes) on `<code>`
- `ex-link` on external links

An **unrecognised** class is not destroyed simply because the profile does not know it: it may carry
intentional styling or semantics. It is kept and reported once as a Suggestion (`UNKNOWN-CLASS-001`) so it
can be removed by hand if it turns out to be cruft. Setting `cleanup.class_mode: allowlist` in
`profiles/blog.yaml` will strip everything not explicitly named, if that is ever wanted.

Legacy resource icons are recognised by size and by icon-style filenames (`pdf_24.png`, `youtube-play_24.png`).
An image with a declared width or height above 40px is treated as content and is never removed, even if its
filename mentions PDF or GitHub.

### Reading the numbers

The counters answer two different questions, so they behave differently.

| | Question it answers | Behaviour |
| --- | --- | --- |
| **Safe** | What did the cleaner do to my source? | Measured once, against the original. Does not move as you work. Nothing for you to do. |
| **Suggestions** | What might I want to change? | Goes down as you resolve them. |
| **Warnings** | What needs a decision? | Goes down as you resolve them. |
| **Errors** | What is broken? | Copy and download are disabled while any remain. |
| **Fixed** | What have I changed? | Counts the fixes you applied. Undo puts the last one back. |

The same explanation is in the interface under **What do these mean?**.

Findings are grouped by rule, one accordion each, so seven long paragraphs read as one row rather than
seven. Warnings and errors start expanded; completed clean-up starts collapsed. Filtering by severity
hides the groups that have nothing left in them.

**Fixed** expands into the list of changes you have applied. Each has its own Undo, so you are not
limited to reversing the most recent one.

Nothing is stored on the server. The source and the list of applied fixes travel in the form, and the
state is rebuilt by replaying the fixes from the original each time, so the result is always the
product of a full run of the rule engine rather than a patched findings list.

### Applying a suggestion

Findings that can be fixed structurally carry a button in the **Changes** tab. Nothing is applied
until you press it (handoff 9). Pressing it applies that one change and re-runs the whole engine, so
what you see afterwards is a real analysis, not a patched findings list.

| Finding | Button |
| --- | --- |
| `UNKNOWN-CLASS-001` | Remove that class wherever it appears |
| `SEO-H1-001` | Change the `<h1>` to an `<h2>` |
| `SEO-FAKE-HEADING-001` | Turn the bold paragraph into an `<h3>` |
| `PARAGRAPH-REVIEW-001` | Split the paragraph at the suggested sentence boundary |
| `SEO-DUPLICATE-ID-001` | Change the id, on either side of the collision, with a suggested value you can edit first |
| `URL-HOST-001` | Repoint a link from the old Dyalog host to the current one, with the target editable |

Each button shows **After, if you apply this** in its Details, so you can see the exact result before
committing to it. Where an action produces more than one element — splitting a paragraph, say — the
resulting blocks are listed separately as readable prose, and the markup view highlights exactly what
was inserted, so a single added `</p><p>` does not have to be hunted for in a wall of HTML. For a long
paragraph the message also names the sentence boundary it would split at.

Every warning the app raises has a way to resolve it. Where an action needs a value, the app proposes
one and puts it in an editable box: for a duplicate id it suggests a slug from the element's own text,
and it refuses a value that is malformed or already used elsewhere. Only the *later* occurrences of a
duplicate id are offered for renaming, so existing anchor links still reach the original element.

**Copy** and **Download** ask for confirmation if warnings are still open, and the export toolbars show
how many. It is a question, not a block: an Error stops export outright, a Warning only asks.

Every action is structural. Each one compares the visible text before and after and refuses to apply
if a single word moved, so an action can change `<p>` structure or a heading level but never the
copy. Actions that would need new wording — rewriting "click here", for example — are reported only.

### SEO and structure checks

Report-only (handoff 10): these never change the HTML.

| Rule | Severity | What it catches |
| --- | --- | --- |
| `SEO-H1-001` | Warning | An `<h1>` in the post body. WordPress already uses the post title as the page's `<h1>`. |
| `SEO-DUPLICATE-ID-001` | Warning | The same `id` used twice, so anchor links only ever reach the first. |
| `SEO-IMG-ALT-001` | Warning | An image with no `alt` attribute. `alt=""` is accepted as a decorative image. |
| `SEO-HEADING-ORDER-001` | Suggestion | A skipped heading level, e.g. `<h2>` straight to `<h4>`. |
| `SEO-FAKE-HEADING-001` | Suggestion | A paragraph that is entirely bold, usually a heading in disguise. |
| `SEO-LINK-TEXT-001` | Suggestion | Link text like "click here" that does not describe the target. |

Each can be switched off individually under `rules.seo` in `profiles/blog.yaml`.

### Block markup (pasting into WordPress)

Gutenberg's paste sanitiser strips `class="language-apl"` and `class="ex-link"` when you paste HTML
into a Paragraph block. Its **block parser** does not. The results screen therefore has a **Block
markup** tab that wraps the same cleaned HTML in block delimiters:

```html
<!-- wp:paragraph -->
<p>We'll call these <code class="language-apl">Words</code> and <code class="language-apl">Freqs</code>.</p>
<!-- /wp:paragraph -->
```

Paste that into the WordPress **Code editor** (Ctrl+Shift+Alt+M), not into a paragraph block. You get
real Heading, Paragraph, List and Image blocks with the classes intact, still editable afterwards.

This mode applies no rules and changes no copy; it only adds the boundary comments. Elements with no
obvious core block become a Custom HTML block and are reported as a Suggestion (`BLOCK-MARKUP-001`).
The plain **Clean HTML** output is unchanged and remains the default.

### Links

External HTTP/HTTPS links receive:

```html
class="ex-link" target="_blank" rel="noopener"
```

Current Dyalog-site links are treated as internal and do not receive `ex-link`:

- `dyalogprod.gos.dyalog.com`
- `www.dyalog.com`
- `dyalog.com`

An internal link that already intentionally uses `target="_blank"` keeps it and receives `rel="noopener"` if needed.

### Explicit URL migrations

The bundled profiles contain only the URL changes established during the migration work:

- `https://www.dyalog.com/uploads/files/presentations/…` → `https://dyalogprod.gos.dyalog.com/uploads/files/presentations/…`
- `https://dyalog.tv/.../?v=VIDEO_ID` → `https://www.youtube.com/watch?v=VIDEO_ID`

The app does **not** search for, infer, or invent missing URLs.

### Legacy resource lists

Known old icon/link patterns are converted into simple HTML using normal elements only. Depending on the source this produces layouts such as:

```text
Release title – Release notes (PDF)
Webinar title – Watch video | PowerPoint | PDF – description…
```

Webinar titles are bolded with `<strong>`. Presentation files migrated to `dyalogprod.gos.dyalog.com` remain internal and therefore do not get `ex-link`.

### Paragraphs

Long paragraphs are reported as **Suggestions** for review. They are not split automatically because a logical paragraph break is an editorial judgement and the Blogsterizer does not silently rewrite copy.

## Copy guard

Ordinary clean-up rules must preserve the exact visible token stream. If one changes visible copy, that rule is rolled back.

Rules that deliberately replace legacy resource labels/separators may add presentational labels, but they still may not remove or reorder any original word, number, or APL token. If they do, they are rolled back too.

If the final copy guard fails, or the final validation pass finds a core invariant error, the Results page disables the Copy HTML and Download HTML actions.

## Quick start on Windows

Python 3.11 or later is required.

1. Extract the folder.
2. Double-click `start-blogsterizer.bat`.
3. On first launch it creates a local virtual environment and installs the app.
4. The browser opens at `http://127.0.0.1:8000`.

Subsequent launches reuse the local environment rather than upgrading/reinstalling pip every time.

## Manual start

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Tests

```bash
pytest
```

The regression suite contains direct examples and invariants derived from the editing workflow, including a mixed-corpus test that checks APL markup, old classes, URL migrations, and the external-link policy together.

## API

`POST /api/analyse`

```json
{
  "source_type": "html",
  "content": "<p class=\"fclear\">Use <span class=\"APLFont\">⎕JSON</span>.</p>"
}
```

`source_type` can be `html`, `text`, or `url`. URL input accepts an optional `selector`.

## Rules and extension

Profiles live in `profiles/*.yaml`. URL migrations, internal hosts, old classes and rule ordering are configuration-led.

Rules live in `app/rules/`. To add a new rule:

1. subclass `app.rules.base.Rule`;
2. implement `apply()`;
3. register it in `app/rules/__init__.py` and `app.engine._build_rules()`;
4. enable/configure it in the relevant YAML profile; and
5. add a regression test based on a real example.

That final step is deliberate: a transformation is not considered part of the Blogsterizer's behaviour until there is a test for it.

## Current limits

- Logical paragraph splitting is review-only.
- JavaScript-rendered pages are not rendered by the URL importer.
- The app does not publish back to WordPress yet.
- Free-form editorial/typo checking is not implemented yet; the current reports are deterministic HTML/content-structure checks.
- Arbitrary ASCII-only code in unmarked plain prose cannot be inferred safely; use backticks in plain-text input or `<code>` in HTML input.

## Images are not carried into the markup

Every `<img>` is replaced with a placeholder naming the file it stood for:

```html
<p class="image-placeholder"><strong>Image here: employeespotlight_martin_01.jpeg</strong></p>
```

The old `src` points at the site being migrated away from, so carrying it through would publish a
hotlink to it. The images are processed separately (below) and placed by hand.

Nothing is lost: the filename is in the placeholder, the original alt text is reported for the sidecar
file, and a thumbnail that links somewhere keeps its link with the placeholder as its text. An image
inside a sentence gets an inline placeholder so the paragraph stays valid.

This overrides handoff section 11, "normal images must survive", which was written when the app was
destroying images silently. Set `rules.image_placeholder.replace_images: false` in
`profiles/blog.yaml` to turn it off.

## Preparing images

The **Images** tab takes a folder containing the post's images and the post URL. For each
`<img>` in the HTML it finds the matching file by name, writes a processed version, and replaces the
tag with a placeholder:

```html
<p class="image-placeholder"><strong>Image here: blog_hashing-it-out_01.webp</strong></p>
```

Images are not put back into the markup — that is yours to do, and the placeholder is deliberately
conspicuous so it cannot be missed. An image inside a sentence gets an inline placeholder instead, so
the paragraph stays valid.

Processing: resized to 1200px wide (an image already narrower is left alone, since enlarging cannot
add detail), EXIF stripped, converted to WebP. Compression is chosen per image — near-lossless for
screenshots, quality 82 for photographs — because lossy WebP visibly damages monospaced text and most
of these images are APL session output. Each decision is reported so you can see when it guesses wrong.

Alt text and titles are written to `<slug>-images.txt` beside the processed files, with a status per
image: `KEPT` (the original page's alt text, written by a person), `UNREVIEWED` (drafted by a model),
`TODO` (no description — write one). Drafting is opt-in and needs `ANTHROPIC_API_KEY` in the
environment; without it you get `TODO` entries rather than invented text. **Nothing in that file has
been checked**, which the file says at the top.

Anything unmatched is reported rather than guessed: an `<img>` with no file in the folder, and a file
in the folder no `<img>` uses.

## The API key

Everything in the app works without a key. It is needed only for the optional AI drafting: image alt
text and titles, and the Yoast fields.

Copy `.env.example` to `.env` beside `pyproject.toml`, put the key in it, and restart:

```
ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is gitignored, so the key will not be committed. Setting `ANTHROPIC_API_KEY` in the
environment works too and takes precedence.

## Yoast fields

The **Yoast** tab drafts a focus keyphrase, a meta description and an SEO title from the post's own
words. Nothing is written into the HTML; these are fields you paste into Yoast.

Every draft is checked against the post before you see it. A keyphrase the post never uses is flagged
— Yoast would score it green while the page ranks for nothing — as is a meta description outside the
120-155 characters Yoast wants, or an SEO title over 60. **Drafts are unreviewed:** read them against
the post.

## Checking links

The **Links** tab asks each link in the document whether it still resolves. This is the one part of the
app that touches the network, so it runs only when you press the button and is never part of the
analysis: every rule finding stays reproducible offline.

Results are one of **broken** (a 404, a timeout, a failed request), **inconclusive** (a 403, 405 or 429
— plenty of sites answer that way to anything that is not a browser, so check it by hand before
believing it), **not checked** (relative, in-page, `mailto:`, or an address on a private network), or
**ok**. Requests go out four at a time with a ten-second timeout, `HEAD` first and `GET` only if that
is refused, and a redirect to a private address is abandoned rather than followed.

## Versioning

The version lives in `app/version.py` and nowhere else. It is shown in the page header and footer,
returned by `/health`, and read by `pyproject.toml`. See `CHANGELOG.md` for what changed in each
release.

Below 1.0: minor (`0.x.0`) for a new capability or a behaviour change, patch (`0.x.y`) for a fix.
**1.0.0 is reserved** for the point at which the deterministic cleaner is trusted against real content
and the WordPress round trip has been verified in a live install — handoff §30 puts that before any
further features.
