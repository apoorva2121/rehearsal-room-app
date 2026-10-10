#!/data/data/com.termux/files/usr/bin/sh
# Move an OpenAI key from the shared RehearsalRoom folder into Termux's own
# private storage, and delete the shared copy.
#
# Why this exists: adb cannot write to Termux's home directory, so a key
# pushed from the laptop has to land in /sdcard first -- where any app with
# storage permission could read it. This moves it somewhere they cannot, and
# removes the shared copy immediately, so that window is seconds long.
#
# Run:  sh /sdcard/RehearsalRoom/key.sh

src=/sdcard/RehearsalRoom/.key-import
dst="$HOME/.rehearsal-key"

if [ ! -f "$src" ]; then
  echo "Nothing to import: no .key-import in the RehearsalRoom folder."
  if [ -f "$dst" ]; then
    echo "You already have a key in Termux home ($(wc -c < "$dst" | tr -d ' ') characters)."
  fi
  exit 1
fi

# Strip spaces and newlines: a stray one is the commonest reason a pasted
# key is rejected, and the error from OpenAI does not say so.
tr -d ' \t\r\n' < "$src" > "$dst" || { echo "Could not write $dst"; exit 1; }
chmod 600 "$dst"
rm -f "$src"

size=$(wc -c < "$dst" | tr -d ' ')
if [ "$size" -lt 20 ]; then
  echo "Imported, but it is only $size characters -- that looks wrong."
  exit 1
fi
echo "Key moved into Termux home ($size characters, readable only by you)."
echo "The copy in the shared folder has been deleted."
echo
echo "Check it works:   cd /sdcard/RehearsalRoom && python ai.py --check"
echo "Then stop the server with Ctrl-C and tap the Rehearsal Room icon again."
