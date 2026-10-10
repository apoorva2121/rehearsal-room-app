"""Which guides to build into the study app.

To add new material:
  * new section file  -> just drop the .md into an existing guide's
                         sections/ folder, then re-run build.py
  * a whole new guide -> add an entry to GUIDES below, then re-run build.py

Nothing else needs changing.
"""

import os
from pathlib import Path

# Read-only source of truth: the folder holding your guide directories. The
# build never writes here.
#
# Point it at your own material with the REHEARSAL_SOURCE environment variable:
#     Windows:  set REHEARSAL_SOURCE=C:\path\to\guides
#     macOS/Linux:  export REHEARSAL_SOURCE=/path/to/guides
#
# Falling back to a `guides` folder beside this file means a fresh clone works
# with no configuration at all - drop your guides in there and run build.py.
SOURCE_ROOT = Path(
    os.environ.get("REHEARSAL_SOURCE")
    or Path(__file__).resolve().parent / "guides"
)

# Where the app is generated (this folder).
OUT_ROOT = Path(__file__).resolve().parent

GUIDES = [
    {
        "key": "ml-stats",
        "title": "ML & Statistics",
        "blurb": "Machine learning, statistics, experimentation, MLOps",
        "dir": "ML-Stats-Interview-Guide",
        "sections": "sections",
        # Files to skip: scratch/test files that duplicate real questions.
        "exclude": [],
    },
    {
        "key": "agentic-ai",
        "title": "Agentic AI",
        "blurb": "Agents, orchestration, RAG, MCP, tools, guardrails",
        "dir": "Agentic-AI-Interview-Guide",
        "sections": "sections",
        "exclude": ["00-test-Q1.md"],
    },
    {
        "key": "forecasting",
        "title": "Forecasting",
        "blurb": "Time series, classical and ML forecasting, hierarchies",
        "dir": "Forecasting-Interview-Guide",
        "sections": "sections",
        "exclude": ["00-test-Q1.md"],
    },
    {
        "key": "deep-learning",
        "title": "Deep Learning",
        "blurb": "Neural networks, training, transformers, serving and cost",
        "dir": "Deep-Learning-Interview-Guide",
        "sections": "sections",
        "exclude": [],
    },
    {
        "key": "reinforcement-learning",
        "title": "Reinforcement Learning",
        "blurb": "MDPs, value and policy methods, exploration, RLHF",
        "dir": "RL-Interview-Guide",
        "sections": "sections",
        "exclude": [],
    },
    {
        "key": "mmm",
        "title": "Marketing Mix Modeling",
        "blurb": "Adstock, saturation, ROI and budget optimisation, geo tests",
        "dir": "MMM-Interview-Guide",
        "sections": "sections",
        "exclude": [],
    },
]

# Answers longer than this (in words) are treated as reading material
# rather than flashcards, and get a "long answer" marker in the UI.
LONG_ANSWER_WORDS = 600
