#!/data/data/com.termux/files/usr/bin/sh
# Rehearsal Room: start the server in the background if it is not running.
# Called by start.sh, by the Termux:Boot hook after a restart, and from
# ~/.bashrc every time Termux is opened. Safe to run any number of times.
DIR="$HOME/storage/shared/RehearsalRoom"
if python -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1', 8899)) == 0 else 1)" 2>/dev/null; then
  echo "  Rehearsal Room is running at http://127.0.0.1:8899/"
else
  command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
  if [ -f "$DIR/server.py" ]; then
    ( cd "$DIR" && nohup python server.py 8899 --no-browser >/dev/null 2>&1 & )
    echo "  Rehearsal Room started at http://127.0.0.1:8899/"
  else
    echo "  RehearsalRoom folder not found at $DIR"
  fi
fi
echo "  Tap the Rehearsal Room icon on your home screen. You can leave Termux."
