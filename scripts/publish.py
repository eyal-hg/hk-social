"""Publish approved posts whose date has arrived, to the Facebook Page and Instagram.

Env: META_TOKEN (long-lived Page access token of the HK page, secret), PAGE_ID, IG_ID,
IMAGE_BASE_URL (public base for out/*.jpg).
A post is published only if status == "approved" and publish_date <= today (Asia/Jerusalem).
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
GRAPH = "https://graph.facebook.com/v21.0"
TOKEN = os.environ["META_TOKEN"]
PAGE_ID = os.environ["PAGE_ID"]
IG_ID = os.environ["IG_ID"]
IMAGE_BASE = os.environ["IMAGE_BASE_URL"].rstrip("/")
DRY = "--dry-run" in sys.argv


def call(method, path, **params):
    data = urllib.parse.urlencode(params).encode()
    url = f"{GRAPH}/{path}"
    if method == "GET":
        req = urllib.request.Request(url + "?" + data.decode())
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} -> {e.code}: {body}") from None


def page_token():
    # עובד גם עם טוקן משתמש (נמשך ממנו טוקן הדף) וגם עם טוקן דף (מוחזר כמו שהוא)
    try:
        return call("GET", PAGE_ID, fields="access_token", access_token=TOKEN).get("access_token") or TOKEN
    except RuntimeError:
        return TOKEN


def caption(post):
    tags = " ".join("#" + t.lstrip("#") for t in post.get("hashtags", []))
    return (post["caption"].strip() + ("\n\n" + tags if tags else "")).strip()


def to_facebook(post, ptoken):
    r = call("POST", f"{PAGE_ID}/photos", url=f"{IMAGE_BASE}/{post['id']}.jpg", message=caption(post), access_token=ptoken)
    return r.get("post_id") or r.get("id")


def to_instagram(post):
    c = call("POST", f"{IG_ID}/media", image_url=f"{IMAGE_BASE}/{post['id']}.jpg", caption=caption(post), access_token=TOKEN)["id"]
    for _ in range(20):
        st = call("GET", c, fields="status_code", access_token=TOKEN).get("status_code")
        if st == "FINISHED":
            break
        if st == "ERROR":
            raise RuntimeError(f"instagram container {c} failed")
        time.sleep(3)
    return call("POST", f"{IG_ID}/media_publish", creation_id=c, access_token=TOKEN)["id"]


def main():
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    due = []
    for p in sorted((ROOT / "posts").rglob("*.json")):
        post = json.loads(p.read_text(encoding="utf-8"))
        if post.get("status") == "approved" and post["publish_date"] <= today:
            due.append((p, post))
    if not due:
        print("nothing due", today)
        return
    ptoken = None if DRY else page_token()
    failed = False
    for p, post in due:
        channels = post.get("channels", ["facebook", "instagram"])
        res = post.setdefault("results", {})
        try:
            if "facebook" in channels and "facebook" not in res:
                res["facebook"] = "dry-run" if DRY else to_facebook(post, ptoken)
            if "instagram" in channels and "instagram" not in res:
                res["instagram"] = "dry-run" if DRY else to_instagram(post)
            post["status"] = "published"
            post["published_at"] = datetime.now(ZoneInfo("Asia/Jerusalem")).isoformat(timespec="minutes")
            print("published", post["id"], res)
        except Exception as e:  # noqa: BLE001
            failed = True
            post["last_error"] = str(e)[:500]
            print("FAILED", post["id"], e, file=sys.stderr)
        if not DRY:
            p.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
