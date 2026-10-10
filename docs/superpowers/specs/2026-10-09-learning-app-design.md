# Interview Q&A Study App — Design

Date: 2026-10-09
Status: approved by user, ready for implementation

## Purpose

Study 1,206 interview questions one at a time instead of scrolling three
large documents. Per question: see the question, reveal the answer (with
its diagrams, tables and maths), write personal notes, and record a
webcam video of answering it aloud.

## Source data (verified 2026-10-09)

Source of truth, read-only: `C:\Users\apoor\Documents\Learning for switching`

| Guide | Directory | Questions | Diagrams |
|---|---|---|---|
| ML & Statistics | `ML-Stats-Interview-Guide` | 329 | 70 |
| Agentic AI | `Agentic-AI-Interview-Guide` | 273 | 0 |
| Forecasting | `Forecasting-Interview-Guide` | 604 | 16 |
| **Total** | | **1206** | **86** |

Verified facts:

- Every question is an h3 beginning `### Q<n>.<n> `.
- All 86 image references resolve to files on disk. Zero missing.
- Figure paths use two conventions: `figures/x.png` (relative to guide
  root) and `../images/x.png` (relative to the sections directory).
  Resolution tries the section file's directory first, then the guide root.
- `00-test-Q1.md` exists in the Agentic and Forecasting guides and
  duplicates a real Q1.1. Excluded by config.
- Some h3 headings are not questions (`### 1. Requirements`, etc.).
  These are subsections *within* a long answer and must stay attached to
  the preceding question, not become records.
- Sections carry metadata as HTML comments: `<!-- part: ... -->` and
  `<!-- questions: N | answered: N -->`. `part` is used for sidebar grouping.
- `C:\Users\apoor\Documents\learning app\*.docx|*.md` is a derived copy of
  one guide's `split/` output. NOT a source. Ignored.

## Content fidelity (hard requirement)

Answers are converted, never rewritten. The pipeline is pandoc only — no
summarising, no paraphrasing, no generated text. Post-processing is limited
to adding CSS class attributes and rewriting image `src` paths.

## Conversion pipeline

Per section file:

    pandoc --section-divs --mathml --wrap=none -f markdown -t html5

`--wrap=none` is mandatory. Pandoc's default 72-column wrapping splits HTML
attributes across lines, which silently hides section ids from any
line-based parser (observed: 2 of 12 questions detected instead of 12).

`--mathml` renders LaTeX at build time, so the app needs no maths library
and no internet. MathML rendering confirmed in Chromium.

Splitting: walk `<section class="level3">` nodes in document order.
An id matching `^q\d` starts a new record; any other level3 section is
appended to the current record's answer.

## Record schema

    { id, guide, part, section, section_title,
      qnum, question_html, question_text,
      answer_html, figures[], words, is_long }

`id` is `<guide-key>-<qnum>`, e.g. `ml-stats-Q1.4`.
`is_long` marks the ~100 capstone/e2e answers so the UI can treat them
as reading material rather than flashcards.

## Output layout

    learning app/
      Start Learning App.bat   launcher
      server.py                local server, stdlib only, binds 127.0.0.1
      build.py                 re-run after adding material
      config.py                guide list
      index.html  assets/app.css  assets/app.js
      data/index.json          light: ids, question text, structure
      data/<guide>.json        heavy: answer HTML, fetched on demand
      figures/<guide>/         copied diagrams
      notes/<id>.md            user notes, one file per question
      recordings/<id>-<ts>.webm  user videos
      state.json               bookmarks, known/unsure marks, last position

## Why a local server

Required by the video feature: `getUserMedia` needs a secure context, and
`localhost` is one. Verified in Chromium on `http://127.0.0.1`:
`isSecureContext` true, `getUserMedia` present, `MediaRecorder` present,
WebM VP9/VP8 and MP4 all supported, MathML renders, IndexedDB and
localStorage available.

Not verified: `file://` behaviour (both test harnesses block the `file:`
scheme) and the camera permission grant itself (needs a human click).

The server also lets notes and recordings be ordinary files on disk, so the
user can read, back up and delete them outside the browser — which browser
storage would prevent.

Python 3.13.9 and pandoc 3.8 are already installed. No npm, no internet.

## Server API

    GET    /                       static files
    GET    /api/state              bookmarks + marks + last position
    PUT    /api/state              save state
    GET    /api/notes/<id>         note text
    PUT    /api/notes/<id>         save note
    POST   /api/recordings/<id>    save webm, returns filename
    GET    /api/recordings         list with byte sizes
    DELETE /api/recordings/<name>  delete one

Ids and filenames are restricted to `[A-Za-z0-9._-]` to prevent path
traversal. The server binds 127.0.0.1 only.

## UI

- Sidebar: three guides, grouped by part, then section, with counts and
  progress. Collapsible.
- Main pane: question, then answer revealed on Space or click. A reading
  mode toggle keeps answers always visible.
- Answers render in three zones, exploiting the consistent source format:
  the `**In one line:**` paragraph as a summary card, the body with large
  type and styled tables, the `> **Likely follow-up:**` blockquote as a
  separate block.
- Large base font with a size control, because big type and wide
  comparison tables compete for width.
- Navigation: Prev/Next buttons, arrow keys, jump-to-id, search over
  question text.
- Per question: notes box (autosaved) and a record/play/delete video panel.
- Recordings screen: every clip with size, total disk used, delete buttons.
  Default 720p; VP9 720p costs roughly 10-12 MB per minute.

## Build verification

The build fails rather than shipping a quietly-wrong app if:

- the record count does not equal `grep -c '^### Q'` over all included
  sources (expected 1206)
- any id is duplicated
- any record has an empty answer
- any `<img src>` does not resolve to a file on disk

After building: open the app and confirm a maths formula, a markdown table
and a diagram all render, and that a spot-checked answer matches its source.

## Explicitly out of scope

Spaced repetition, quiz scoring, accounts, phone sync. The JSON output makes
these addable later without rework.

## Adding material later

Drop a new `.md` into a guide's `sections/`, or add a guide to `config.py`,
then run `python build.py`. No code changes.
