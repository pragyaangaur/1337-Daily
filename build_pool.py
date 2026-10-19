"""Builds the bot's solution pool: one checked Python 3 solution per problem.

Reads the archived dataset line by line (it is 100 MB) and writes
pool.jsonl with {slug, number, title, difficulty, code}.
Only chunks that passed the local tests (py3_check.jsonl) are used, premium
problems are dropped, and so are files that define their own TreeNode or
ListNode (kamyu104's stubs would shadow LeetCode's real classes).

Run once: python3 -I build_pool.py
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE.parent / "archive" / "2026-10-16-attempts-1-2" / "data" / "build"
OUT = HERE / "pool.jsonl"
STUB = re.compile(r"^class (TreeNode|ListNode)\b", re.M)


def main():
    passed = {}
    with open(BUILD / "py3_check.jsonl") as f:
        for line in f:
            r = json.loads(line)
            if r["status"] == "pass":
                passed.setdefault(r["slug"], []).append(r["chunk"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    kept = 0
    with open(BUILD / "problems.jsonl") as f, open(OUT, "w") as out:
        for line in f:
            r = json.loads(line)
            slug = r["slug"]
            sols = r.get("solutions_py3") or []
            if str(r.get("premium")) == "True" or slug not in passed:
                continue
            code = None
            for i in sorted(passed[slug]):
                if i < len(sols) and sols[i] and not STUB.search(sols[i]):
                    code = sols[i]
                    break
            if not code or "class Solution" not in code and "class " not in code:
                continue
            out.write(json.dumps({
                "slug": slug, "number": r["number"], "title": r["title"],
                "difficulty": r["difficulty"], "code": code}) + "\n")
            kept += 1
    print(f"pool: {kept} problems -> {OUT}")


if __name__ == "__main__":
    main()
