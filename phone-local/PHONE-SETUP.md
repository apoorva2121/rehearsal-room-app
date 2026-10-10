# Rehearsal Room on your phone

The same app as the laptop, running on the phone itself. Everything is saved
on the phone only - no account, no cloud, no internet, no laptop needed.

## Day to day

Tap the **Rehearsal Room** icon (teal R) on your home screen. That is all.

A black Termux window flashes for a few seconds while the server starts,
then the app opens in Edge by itself. Cold start is about 6-10 seconds; if
the server is already running it is instant. Notes, marks and recordings
save to the phone as you go.

## What runs underneath

A tiny server (the same `server.py` as the laptop) runs inside the Termux
app. Three things start it, so you never have to:

- the **Rehearsal Room icon** (a Termux:Widget shortcut running `open.sh`),
- **opening Termux** by hand (a hook in `~/.bashrc`),
- a **phone restart** (Termux:Boot).

`server.py` re-installs all of these hooks every time it starts, so they
cannot go stale.

Even with the server dead (Termux swiped away or force-stopped) the page,
every question and every figure are cached in Edge, so the old Edge shortcut
or the address `127.0.0.1:8899` still opens. The status line then reads
**"Server is off. Open the Termux app to start it."** Tap the Rehearsal Room
icon instead and it reconnects on its own. Marks and notes made meanwhile are
kept in the browser and written to the RehearsalRoom folder when the server
is back. Recording needs the server, so the record button hides until then.

Manual start, if ever needed, in Termux:

    bash ~/storage/shared/RehearsalRoom/start.sh

## Where your work is

    Internal storage / RehearsalRoom / notes          one .md file per question
    Internal storage / RehearsalRoom / recordings     your videos (.webm)
    Internal storage / RehearsalRoom / state.json     marks and last position

Open them in any file manager. Delete recordings you have outgrown there or
in the app. Phone and laptop are separate copies: a note on one does not
appear on the other.

## Camera

The first time you press Start recording, the browser asks for camera and
microphone - choose "Allow while visiting the site" so it remembers. Takes
are up to 10 minutes, roughly 5 MB a minute.

## Grading yourself on the phone (needs mobile data)

Under the answer is a box that says "Don't follow something above?". Name what
you are stuck on and it explains that concept in three short lines, pointing at
where it appears in the answer you are reading. It appears when you reveal the
answer, not before.

Under a recording is **Grade this take**: it transcribes what you said, marks
it against the written answer in your guide, and lists what you missed.

This is the only part of the phone app that needs the internet. Reading,
marking, notes and recording all still work with Termux closed and no signal,
exactly as before. With no key on the phone, the grading controls are not
drawn at all.

To turn it on, in Termux:

```
printf '%s' 'sk-...' > ~/.rehearsal-key
chmod 600 ~/.rehearsal-key
```

Then stop the server (Ctrl-C in Termux) and tap the icon again.

**Why Termux home and not the RehearsalRoom folder:** everything under
Internal storage can be read by any app you have given storage permission to.
`~/.rehearsal-key` lives inside Termux's own private storage, which they
cannot reach. So the key is the one file that does *not* get copied across
with the others. Set a monthly usage limit on the key as well -- a phone is
the easiest thing in this setup to lose.

Check it worked, in Termux:

```
cd /sdcard/RehearsalRoom && python ai.py --check
```

It prints whether a key was found and whether OpenAI answered, never the key.

## Adding new questions

On the laptop: `python build.py`, then `python phone-local/build_phone.py`.
Copy the laptop's `data` and `figures` folders, `server.py`, `ai.py` and
everything in `phone-local/` over the phone's Internal storage /
RehearsalRoom. Notes, recordings and marks are untouched. Tap the icon once so
the new files get cached.

`ai.py` is what makes grading work; without it the app runs exactly as it did
before, grading quietly absent. Your key is never copied -- it stays in Termux
home (see above).

## One-time setup (done on this phone, 9-10 Oct 2026)

    Termux 0.118.3, Termux:Boot 0.8.1, Termux:Widget 0.15.0
        (all official GitHub builds, installed with adb; the copies that
        landed in the Work profile were removed)
    termux-setup-storage        (tapped Allow)
    pkg install -y python
    Settings -> Apps -> Termux -> Display over other apps: ON
        (needed so the icon can open a Termux window from the home screen)
    bash ~/storage/shared/RehearsalRoom/start.sh   (installs the hooks)
    Termux:Widget app -> CREATE SHORTCUTS, then long-press the Termux:Widget
        icon and drag "Rehearsal Room" onto the home screen
