#!/data/data/com.termux/files/usr/bin/sh
# Rehearsal Room: the home-screen icon runs this (via Termux:Widget).
# Starts the server if it is not running, waits for it, opens the app.
#
#   open.sh          always open the app in the browser
#   open.sh --cold   only open it if the server had to be started
#                    (used from ~/.bashrc, so opening Termux by hand for
#                    other reasons does not keep throwing the browser up)
DIR="$HOME/storage/shared/RehearsalRoom"
URL="http://127.0.0.1:8899/"
probe() { python -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1', 8899)) == 0 else 1)" 2>/dev/null; }

was_up=0; probe && was_up=1
sh "$DIR/autostart.sh"

i=0
while [ $i -lt 60 ] && ! probe; do sleep 0.5; i=$((i+1)); done

if [ "$1" = "--cold" ] && [ "$was_up" = 1 ]; then exit 0; fi
if ! probe; then echo "  The server did not start. Run: bash $DIR/start.sh"; exit 1; fi
echo "  Opening the app..."
am start -a android.intent.action.VIEW -d "$URL" -p com.microsoft.emmx >/dev/null 2>&1 \
  || am start -a android.intent.action.VIEW -d "$URL" >/dev/null 2>&1
