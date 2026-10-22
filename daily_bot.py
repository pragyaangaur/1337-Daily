"""Daily LeetCode bot: submits 6 checked Python 3 solutions a day on its own.

launchd runs this every 30 minutes. Most runs exit at once. A run only does work
when today's quota is not met yet and today's random start time has passed, so a
sleeping laptop just means the next wake-up tries again, and once 6 are Accepted
the rest of the day is a no-op.

  python3 daily_bot.py --login     one-time: log in to the bot's own browser profile
  python3 daily_bot.py --dry-run   open one problem, fill the editor, do not submit
  python3 daily_bot.py             the real run (what launchd calls)
  python3 daily_bot.py --count 1   submit just 1 now (test)
  python3 daily_bot.py --force     ignore the start-time and quota checks
"""
import argparse
import datetime as dt
import fcntl
import json
import logging
import logging.handlers
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
POOL = HERE / "pool.jsonl"
STATE = DATA / "state.json"
PROFILE = DATA / "profile"
LOCK = DATA / "lock"

PER_DAY = 6               # Accepted submissions wanted per day
MAX_ATTEMPTS_PER_DAY = 10  # hard cap, so a broken page cannot loop
MAX_MISSES_IN_A_ROW = 3    # stop the run if this many in a row are not Accepted
GAP_SECONDS = 20          # pause between submissions
GAP_JITTER = 5
START_WINDOW = (9, 20)    # today's start time is random inside these local hours

LANGS = r"^(C\+\+|Java|Python3?|C|C#|JavaScript|TypeScript|PHP|Swift|Kotlin|Dart|Go|Ruby|Scala|Rust|Racket|Erlang|Elixir)$"

DATA.mkdir(parents=True, exist_ok=True)
log = logging.getLogger("bot")
log.setLevel(logging.INFO)
_h = logging.handlers.RotatingFileHandler(DATA / "bot.log", maxBytes=500_000, backupCount=3)
_h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
log.addHandler(_h)
log.addHandler(logging.StreamHandler(sys.stdout))


def notify(msg):
    log.info("NOTIFY %s", msg)
    script = f'display notification {json.dumps(msg)} with title "LeetCode bot"'
    subprocess.run(["osascript", "-e", script], check=False)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"days": {}, "submitted": [], "skipped": []}


def save_state(st):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(STATE)


def today_entry(st):
    key = dt.date.today().isoformat()
    day = st["days"].setdefault(key, {"ac": [], "attempts": 0, "notified": False})
    if "start_at" not in day:
        lo, hi = START_WINDOW
        minutes = random.randint(lo * 60, hi * 60)
        day["start_at"] = f"{minutes // 60:02d}:{minutes % 60:02d}"
    return day


def launch(p, headless=False):
    # Real Chrome with its own profile folder: clearing the everyday Chrome's
    # cookies does not touch this one, and Google/GitHub sign-in accepts it.
    return p.chromium.launch_persistent_context(
        str(PROFILE), channel="chrome", headless=headless,
        viewport={"width": 1400, "height": 900},
        ignore_default_args=["--enable-automation"],
        args=["--disable-blink-features=AutomationControlled"])


def api_problems(page):
    """Return (logged_in_user, set of solved slugs) from LeetCode's own API."""
    if "leetcode.com" not in page.url:
        page.goto("https://leetcode.com/problemset/", wait_until="domcontentloaded")
    for attempt in (1, 2):
        try:
            # A redirect (a Cloudflare check or a sign-in page) can destroy the
            # page while the fetch runs, so wait for it to settle and try once more.
            page.wait_for_load_state("load", timeout=30000)
            data = page.evaluate(
                "fetch('/api/problems/all/', {credentials: 'include'}).then(r => r.json())")
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)
    user = data.get("user_name") or ""
    solved = {x["stat"]["question__title_slug"]
              for x in data.get("stat_status_pairs", []) if x.get("status") == "ac"}
    return user, solved


def ensure_python(page):
    btn = page.get_by_role("button", name=re.compile(LANGS)).first
    cur = btn.inner_text().strip()
    if cur == "Python3":
        return
    btn.click(timeout=5000)
    page.get_by_text("Python3", exact=True).first.click(timeout=5000)
    time.sleep(0.8)


def fill_editor(page, code):
    ok = page.evaluate(
        """code => {
            const m = window.monaco;
            if (!m) return false;
            const eds = m.editor.getEditors ? m.editor.getEditors() : [];
            const model = eds.length ? eds[0].getModel() : m.editor.getModels()[0];
            if (!model) return false;
            model.setValue(code);
            return model.getValue().length > 0;
        }""", code)
    if not ok:  # fallback: select all and type without touching the clipboard
        page.locator(".monaco-editor:visible").first.click(force=True, timeout=3000)
        page.keyboard.press("Meta+A")
        page.keyboard.press("Backspace")
        page.keyboard.insert_text(code)
    time.sleep(0.5)
    got = page.evaluate(
        "(() => { const m = window.monaco; if (!m) return ''; "
        "const e = m.editor.getEditors ? m.editor.getEditors() : []; "
        "return (e.length ? e[0].getModel() : m.editor.getModels()[0]).getValue(); })()")
    return bool(got) and got.replace("\r", "").strip() == code.replace("\r", "").strip()


def open_problem(page, slug):
    page.goto(f"https://leetcode.com/problems/{slug}/", wait_until="domcontentloaded")
    try:
        page.wait_for_selector(".monaco-editor", timeout=20000)
    except Exception:
        return False
    time.sleep(1.5)
    ensure_python(page)
    return True


def submit(page):
    try:
        page.locator('[data-e2e-locator="console-submit-button"]').click(force=True, timeout=5000)
    except Exception:
        page.get_by_role("button", name="Submit").click(force=True, timeout=5000)
    sel = '[data-e2e-locator="submission-result"]'
    page.wait_for_selector(sel, timeout=90000)
    deadline = time.time() + 90
    while time.time() < deadline:
        res = page.locator(sel).inner_text().strip()
        if res and not re.search(r"pending|judging|running", res, re.I):
            return res
        time.sleep(2)
    return "TIMEOUT"


def pick(pool, solved, st, n):
    skip = solved | set(st["submitted"]) | set(st["skipped"])
    left = [r for r in pool if r["slug"] not in skip]
    random.shuffle(left)
    return left[:n]


def run(args):
    with open(LOCK, "w") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.info("another run is active, exiting")
            return 0

        st = load_state()
        day = today_entry(st)
        save_state(st)
        manual = args.force or args.dry_run or args.count
        if st.get("logged_out") and not manual:
            return 0  # no browser until --login is run again
        if not manual:
            if len(day["ac"]) >= PER_DAY or day["attempts"] >= MAX_ATTEMPTS_PER_DAY:
                return 0
            if dt.datetime.now().strftime("%H:%M") < day["start_at"]:
                return 0

        pool = [json.loads(l) for l in open(POOL)]
        with sync_playwright() as p:
            ctx = launch(p)
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                try:
                    user, solved = api_problems(page)
                except Exception as e:
                    log.info("could not read the problem list: %r", e)
                    return 1
                if not user:
                    log.info("not logged in")
                    st["logged_out"] = True
                    save_state(st)
                    page.screenshot(path=str(DATA / "logged-out.png"))
                    notify("Logged out. Run: python3 daily_bot.py --login")
                    return 1
                if st.pop("logged_out", None):
                    save_state(st)
                log.info("logged in as %s, %d solved, %d AC today", user, len(solved), len(day["ac"]))

                need = 1 if args.dry_run else (args.count or PER_DAY - len(day["ac"]))
                misses = 0
                for rec in pick(pool, solved, st, need + 20):
                    if need <= 0 or day["attempts"] >= MAX_ATTEMPTS_PER_DAY and not args.dry_run:
                        break
                    slug = rec["slug"]
                    try:
                        if not open_problem(page, slug):
                            log.info("[%s] no editor (premium or page changed), skipped", slug)
                            st["skipped"].append(slug)
                            save_state(st)
                            continue
                        if not fill_editor(page, rec["code"]):
                            log.info("[%s] editor did not take the code, stopping", slug)
                            notify("Could not fill the editor. LeetCode's page may have changed.")
                            return 1
                        if args.dry_run:
                            log.info("[%s] dry run: editor filled, not submitting. Look at the window.", slug)
                            time.sleep(20)
                            return 0
                        res = submit(page)
                    except Exception as e:
                        log.info("[%s] ERR %r", slug, e)
                        try:  # a picture of what the page showed, for debugging
                            page.screenshot(path=str(DATA / "last-error.png"))
                        except Exception:
                            pass
                        misses += 1
                        if misses >= MAX_MISSES_IN_A_ROW:
                            notify("Three failures in a row, stopping for now.")
                            return 1
                        continue
                    day["attempts"] += 1
                    st["submitted"].append(slug)
                    log.info("[%s] %s", slug, res)
                    if "Accepted" in res:
                        day["ac"].append(slug)
                        need -= 1
                        misses = 0
                    else:
                        misses += 1
                    save_state(st)
                    if misses >= MAX_MISSES_IN_A_ROW:
                        notify(f"{misses} non-accepted in a row, stopping for now.")
                        return 1
                    if need > 0:
                        time.sleep(GAP_SECONDS + random.uniform(-GAP_JITTER, GAP_JITTER))
                if len(day["ac"]) >= PER_DAY:
                    notify(f"Done for today: {len(day['ac'])} accepted.")
                return 0
            finally:
                ctx.close()


def login():
    with sync_playwright() as p:
        ctx = launch(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://leetcode.com/accounts/login/", wait_until="domcontentloaded")
        print("Log in to LeetCode in the window that opened. Waiting up to 10 minutes...")
        deadline = time.time() + 600
        while time.time() < deadline:
            time.sleep(5)
            try:
                user, _ = api_problems(page) if "leetcode.com" in page.url else ("", set())
            except Exception:
                continue
            if user:
                st = load_state()
                if st.pop("logged_out", None):
                    save_state(st)
                print(f"Logged in as {user}. Session saved in {PROFILE}.")
                ctx.close()
                return 0
        print("Timed out.")
        ctx.close()
        return 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--count", type=int, help="submit this many now, ignoring start time and quota")
    a = ap.parse_args()
    sys.exit(login() if a.login else run(a))
