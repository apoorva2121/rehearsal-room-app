"""Rehearsal Room launcher - what the desktop icon runs.

Runs under pythonw.exe, so there is no console window. It starts the
server silently if it is not already running, waits for it to answer, then
opens the app in its own browser window (no address bar, own taskbar entry).

Clicking the icon again while the server is up just opens the window.
"""

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 8899
URL = "http://127.0.0.1:%d/" % PORT

CREATE_NO_WINDOW = 0x08000000
DETACHED = 0x00000008


def server_up():
    with socket.socket() as probe:
        probe.settimeout(0.4)
        return probe.connect_ex(("127.0.0.1", PORT)) == 0


def start_server():
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    subprocess.Popen(
        [str(pythonw), str(HERE / "server.py"), str(PORT), "--no-browser"],
        cwd=str(HERE),
        creationflags=CREATE_NO_WINDOW | DETACHED,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    for _ in range(50):          # up to ~10 s for the first start
        if server_up():
            return True
        time.sleep(0.2)
    return False


def browser_app_mode():
    """A browser that can open a URL as its own window. Chrome first, then Edge."""
    candidates = []
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    for exe in candidates:
        if exe.exists():
            return exe
    return None


def open_app():
    exe = browser_app_mode()
    if exe is None:
        webbrowser.open(URL)      # plain tab, still works
        return
    subprocess.Popen(
        [str(exe), "--app=" + URL, "--window-size=1440,900"],
        creationflags=DETACHED, close_fds=True,
    )


def main():
    if not server_up() and not start_server():
        # Nothing on screen under pythonw, so fall back to the visible launcher.
        subprocess.Popen(["cmd", "/c", "start", "", str(HERE / "Start Learning App.bat")])
        return
    open_app()


if __name__ == "__main__":
    main()
