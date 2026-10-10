#!/usr/bin/env python3
"""Local server for the study app.

It exists for two reasons:
  1. The browser only allows camera access on a secure context, and
     http://127.0.0.1 is one. A double-clicked file:// page is not reliable.
  2. It lets notes and recordings be ordinary files on disk, so they can be
     read, backed up and deleted outside the browser.

Binds to 127.0.0.1 only, so nothing outside this machine can reach it.

Run:  python server.py            (or double-click "Start Learning App.bat")
"""

import json
import os
import re
import socket
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# The online half. Imported defensively on purpose: if it is missing or
# broken, the app must still serve notes and recordings offline exactly as
# it did before. A revision tool that fails closed is worse than useless.
try:
    import ai
except Exception:  # pragma: no cover - any import failure is the same to us
    ai = None

ROOT = Path(__file__).resolve().parent
NOTES_DIR = ROOT / "notes"
RECORDINGS_DIR = ROOT / "recordings"
STATE_FILE = ROOT / "state.json"

# Anything written to disk must match this. Blocks path traversal outright.
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
MAX_UPLOAD = 500 * 1024 * 1024  # a very long take is still only ~500 MB

DEFAULT_PORT = 8899


def safe(name):
    return bool(SAFE_NAME.match(name)) and ".." not in name


def audio_for(base):
    """The audio sibling of a take, or None.

    Takes are saved as <base>.webm (video, what you watch) plus
    <base>.audio.webm (or .wav on the fallback path) -- a few hundred KB
    that is small enough to transcribe. The video itself is usually far
    over the 25 MB the transcription API accepts.
    """
    for suffix in (".audio.webm", ".audio.wav"):
        candidate = RECORDINGS_DIR / (base + suffix)
        if candidate.is_file():
            return candidate
    return None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    # Quieter log: one line per request, no noise for static assets.
    def log_message(self, fmt, *args):
        # Under pythonw.exe (the silent launcher) there is no stderr at all.
        if sys.stderr is not None and self.path.startswith("/api/"):
            sys.stderr.write("  %s %s\n" % (self.command, self.path))


    # --- helpers ---------------------------------------------------------
    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def fail(self, status, message):
        self.send_json({"error": message}, status)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            return None
        return self.rfile.read(length)

    def read_json_body(self):
        body = self.read_body()
        if not body:
            return {}
        try:
            payload = json.loads(body.decode("utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def ai_ready(self):
        """None when usable, otherwise the reply already sent."""
        if ai is None:
            return self.send_json(
                {"error": "The AI module is not installed next to server.py.",
                 "kind": "error"}, 400)
        return None

    def api_parts(self):
        """['notes', 'ml-stats-Q1.4'] for /api/notes/ml-stats-Q1.4"""
        path = self.path.split("?")[0]
        return [p for p in path[len("/api/"):].split("/") if p]

    # --- GET -------------------------------------------------------------
    def do_GET(self):
        if not self.path.startswith("/api/"):
            return super().do_GET()

        parts = self.api_parts()
        if not parts:
            return self.fail(404, "unknown endpoint")

        if parts[0] == "state":
            if STATE_FILE.is_file():
                return self.send_json(json.loads(
                    STATE_FILE.read_text(encoding="utf-8")))
            return self.send_json({})

        if parts[0] == "notes" and len(parts) == 2:
            if not safe(parts[1]):
                return self.fail(400, "bad id")
            note = NOTES_DIR / (parts[1] + ".md")
            return self.send_text(
                note.read_text(encoding="utf-8") if note.is_file() else "")

        if parts[0] == "ai" and len(parts) == 2 and parts[1] == "status":
            # Whether the feature exists at all. No key material, ever.
            if ai is None:
                return self.send_json({"enabled": False,
                                       "where": "ai.py is missing"})
            return self.send_json(ai.status())

        if parts[0] == "recordings" and len(parts) == 1:
            items = []
            if RECORDINGS_DIR.is_dir():
                for f in sorted(RECORDINGS_DIR.glob("*.webm")):
                    if f.name.endswith(".audio.webm"):
                        continue  # the sibling, not a take of its own
                    stat = f.stat()
                    base = f.name[:-len(".webm")]
                    items.append({"name": f.name, "bytes": stat.st_size,
                                  "modified": int(stat.st_mtime),
                                  "question": f.name.rsplit("--", 1)[0],
                                  "base": base,
                                  "has_audio": audio_for(base) is not None,
                                  "transcript": self.cached_text(base),
                                  "grade": self.cached_grade(base)})
            return self.send_json({"recordings": items})

        return self.fail(404, "unknown endpoint")

    # --- cached work ------------------------------------------------------
    # A transcript and a grade are each paid for once. They sit next to the
    # take as ordinary files, so they survive a restart, can be read
    # without the app, and are never bought twice.
    def cached_text(self, base):
        path = RECORDINGS_DIR / (base + ".txt")
        try:
            return path.read_text(encoding="utf-8") if path.is_file() else None
        except OSError:
            return None

    def cached_grade(self, base):
        path = RECORDINGS_DIR / (base + ".grade.json")
        try:
            return json.loads(path.read_text(encoding="utf-8")) \
                if path.is_file() else None
        except (OSError, json.JSONDecodeError):
            return None

    # --- PUT -------------------------------------------------------------
    def do_PUT(self):
        parts = self.api_parts()
        if not self.path.startswith("/api/") or not parts:
            return self.fail(404, "unknown endpoint")

        body = self.read_body()
        if body is None:
            return self.fail(413, "too large")

        if parts[0] == "state":
            STATE_FILE.write_text(body.decode("utf-8"), encoding="utf-8")
            return self.send_json({"saved": True})

        if parts[0] == "notes" and len(parts) == 2:
            if not safe(parts[1]):
                return self.fail(400, "bad id")
            NOTES_DIR.mkdir(exist_ok=True)
            target = NOTES_DIR / (parts[1] + ".md")
            text = body.decode("utf-8")
            if text.strip():
                target.write_text(text, encoding="utf-8")
            elif target.is_file():
                target.unlink()  # an emptied note is a deleted note
            return self.send_json({"saved": True})

        return self.fail(404, "unknown endpoint")

    # --- POST ------------------------------------------------------------
    def do_POST(self):
        parts = self.api_parts()
        if not self.path.startswith("/api/") or len(parts) != 2:
            return self.fail(404, "unknown endpoint")

        if parts[0] == "ai":
            return self.do_ai(parts[1])

        if parts[0] != "recordings" or not safe(parts[1]):
            return self.fail(400, "bad request")

        body = self.read_body()
        if body is None:
            return self.fail(413, "recording too large")

        RECORDINGS_DIR.mkdir(exist_ok=True)
        stamp = self.headers.get("X-Recorded-At") or "0"
        if not stamp.isdigit():
            stamp = "0"
        # The audio sibling carries the same stamp as its video, which is
        # what pairs them -- so the browser must send the stamp it used.
        kind = (self.headers.get("X-Audio") or "").strip()
        if kind in ("webm", "wav"):
            name = parts[1] + "--" + stamp + ".audio." + kind
        else:
            name = parts[1] + "--" + stamp + ".webm"
        (RECORDINGS_DIR / name).write_bytes(body)
        return self.send_json({"name": name, "bytes": len(body)})

    # --- the online endpoints ---------------------------------------------
    def do_ai(self, action):
        """/api/ai/<action>. Every failure arrives as {error, kind} with
        status 400, so the browser has one path for all of them."""
        already_answered = self.ai_ready()
        if already_answered is not None:
            return already_answered

        payload = self.read_json_body()
        base = (payload.get("base") or "").strip()
        question_id = (payload.get("question") or "").strip()
        if base and not safe(base):
            return self.fail(400, "bad take name")

        try:
            if action == "transcribe":
                return self.send_json(self.do_transcribe(base, payload))
            if action == "grade":
                return self.send_json(self.do_grade(base, payload))
            if action == "explain":
                return self.send_json(ai.explain(
                    question_id, payload.get("ask") or "",
                    payload.get("turns") or []))
        except ai.Problem as problem:
            return self.send_json(problem.as_json(), 400)
        except Exception as err:  # never take the server down over this
            return self.send_json({"error": "Unexpected: %s" % err,
                                   "kind": "error"}, 400)
        return self.fail(404, "unknown ai endpoint")

    def do_transcribe(self, base, payload):
        cached = self.cached_text(base)
        if cached and not payload.get("force"):
            return {"text": cached, "cached": True}
        audio = audio_for(base)
        if audio is None:
            # Last resort: transcribe the video itself. Only works when
            # the take is small enough for the 25 MB cap, which a short
            # answer is. Better than refusing a take already performed.
            video = RECORDINGS_DIR / (base + ".webm")
            if video.is_file() and video.stat().st_size <= 24 * 1024 * 1024:
                audio = video
            else:
                raise ai.Problem(
                    "No audio was saved beside that take, and the video "
                    "is too big to transcribe on its own. Record a new "
                    "take -- the next one will save audio too.", "error")
        text = ai.transcribe(audio)
        (RECORDINGS_DIR / (base + ".txt")).write_text(text, encoding="utf-8")
        return {"text": text, "cached": False}

    def do_grade(self, base, payload):
        cached = self.cached_grade(base)
        if cached and not payload.get("force"):
            return dict(cached, cached=True)
        transcript = payload.get("transcript") or self.cached_text(base) or ""
        # The take name is <question id>--<stamp>, so the question is in it.
        question_id = payload.get("question") or base.rsplit("--", 1)[0]
        result = ai.grade(question_id, transcript)
        (RECORDINGS_DIR / (base + ".grade.json")).write_text(
            json.dumps(result, indent=1), encoding="utf-8")
        return dict(result, cached=False)

    # --- DELETE ----------------------------------------------------------
    def do_DELETE(self):
        parts = self.api_parts()
        if not self.path.startswith("/api/") or len(parts) != 2:
            return self.fail(404, "unknown endpoint")

        if parts[0] != "recordings" or not safe(parts[1]):
            return self.fail(400, "bad name")

        target = RECORDINGS_DIR / parts[1]
        if target.is_file():
            target.unlink()
            # A deleted take takes its audio, transcript and grade with it,
            # or the folder fills with orphans nothing can play.
            if parts[1].endswith(".webm"):
                base = parts[1][:-len(".webm")]
                for suffix in (".audio.webm", ".audio.wav", ".txt",
                               ".grade.json"):
                    sibling = RECORDINGS_DIR / (base + suffix)
                    if sibling.is_file():
                        sibling.unlink()
            return self.send_json({"deleted": parts[1]})
        return self.fail(404, "no such recording")


class QuietServer(ThreadingHTTPServer):
    # A browser that navigates away mid-download closes the socket; that
    # is normal, not an error worth a traceback on screen.
    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError,
                            ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def install_termux_hooks():
    """Phone only. Make sure the server comes back by itself:
         ~/.termux/boot/rehearsal-room.sh   Termux:Boot runs it after a restart
         ~/.bashrc                          opening Termux starts it
    Runs only inside Termux, is a no-op anywhere else, harmless to repeat.
    Whichever way the server was started, the hooks end up installed."""
    if not os.environ.get("PREFIX", "").startswith("/data/data/com.termux"):
        return
    autostart = ROOT / "autostart.sh"
    if not autostart.is_file():
        return
    try:
        home = Path.home()
        boot_dir = home / ".termux" / "boot"
        boot_dir.mkdir(parents=True, exist_ok=True)
        hook = boot_dir / "rehearsal-room.sh"
        text = ("#!/data/data/com.termux/files/usr/bin/sh\n"
                "# Rehearsal Room: installed by server.py. Starts the server after a reboot.\n"
                "sleep 5\n"
                "sh \"%s\"\n" % autostart)
        if not hook.is_file() or hook.read_text(encoding="utf-8") != text:
            hook.write_text(text, encoding="utf-8")
            hook.chmod(0o755)
        # Opening Termux by hand: start the server, and open the app if it
        # was down (open.sh --cold). The line is replaced, not appended, so an
        # older version of it never lingers.
        opener = ROOT / "open.sh"
        line = 'sh "%s" --cold   # Rehearsal Room: start the server when Termux opens\n' % opener
        for rc in (home / ".bashrc", home / ".bash_profile"):
            if rc.name == ".bash_profile" and not rc.is_file():
                continue
            existing = rc.read_text(encoding="utf-8") if rc.is_file() else ""
            kept = [l for l in existing.splitlines(True) if "Rehearsal Room" not in l]
            if kept and not kept[-1].endswith("\n"):
                kept[-1] += "\n"
            wanted = "".join(kept) + line
            if wanted != existing:
                rc.write_text(wanted, encoding="utf-8")

        # The home-screen icon: a Termux:Widget shortcut. Both the classic
        # ~/.shortcuts entry and the dynamic one (long-press the Termux:Widget
        # icon, or pin it) run open.sh in a Termux window.
        if opener.is_file():
            body = opener.read_text(encoding="utf-8")
            for d in (home / ".shortcuts", home / ".termux" / "widget" / "dynamic_shortcuts"):
                d.mkdir(parents=True, exist_ok=True)
                d.chmod(0o700)
                target = d / "Rehearsal Room"
                if not target.is_file() or target.read_text(encoding="utf-8") != body:
                    target.write_text(body, encoding="utf-8")
                target.chmod(0o700)
            icon = ROOT / "icons" / "icon-192.png"
            if icon.is_file():
                icons = home / ".shortcuts" / "icons"
                icons.mkdir(parents=True, exist_ok=True)
                icons.chmod(0o700)
                dest = icons / "Rehearsal Room.png"
                if not dest.is_file() or dest.read_bytes() != icon.read_bytes():
                    dest.write_bytes(icon.read_bytes())
    except OSError:
        pass


def import_pending_key():
    """Phone only. Move a key left in the app folder into Termux's own
    private storage, and delete the shared copy.

    adb cannot write to Termux's home directory, so a key pushed from the
    laptop has to land here on shared storage first -- where any app holding
    storage permission could read it. Importing it on the next start is what
    makes that window minutes rather than permanent.

    It acts only on a file somebody deliberately put there, and deletes it
    either way, so it runs at most once per key. A key already in Termux
    home is left alone unless a new one is waiting.
    """
    if not os.environ.get("PREFIX", "").startswith("/data/data/com.termux"):
        return
    pending = ROOT / ".key-import"
    if not pending.is_file():
        return
    try:
        raw = pending.read_text(encoding="utf-8")
        key = ai.clean_key(raw) if ai is not None else "".join(raw.split())
        target = Path.home() / ".rehearsal-key"
        if len(key) >= 20:
            target.write_text(key, encoding="utf-8")
            target.chmod(0o600)
            print("  Key        -> imported into %s (%d characters);"
                  % (target, len(key)))
            print("                the copy in the app folder is deleted.")
        else:
            print("  Key        -> .key-import held only %d characters, which "
                  "looks wrong; ignored." % len(key))
        pending.unlink()
    except OSError as err:
        print("  Key        -> could not import .key-import (%s)" % err)


def find_port(preferred):
    for port in range(preferred, preferred + 20):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit("No free port found between %d and %d."
                     % (preferred, preferred + 20))


def main():
    if not (ROOT / "data" / "index.json").is_file():
        print("No data yet. Run:  python build.py")
        return 1

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    open_browser = "--no-browser" not in sys.argv   # launch.pyw opens its own window
    port = find_port(int(args[0]) if args else DEFAULT_PORT)
    url = "http://127.0.0.1:%d/" % port

    NOTES_DIR.mkdir(exist_ok=True)
    RECORDINGS_DIR.mkdir(exist_ok=True)
    install_termux_hooks()
    import_pending_key()   # before the status line below reports the key

    server = QuietServer(("127.0.0.1", port), Handler)
    print("\n  Study app running at  " + url)
    print("  Notes      -> " + str(NOTES_DIR))
    print("  Recordings -> " + str(RECORDINGS_DIR))
    if ai is not None:
        state = ai.status()
        print("  Grading    -> " + ("on, via " + state["chat_model"]
              if state["enabled"] else
              "off (no OpenAI key in " + state["where"] + ")"))
    print("\n  Close this window to stop.\n")

    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
