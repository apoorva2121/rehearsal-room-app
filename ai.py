#!/usr/bin/env python3
"""The online half of the app: transcribe a take, grade it, answer a follow-up.

Everything here needs the internet and an OpenAI key. Nothing else in the app
does, and that separation is deliberate -- if this module cannot work, the
rest of the app must carry on exactly as before. So every function returns
either a result or a Problem, and never raises into the server.

The key is read from, in order:
  1. the OPENAI_API_KEY environment variable
  2. ~/.rehearsal-key          (chmod 600; on the phone this is Termux home,
                                NOT /sdcard, which other apps can read)
It is never logged, never returned to the browser, and never written anywhere.

Standard library only. The phone runs this under Termux, where every pip
install is one more thing that can break before an interview.
"""

import json
import os
import re
import ssl
import urllib.error
import urllib.request
import uuid
from html import unescape
from pathlib import Path

OPENAI_ROOT = "https://api.openai.com/v1"

# Overridable because model names change faster than this file will.
TRANSCRIBE_MODEL = os.environ.get("REHEARSAL_TRANSCRIBE_MODEL", "whisper-1")
CHAT_MODEL = os.environ.get("REHEARSAL_CHAT_MODEL", "gpt-4o")

# OpenAI rejects audio over 25 MB. Checked here so the error is ours, in
# plain words, rather than a 413 from a server the user cannot see.
MAX_AUDIO_BYTES = 25 * 1024 * 1024

TRANSCRIBE_TIMEOUT = 180
CHAT_TIMEOUT = 90

# Spoken ML jargon that transcribers mangle. Given as a hint, not a filter.
VOCABULARY = (
    "ROC AUC, precision, recall, F1, XGBoost, LightGBM, scikit-learn, "
    "overfitting, regularisation, L1, L2, cross-validation, k-fold, SHAP, "
    "p-value, confidence interval, A/B test, CUPED, propensity score, "
    "ARIMA, SARIMA, Prophet, LSTM, transformer, attention, embedding, "
    "RAG, MCP, LLM, fine-tuning, LoRA, quantisation, MLOps, Azure, "
    "Databricks, PySpark, feature store, drift, SMOTE, bagging, boosting"
)


class Problem(Exception):
    """A failure the browser should show the user in one honest line."""

    def __init__(self, message, kind="error"):
        super().__init__(message)
        self.message = message
        self.kind = kind          # offline | no-key | rejected | limit | error

    def as_json(self):
        return {"error": self.message, "kind": self.kind}


# --------------------------------------------------------------- the key

def clean_key(text):
    """A key as a human actually saves it, reduced to the key itself.

    The file is hand-edited, so it arrives in every plausible shape:
    `sk-...`, `OPENAI_API_KEY=sk-...`, `export OPENAI_API_KEY="sk-..."`,
    with a trailing newline, with quotes. Every one of those is plainly
    meant as the key, and OpenAI's answer to the wrong shape -- "rejected"
    -- does not say which part was wrong. So accept them all rather than
    leave a trap that costs an hour to find.
    """
    line = next((l.strip() for l in (text or "").splitlines() if l.strip()), "")
    if line.lower().startswith("export "):
        line = line[len("export "):].strip()
    # NAME=value, but only when NAME looks like an environment variable, so
    # a key that itself contains '=' is never cut in half.
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", line):
        line = line.split("=", 1)[1].strip()
    return line.strip("'\"").strip()


def find_key():
    """The key, or None."""
    env = clean_key(os.environ.get("OPENAI_API_KEY") or "")
    if env:
        return env
    for path in (Path.home() / ".rehearsal-key",):
        try:
            if path.is_file():
                text = clean_key(path.read_text(encoding="utf-8"))
                if text:
                    return text
        except OSError:
            pass
    return None


def key_location():
    """Where a key would go, phrased for whoever has to create it."""
    if os.environ.get("PREFIX", "").startswith("/data/data/com.termux"):
        return "~/.rehearsal-key in Termux (not /sdcard)"
    return str(Path.home() / ".rehearsal-key")


def status():
    """What the browser is allowed to know: whether the feature exists."""
    return {
        "enabled": find_key() is not None,
        "where": key_location(),
        "transcribe_model": TRANSCRIBE_MODEL,
        "chat_model": CHAT_MODEL,
    }


# ------------------------------------------------------------ http plumbing

def _require_key():
    key = find_key()
    if not key:
        raise Problem(
            "No OpenAI key yet. Put one in %s, then restart the app."
            % key_location(), "no-key")
    return key


def _send(request, timeout):
    """One request, with every failure translated into plain English.

    The key lives only in the request headers, so nothing here ever puts it
    in a message, a log line or an exception.
    """
    try:
        context = ssl.create_default_context()
        with urllib.request.urlopen(request, timeout=timeout,
                                    context=context) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = ""
        try:
            payload = json.loads(err.read().decode("utf-8"))
            detail = (payload.get("error") or {}).get("message", "")
        except Exception:
            pass
        if err.code == 401:
            raise Problem("OpenAI rejected the key. Check it was pasted "
                          "whole, with no stray spaces.", "rejected")
        if err.code == 429:
            raise Problem("OpenAI says too many requests, or the account is "
                          "out of credit. Check your usage limit.", "limit")
        if err.code == 404 and "model" in detail.lower():
            raise Problem("The model '%s' is not available on this key. Set "
                          "REHEARSAL_CHAT_MODEL (or "
                          "REHEARSAL_TRANSCRIBE_MODEL) to one that is."
                          % CHAT_MODEL, "error")
        if err.code == 413:
            raise Problem("That audio is too big for OpenAI (25 MB cap).",
                          "error")
        raise Problem("OpenAI returned %d%s" % (err.code,
                      ": " + detail if detail else ""), "error")
    except urllib.error.URLError as err:
        raise Problem("No internet. The recording is saved -- grade it when "
                      "you are back online.", "offline")
    except TimeoutError:
        raise Problem("OpenAI took too long. Try again.", "error")
    except json.JSONDecodeError:
        raise Problem("OpenAI sent something unreadable.", "error")


def _multipart(fields, file_field, filename, file_bytes, content_type):
    """multipart/form-data by hand, because requests is not installed."""
    boundary = "----rehearsal" + uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                % (boundary, name, value)).encode("utf-8")
    out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; "
            "filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
            % (boundary, file_field, filename, content_type)).encode("utf-8")
    out += file_bytes
    out += ("\r\n--%s--\r\n" % boundary).encode("utf-8")
    return bytes(out), "multipart/form-data; boundary=" + boundary


def _chat(messages, max_tokens, as_json=False, temperature=0.2):
    key = _require_key()
    payload = {
        "model": CHAT_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if as_json:
        payload["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(
        OPENAI_ROOT + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json"},
        method="POST")
    body = _send(request, CHAT_TIMEOUT)
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise Problem("OpenAI replied with no answer in it.", "error")


# ---------------------------------------------------- the reference answer

_INDEX = None
_GUIDES = {}
ROOT = Path(__file__).resolve().parent


def _load_index():
    global _INDEX
    if _INDEX is None:
        path = ROOT / "data" / "index.json"
        _INDEX = json.loads(path.read_text(encoding="utf-8"))
    return _INDEX


def _html_to_text(fragment):
    """Readable plain text. Tables matter in these answers, so cells are kept
    as ' | ' rather than being run together into one word."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", fragment or "")
    text = re.sub(r"(?i)</t[dh]>\s*", " | ", text)
    text = re.sub(r"(?i)</(tr|p|div|li|h[1-6]|table)>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def reference_for(question_id):
    """(question, model answer) as plain text, or a Problem if unknown.

    Grading is only honest when it grades against this. Without it we would be
    asking a language model to invent a rubric, which is exactly the
    flattering nonsense this feature exists to avoid.
    """
    index = _load_index()
    record = (index.get("questions") or {}).get(question_id)
    if not record:
        raise Problem("No such question: %s" % question_id, "error")
    guide = record["guide"]
    if guide not in _GUIDES:
        path = ROOT / "data" / ("%s.json" % guide)
        if not path.is_file():
            raise Problem("Guide data missing for %s. Run build.py." % guide,
                          "error")
        _GUIDES[guide] = json.loads(path.read_text(encoding="utf-8"))
    entry = _GUIDES[guide].get(question_id) or {}
    answer = _html_to_text(entry.get("answer_html", ""))
    if not answer:
        raise Problem("That question has no written answer to grade against.",
                      "error")
    return record.get("question_text") or record.get("question_html", ""), answer


# ------------------------------------------------------------- transcribe

def transcribe(audio_path):
    """Spoken answer -> text. Cached by the caller, so never sent twice."""
    key = _require_key()
    path = Path(audio_path)
    if not path.is_file():
        raise Problem("No audio was saved with that take.", "error")
    data = path.read_bytes()
    if not data:
        raise Problem("The audio file is empty.", "error")
    if len(data) > MAX_AUDIO_BYTES:
        raise Problem("That audio is %.0f MB; OpenAI accepts 25 MB. Record a "
                      "shorter take." % (len(data) / 1048576.0), "error")

    body, content_type = _multipart(
        {"model": TRANSCRIBE_MODEL, "prompt": VOCABULARY,
         "response_format": "json"},
        "file", path.name, data,
        "audio/wav" if path.suffix == ".wav" else "audio/webm")
    request = urllib.request.Request(
        OPENAI_ROOT + "/audio/transcriptions", data=body,
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": content_type},
        method="POST")
    text = (_send(request, TRANSCRIBE_TIMEOUT).get("text") or "").strip()
    if not text:
        raise Problem("Nothing was heard in that recording. Check the "
                      "microphone was not muted.", "error")
    return text


# ------------------------------------------------------------------ grade

GRADE_SYSTEM = (
    "You are a senior interviewer for a data science role, grading a spoken "
    "answer from a candidate with 10 years of experience. You are grading for "
    "Senior/Lead, Principal and DS Manager tracks, so a vague answer that "
    "merely sounds senior is a fail.\n\n"
    "You are given the question, the WRITTEN REFERENCE ANSWER, and a "
    "transcript of what the candidate actually said out loud.\n\n"
    "Rules you must not break:\n"
    "1. Judge only against the reference answer. Every item in 'missed' MUST "
    "be a point present in the reference answer and absent from the "
    "transcript. Never invent a requirement the reference does not make.\n"
    "2. Be blunt. Say 'wrong', never 'good instinct, but'. A soft grade costs "
    "this person an offer. Do not open with praise. Do not encourage.\n"
    "3. The transcript comes from speech-to-text, so it has no punctuation "
    "and mangles jargon ('rock AUC' is 'ROC AUC'). Grade the meaning, never "
    "the wording, and never criticise transcription artefacts.\n"
    "4. If the transcript is empty, inaudible, or clearly not an answer to "
    "this question, set verdict to 'NO ANSWER' and leave the lists empty.\n"
    "5. 'wrong' is only for statements that are actually incorrect, not for "
    "things left out. If nothing was wrong, return an empty list.\n"
    "6. Hedging, rambling and burying the point are delivery failures. Say so "
    "in one sentence, and quote back roughly what they did.\n\n"
    "Reply with JSON only, in exactly this shape:\n"
    '{\n'
    '  "verdict": "WOULD PASS" | "BORDERLINE" | "WOULD NOT PASS" | "NO ANSWER",\n'
    '  "verdict_note": "one sentence, why",\n'
    '  "missed": ["point from the reference they never said"],\n'
    '  "wrong": [{"said": "roughly what they claimed", "why": "why it is wrong"}],\n'
    '  "scores": {"correctness": 3, "depth": 3, "articulation": 3},\n'
    '  "delivery": "one sentence on how it was delivered"\n'
    '}\n'
    "Scores are integers 1-5. At most 5 items in 'missed' - the 5 that would "
    "cost them the most."
)


def grade(question_id, transcript):
    question, reference = reference_for(question_id)
    transcript = (transcript or "").strip()
    if not transcript:
        raise Problem("Nothing to grade - transcribe the take first.", "error")
    user = ("QUESTION\n%s\n\nREFERENCE ANSWER\n%s\n\nWHAT THEY SAID OUT LOUD "
            "(speech-to-text)\n%s" % (question, reference, transcript))
    raw = _chat([{"role": "system", "content": GRADE_SYSTEM},
                 {"role": "user", "content": user}],
                max_tokens=900, as_json=True)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        raise Problem("The grade came back malformed. Try again.", "error")

    # Shaped here so the browser can render it without defensive checks.
    scores = result.get("scores") or {}
    return {
        "verdict": result.get("verdict") or "BORDERLINE",
        "verdict_note": result.get("verdict_note") or "",
        "missed": [m for m in (result.get("missed") or []) if m][:5],
        "wrong": [w for w in (result.get("wrong") or [])
                  if isinstance(w, dict) and w.get("said")][:5],
        "scores": {k: scores.get(k) for k in
                   ("correctness", "depth", "articulation")},
        "delivery": result.get("delivery") or "",
        "model": CHAT_MODEL,
    }


# ----------------------------------------------------- the concept explainer

EXPLAIN_SYSTEM = (
    "Someone with ten years in data science is revising. They have a question "
    "and its written answer in front of them, and there is one thing in it "
    "they do not follow. They name that thing; you explain it.\n\n"
    "They are experienced, so this is restoring a concept, not teaching it "
    "from scratch -- but they asked because something was unclear, so say it "
    "in the plainest words you can.\n\n"
    "Reply with JSON only, exactly these three keys:\n"
    '{\n'
    '  "what": "what it is, ONE short sentence, everyday words",\n'
    '  "why": "why it works that way, or why it matters, ONE short sentence '
    '-- no formulas unless the thing they asked about IS a formula",\n'
    '  "here": "where it shows up in the answer they are reading, ONE short '
    'sentence"\n'
    '}\n\n'
    "If the thing they asked about is not covered by their study material, "
    "make \"here\" exactly \"not in your material - this is general "
    "knowledge\". Explain it anyway -- they still need to understand it -- "
    "but be honest that it came from outside their guide.\n\n"
    "Each value is ONE sentence. Speak to them as \"you\". Define any jargon "
    "in the same breath as you use it. No bullet points, no headings, no "
    "bold, no preamble, no 'great question'. If you genuinely do not know, "
    "say so in \"what\" rather than guessing."
)


def explain(question_id, user_question, turns=None):
    """Explain one thing the reader does not follow, in three short lines.

    Grounded in the question and its written answer, which is what keeps it
    about the material in front of them rather than a general lecture.
    """
    question, reference = reference_for(question_id)
    user_question = (user_question or "").strip()
    if not user_question:
        raise Problem("Ask about something first.", "error")

    context = ("THE QUESTION THEY ARE READING\n%s\n\nTHE WRITTEN ANSWER THEY "
               "ARE READING\n%s" % (question, reference))

    messages = [{"role": "system", "content": EXPLAIN_SYSTEM},
                {"role": "user", "content": context}]
    # Only the last few turns, so "and why does that matter?" works without
    # paying for a long history on every later question.
    for turn in (turns or [])[-3:]:
        if turn.get("q"):
            messages.append({"role": "user", "content": turn["q"]})
        if turn.get("a"):
            messages.append({"role": "assistant", "content": turn["a"]})
    messages.append({"role": "user",
                     "content": "I do not follow this: " + user_question})

    raw = _chat(messages, max_tokens=250, temperature=0.3, as_json=True)
    # Three fields joined here rather than three lines asked for in the
    # prompt. Asked for lines, the model returns one run-on paragraph with
    # the arrow buried in it; asked for fields, the shape is guaranteed.
    try:
        parts = json.loads(raw)
    except json.JSONDecodeError:
        lines = [l.strip() for l in (raw or "").splitlines() if l.strip()]
        return {"text": "\n".join(lines[:3]), "model": CHAT_MODEL}

    def one_line(value):
        return " ".join(str(value or "").split())

    answer, why = one_line(parts.get("what")), one_line(parts.get("why"))
    tie = one_line(parts.get("here"))
    if tie and not tie.startswith("->"):
        tie = "-> " + tie
    return {"text": "\n".join(l for l in (answer, why, tie) if l),
            "model": CHAT_MODEL}


# ------------------------------------------------------------------- check

def main():
    """`python ai.py --check` -- does the key work, without the browser.

    Prints facts about the key, never the key.
    """
    import sys
    state = status()
    print("key found      : %s" % ("yes" if state["enabled"] else "no"))
    print("looked in      : OPENAI_API_KEY, then %s" % state["where"])
    print("transcribe     : %s" % state["transcribe_model"])
    print("chat           : %s" % state["chat_model"])
    if not state["enabled"]:
        return 1
    key = find_key()
    print("key shape      : starts '%s', %d chars" % (key[:3], len(key)))
    if "--check" not in sys.argv:
        return 0
    print("\ncalling OpenAI...")
    try:
        reply = _chat([{"role": "user", "content": "Reply with the word: ready"}],
                      max_tokens=5)
        print("chat           : OK (%r)" % reply.strip())
    except Problem as problem:
        print("chat           : FAILED [%s] %s" % (problem.kind, problem.message))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
