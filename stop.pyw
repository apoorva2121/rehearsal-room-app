"""Stop the Rehearsal Room server (the Start-menu 'Stop' entry runs this).

Finds whatever process is listening on the app's port and ends it. Safe to
run when nothing is running. Your notes and recordings are files on disk,
so stopping loses nothing.
"""

import subprocess

PORT = 8899
CREATE_NO_WINDOW = 0x08000000


def listening_pids():
    out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True,
                         text=True, creationflags=CREATE_NO_WINDOW).stdout
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(":%d" % PORT) and parts[3] == "LISTENING":
            pids.add(parts[4])
    return pids


def main():
    for pid in listening_pids():
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True,
                       creationflags=CREATE_NO_WINDOW)


if __name__ == "__main__":
    main()
