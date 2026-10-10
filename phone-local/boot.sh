#!/data/data/com.termux/files/usr/bin/sh
# Termux:Boot runs this when the phone starts (server.py installs a copy of
# it into ~/.termux/boot/ on every start, so it is always current).
sleep 5
sh "$HOME/storage/shared/RehearsalRoom/autostart.sh"
