# 1337-Daily

A small bot that submits six LeetCode solutions every day on its own. It runs from a macOS launchd job, so it needs no daily start.

## How it works

launchd starts the script every 30 minutes. Most runs exit at once. Each day the script picks a random start time between 09:00 and 20:00. After that time has passed, it submits solutions until six are Accepted, with about 20 seconds between submissions. When the laptop is asleep at the start time, the first wake-up after it does the work. When a run is cut off, the next run continues from where it stopped.

Each run reads your solved list from LeetCode and skips those problems. It also skips problems it already submitted and premium problems. If three submissions in a row fail, it stops and sends a macOS notification.

The solutions come from the Python files in kamyu104's LeetCode-Solutions repository (MIT licence), converted to Python 3 and checked against local tests. The prebuilt pool is `pool.jsonl` and holds about 2,000 problems. It contains code only and no problem statements.

## Setup

You need macOS, Google Chrome and Python 3 with Playwright installed.

```bash
pip install playwright
python3 daily_bot.py --login
python3 daily_bot.py --dry-run
python3 daily_bot.py --count 1
python3 install_launchd.py
```

1. `--login` opens Chrome with a profile folder that belongs to the bot. Log in to LeetCode in that window. The session is saved in `data/profile/`, so clearing cookies in your normal Chrome does not affect the bot.
2. `--dry-run` opens one problem and fills the editor without submitting. Check that the language is Python3 and the code is in the editor.
3. `--count 1` submits one solution now, to test the submit step.
4. `install_launchd.py` installs the schedule. Run it with `--remove` to take the schedule away.

## Files

- `daily_bot.py` is the bot.
- `install_launchd.py` installs and removes the launchd job.
- `pool.jsonl` is the solution pool, one problem per line.
- `build_pool.py` built the pool from a private dataset that is not in this repository. It is kept for reference.
- `data/` holds the browser profile, `state.json` and the logs. It is not committed.

## Limits

- The Mac has to be awake, or wake up, for a run to happen. Days with a closed laptop are skipped.
- LeetCode's session expires after a few weeks. The bot sends a notification when that happens, and you run `--login` again.
- Chrome opens a window during a run, which lasts a few minutes.
- LeetCode's terms ban automated submissions, so the account could be flagged. The bot only touches the practice problem set and never joins a rated contest.
