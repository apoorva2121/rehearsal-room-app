#!/data/data/com.termux/files/usr/bin/sh
# Rehearsal Room on this phone - manual start, and one-time hook install.
#
#   bash ~/storage/shared/RehearsalRoom/start.sh
#
# After this has run once you never need it again: the home-screen icon
# (Termux:Widget) and opening Termux both start the server, and so does a
# phone restart (Termux:Boot). server.py re-installs all of these hooks
# every time it starts, so they cannot go stale.
DIR="$HOME/storage/shared/RehearsalRoom"
cd "$DIR" || exit 1

mkdir -p ~/.termux/boot
cp boot.sh ~/.termux/boot/rehearsal-room.sh
chmod +x ~/.termux/boot/rehearsal-room.sh

grep -v "Rehearsal Room" ~/.bashrc > ~/.bashrc.tmp 2>/dev/null; mv ~/.bashrc.tmp ~/.bashrc
printf '%s\n' 'sh "$HOME/storage/shared/RehearsalRoom/open.sh" --cold   # Rehearsal Room: start the server when Termux opens' >> ~/.bashrc

clear
echo
sh "$DIR/open.sh"
echo
echo "  From now on it starts by itself from the home-screen icon,"
echo "  whenever Termux is opened, and after every phone restart."
echo
