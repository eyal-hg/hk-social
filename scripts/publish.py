"""Publish approved posts whose date has arrived, to the Facebook Page and Instagram.

Env: META_TOKEN (long-lived Page access token of the HK page, secret), PAGE_ID, IG_ID,
IMAGE_BASE_URL (public base for out/*.jpg), VIDEO_BASE_URL (public base for video/*.mp4).
A post with "video": "<meta video id>" is published as a Page video + Instagram reel instead of a photo.
A post with "dark": true is created as an unpublished Page post (for promoting as an ad), facebook only.
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
PAGES = {
    "money": {"page": os.environ.get("PAGE_ID", ""), "ig": os.environ.get("IG_ID", "")},
    "studio": {"page": os.environ.get("STUDIO_PAGE_ID", ""), "ig": os.environ.get("STUDIO_IG_ID", "")},
}
IMAGE_BASE = os.environ["IMAGE_BASE_URL"].rstrip("/")
VIDEO_BASE = os.environ.get("VIDEO_BASE_URL", IMAGE_BASE.rsplit("/", 1)[0] + "/video").rstrip("/")
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


def page_token(page_id):
    # עובד גם עם טוקן משתמש (נמשך ממנו טוקן הדף) וגם עם טוקן דף (מוחזר כמו שהוא)
    try:
        return call("GET", page_id, fields="access_token", access_token=TOKEN).get("access_token") or TOKEN
    except RuntimeError:
        return TOKEN


def caption(post):
    tags = " ".join("#" + t.lstrip("#") for t in post.get("hashtags", []))
    return (post["caption"].strip() + ("\n\n" + tags if tags else "")).strip()


def video_url(post):
    return f"{VIDEO_BASE}/{post['video']}.mp4" if post.get("video") else ""


def to_facebook(post, ptoken, page_id):
    if post.get("video"):  # video post: title from the post, caption as description
        r = call("POST", f"{page_id}/videos", file_url=video_url(post), description=caption(post),
                 title=post.get("video_title", ""), access_token=ptoken)
        return r.get("id")
    extra = {"published": "false"} if post.get("dark") else {}  # dark post: exists for ads only, never in the feed
    r = call("POST", f"{page_id}/photos", url=f"{IMAGE_BASE}/{post['id']}.jpg", message=caption(post), access_token=ptoken, **extra)
    return r.get("post_id") or r.get("id")


def to_instagram(post, ig_id):
    if post.get("video"):  # reel; Meta transcodes so status polling takes longer
        c = call("POST", f"{ig_id}/media", media_type="REELS", video_url=video_url(post), caption=caption(post),
                 share_to_feed="true", access_token=TOKEN)["id"]
        tries = 60
    else:
        c = call("POST", f"{ig_id}/media", image_url=f"{IMAGE_BASE}/{post['id']}.jpg", caption=caption(post), access_token=TOKEN)["id"]
        tries = 20
    for _ in range(tries):
        st = call("GET", c, fields="status_code", access_token=TOKEN).get("status_code")
        if st == "FINISHED":
            break
        if st == "ERROR":
            raise RuntimeError(f"instagram container {c} failed: " + str(call("GET", c, fields="status", access_token=TOKEN).get("status")))
        time.sleep(5)
    return call("POST", f"{ig_id}/media_publish", creation_id=c, access_token=TOKEN)["id"]


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
    tokens = {}
    failed = False
    for p, post in due:
        ids = PAGES.get(post.get("page", "money"), {})
        if not ids.get("page"):
            print("skip", post["id"], "- no page ids for", post.get("page")); continue
        if not DRY and ids["page"] not in tokens:
            tokens[ids["page"]] = page_token(ids["page"])
        channels = post.get("channels", ["facebook", "instagram"])
        res = post.setdefault("results", {})
        try:
            if "facebook" in channels and "facebook" not in res:
                res["facebook"] = "dry-run" if DRY else to_facebook(post, tokens[ids["page"]], ids["page"])
            if "instagram" in channels and "instagram" not in res:
                if not ids.get("ig"):
                    raise RuntimeError("no instagram id for page " + post.get("page", "money"))
                res["instagram"] = "dry-run" if DRY else to_instagram(post, ids["ig"])
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
