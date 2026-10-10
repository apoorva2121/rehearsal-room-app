# Rehearsal Room

### Turn your study notes into a drill you can actually practise out loud.

You wrote the notes. You read them twice. You still freeze when someone asks the
question in a room.

Rehearsal Room takes a folder of Markdown or Word study guides and turns it into
a **one-question-at-a-time drill app** — with the diagrams and formulas intact,
a place to write your own answer, and a webcam recorder so you can watch
yourself answer and hear what you actually sound like.

**Runs entirely on your machine.** A small Python server, a plain HTML front
end, no account, no cloud, no telemetry. Your notes and recordings never leave
the laptop.

---

## Why rehearse out loud

Re-reading notes produces *recognition* — the comfortable feeling that you know
something because it looks familiar. Being asked a question cold requires
*retrieval*, which is a different and much harder act. The gap between the two
is why preparation collapses under pressure.

This app is built to force retrieval:

- **One question fills the screen.** No skimming the page for the answer.
- **The answer is hidden until you press Space.** You have to commit first.
- **Mark it honestly** — Got it, Shaky, or Save — and the marks persist.
- **Record yourself answering.** Nothing exposes a woolly explanation faster
  than watching yourself give it.

## What you get

- One question at a time with its **diagrams, tables and formulas** preserved
- **Press Space** to reveal the answer, after you have committed to one
- Mark each card **Got it · Shaky · Save**; your marks persist between sessions
- **Search** across every question; **contents view** per guide
- **Write notes per question**, saved as plain Markdown files you own
- **Record yourself** answering on webcam, saved locally as `.webm`
- **Keyboard driven** — arrows or `n`/`p` to move, `1`/`2`/`3` to mark, `/` to
  search, `c` for contents
- **Three editions from one source:** laptop, phone-as-web-app, and a fully
  offline copy that runs on the phone itself under Termux
- Works with **no internet at all**

<!--
SCREENSHOT GOES HERE - the single biggest upgrade this page can get.
A capture of one question card mid-drill, answer hidden, is enough.
    ![A question card](docs/screens/card.png)
-->

## Quickstart

Needs **Python 3** and **[pandoc](https://pandoc.org/installing.html)** (pandoc
converts your guides; everything else is standard library).

```bash
git clone https://github.com/apoorva2121/rehearsal-room.git
cd rehearsal-room
```

**1. Point it at your material.** Either drop your guide folders into a `guides`
directory beside the code, or set an environment variable:

```bash
export REHEARSAL_SOURCE=/path/to/your/guides     # Windows: set REHEARSAL_SOURCE=C:\path\to\guides
```

**2. Describe your guides** in `config.py` — one entry each:

```python
GUIDES = [
    {
        "key":   "ml-stats",                 # url-safe id
        "title": "ML & Statistics",          # shown in the picker
        "blurb": "Machine learning, statistics, experimentation",
        "dir":   "ML-Stats-Interview-Guide", # folder inside SOURCE_ROOT
        "sections": "sections",              # subfolder holding the .md files
        "exclude": [],                       # files to skip
    },
]
```

**3. Build and run:**

```bash
python build.py      # converts your guides into the app's data
python server.py     # opens http://127.0.0.1:8899
```

On Windows you can double-click **`Start Learning App.bat`** instead, or
`launch.pyw` for a windowed launcher with no console.

Re-run `python build.py` any time you edit a guide.

## How your guides should look

```
<your source folder>/
  ML-Stats-Interview-Guide/
    sections/
      01-foundations.md
      02-evaluation.md
      ...
  Deep-Learning-Interview-Guide/
    sections/
      ...
```

Each section file is ordinary Markdown. Questions are picked out by heading, and
images referenced from the Markdown are copied across automatically, so diagrams
and formulas survive into the cards.

## The three editions

| Edition | How to open | Where your data lives |
|---|---|---|
| **Laptop** | `python server.py`, or `Start Learning App.bat` | `notes/`, `recordings/`, `state.json` in this folder |
| **Phone (web)** | Build the phone edition and serve it | In the browser, per device |
| **Phone (offline)** | In Termux: `bash start.sh`, then open `http://127.0.0.1:8899/` | On the phone only |

`phone-local/PHONE-SETUP.md` has the Termux walkthrough, including the
home-screen icon.

## No content is included

This repository is **the app, not a question bank.** `data/` and `figures/` are
generated from your own guides by `build.py` and are deliberately not committed —
the material I drill against is my own and stays private.

So a fresh clone has no questions in it until you point it at yours. If you run
`server.py` first, it will tell you exactly that:

```
No data yet. Run:  python build.py
```

## Your notes and recordings stay yours

`notes/`, `recordings/` and `state.json` are all git-ignored. Recordings run
around **10 MB per minute**, so they are excluded on size as well as on
principle — webcam video of you practising does not belong in a git history.

## Built with

Python 3 standard library (no web framework) · plain HTML, CSS and JavaScript ·
[pandoc](https://pandoc.org/) for document conversion · `MediaRecorder` for
webcam capture.

```
build.py          guides -> app data
server.py         the local server
config.py         which guides to build; SOURCE_ROOT lives here
ai.py             optional answer grading
backup.py         back up notes and recordings
index.html        the app
assets/           css, js, icons
phone-local/      the offline on-phone edition
```

## Licence

[MIT](LICENSE) — fork it, point it at your own material, make it yours.
