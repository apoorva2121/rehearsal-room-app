#!/usr/bin/env python3
"""Zip up everything that is yours: notes, recordings, marks.

Questions and figures are not included — those can always be rebuilt from
your guides with build.py. This backs up only the things that cannot.

Run:  python backup.py            (writes into backups/)
      python backup.py D:\\somewhere-else
"""

import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MINE = ["notes", "recordings", "state.json"]


def main():
    target_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    archive = target_dir / ("rehearsal-room-" + stamp + ".zip")

    count = 0
    total = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in MINE:
            source = ROOT / name
            if source.is_file():
                zf.write(source, name)
                count += 1
                total += source.stat().st_size
            elif source.is_dir():
                for path in sorted(source.rglob("*")):
                    if path.is_file():
                        zf.write(path, str(path.relative_to(ROOT)))
                        count += 1
                        total += path.stat().st_size

    if count == 0:
        archive.unlink()
        print("Nothing to back up yet — no notes, recordings or marks.")
        return 0

    print("Backed up " + str(count) + " file(s), "
          + str(round(total / 1048576, 1)) + " MB of originals")
    print("  -> " + str(archive) + "  ("
          + str(round(archive.stat().st_size / 1048576, 1)) + " MB zipped)")
    print("\nTo restore: unzip it back into\n  " + str(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
