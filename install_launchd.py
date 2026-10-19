"""Installs (or removes) the launchd job that runs the daily bot every 30 minutes.

  python3 install_launchd.py            install and start
  python3 install_launchd.py --remove   stop and delete

caffeinate -i keeps the Mac from idle-sleeping while a run is in progress.
A closed lid still sleeps; the next wake-up then runs the bot, because launchd
fires the interval timer soon after wake and the bot checks whether it is due.
"""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABEL = "com.pragyaan.leetcode-daily"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
DOMAIN = f"gui/{os.getuid()}"


def main():
    if "--remove" in sys.argv:
        subprocess.run(["launchctl", "bootout", f"{DOMAIN}/{LABEL}"], check=False)
        PLIST.unlink(missing_ok=True)
        print("removed")
        return
    log = HERE / "data" / "launchd.log"
    plist = {
        "Label": LABEL,
        "ProgramArguments": ["/usr/bin/caffeinate", "-i", sys.executable,
                             str(HERE / "daily_bot.py")],
        "WorkingDirectory": str(HERE),
        "StartInterval": 1800,
        "RunAtLoad": True,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    with open(PLIST, "wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["launchctl", "bootout", f"{DOMAIN}/{LABEL}"], check=False,
                   stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "bootstrap", DOMAIN, str(PLIST)], check=True)
    print(f"installed {PLIST}")


if __name__ == "__main__":
    main()
