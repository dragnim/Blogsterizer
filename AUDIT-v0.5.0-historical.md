# The Blogsterizer v0.5.0 audit — historical

> **This document describes v0.5.0 and is kept for reference only.**
>
> Handoff §28 warns against treating a passing checklist as proof of
> correctness: this one was fully ticked while `code-line` survived, `dir="auto"`
> survived, `ex-link` was missing, bare `<code>` never received `language-apl`,
> and normal images were being destroyed. Auditing v0.5.0 against the handoff
> rather than against this list found five violations on the first pass.
>
> For current behaviour see `README.md`; for what changed and why, `CHANGELOG.md`;
> for the authoritative rules, the handoff document itself.


This checklist records the concrete behaviour the app is expected to have after reviewing the editing work that led to the Blogsterizer.

## Copy preservation

- [x] Ordinary transformations cannot change visible words or punctuation.
- [x] A rule that unexpectedly changes copy is rolled back.
- [x] Resource-layout rules may replace labels/separators, but cannot remove or reorder original words, numbers or APL tokens.
- [x] Final copy guard result is shown prominently.
- [x] Copy/download is disabled if the guard fails.

## APL markup

- [x] `span.APLFont` becomes `code.language-apl`.
- [x] `span.language-apl` becomes `code.language-apl`.
- [x] Bare `<code>` becomes `code.language-apl` in both Dyalog profiles.
- [x] ASCII-only code already inside `<code>` is handled (`words`, `Words`, `0`, `X+0`).
- [x] Explicit non-APL `language-*` classes are not changed to APL.
- [x] Bare text-only `<pre>` blocks are wrapped in `code.language-apl`.
- [x] Raw APL system names and glyph expressions are detected conservatively.
- [x] `↑`, `↓`, `←`, `→`, overbar numbers, and diamond-containing expressions are recognised.
- [x] Raw `]LINK` / `]IN` style user commands are recognised.
- [x] Raw `:For` / `:Disposable` and other supported control words are recognised.
- [x] Prose punctuation stays outside code for `(⍋)` / `(⍒)`.
- [x] Expression punctuation stays inside code for `(⊃⍋)` and similar expressions.
- [x] Plain-text backticks provide an explicit path for ASCII-only inline code.

## Legacy/editor clean-up

- [x] `fclear` removed.
- [x] `code-line` removed from paragraphs and code.
- [x] `APLFont` removed as a legacy class.
- [x] `dir="auto"` removed.
- [x] Meaningful `dir="rtl"` / `dir="ltr"` is not removed by the `dir="auto"` rule.
- [x] Inline style, legacy align, `data-*`, comments and redundant spans follow the active Dyalog cleanup profile.
- [x] The clean-up is idempotent.
- [x] Final-output validation reports an ERROR if known legacy classes/`dir="auto"` somehow survive.

## Links

- [x] Every external HTTP/HTTPS link gets `ex-link`.
- [x] Every external HTTP/HTTPS link opens in a new window.
- [x] Every new-window external link gets `rel="noopener"`.
- [x] Protocol-relative external links are handled.
- [x] Relative/internal links do not get `ex-link`.
- [x] Current Dyalog-site links do not get `ex-link`.
- [x] Existing `ex-link` is removed from links that become internal after URL migration.
- [x] Internal links that already use `_blank` keep it and get `noopener`.
- [x] Final-output validation re-checks the link policy and reports any regression as an ERROR.

## URL migrations

- [x] Old Dyalog presentation asset URLs move to `dyalogprod.gos.dyalog.com`.
- [x] The migrated presentation assets are treated as internal.
- [x] `dyalog.tv` video IDs are preserved exactly when converted to YouTube.
- [x] No rule searches the web or guesses a missing URL.
- [x] Final-output validation flags old presentation/dyalog.tv URLs if a migration somehow fails.

## Resource-link layouts

- [x] Old PDF/PPT/ZIP/YouTube/GitHub resource icons are removed from recognised resource links.
- [x] Icon-only release-note links become readable action links.
- [x] Title-plus-icon links keep the title and add a readable resource action.
- [x] Parenthesised `(PDF)` / `(GitHub)` list layouts are normalised without rewording the title.
- [x] Webinar titles are bolded.
- [x] Webinar resource actions use the established text labels.
- [x] Multiple webinar resources use plain `|` separators, without wrapper spans/classes.
- [x] Descriptions remain after the resource links.

## Paragraph/editorial review

- [x] Long paragraphs are flagged as Suggestions.
- [x] Paragraphs are not split automatically.
- [x] The app does not spell-check or silently fix supplied copy.

## Interface

- [x] Compact utility layout; no marketing hero/tagline treatment.
- [x] Findings can be filtered by All, Safe, Suggestions, Warnings, and Errors.
- [x] Selecting a finding filter opens the Changes tab and updates the visible count.
- [x] Clean HTML, Preview, Changes, Diff and JSON report tabs are available.
- [x] Copy and download actions are provided when the copy guard passes.

## URL importer

- [x] Only HTTP/HTTPS public hosts are allowed.
- [x] Private/local/reserved targets are rejected.
- [x] Redirect destinations are checked before following them.
- [x] Optional CSS selector supported.
- [x] Without a selector, common content containers are preferred before whole-page fallback.

## Regression policy

The suite includes direct examples from the editing workflow plus invariant tests. New real-world failures should be added as regression tests before being fixed, so the same behaviour cannot regress unnoticed.
