"""Mark pending posts of a week as approved. Usage: approve.py 2026-W40 [--page money|studio] [--except id1,id2]"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: approve.py <week> [--except id1,id2]")
    week = sys.argv[1]
    page = sys.argv[sys.argv.index("--page") + 1] if "--page" in sys.argv else None
    skip = set()
    if "--except" in sys.argv:
        skip = set(sys.argv[sys.argv.index("--except") + 1].split(","))
    folder = ROOT / "posts" / week
    if not folder.is_dir():
        sys.exit(f"no such week: {week}")
    for p in sorted(folder.glob("*.json")):
        post = json.loads(p.read_text(encoding="utf-8"))
        if post.get("status") != "pending" or (page and post.get("page", "money") != page):
            continue
        post["status"] = "rejected" if post["id"] in skip else "approved"
        p.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(post["id"], post["status"])


if __name__ == "__main__":
    main()
