"""Pull every video HK ever uploaded to Meta (ad account + both Pages) into the repo, so they can be
reposted slowly as organic posts.

Env: META_TOKEN, AD_ACCOUNT_ID, PAGE_ID, STUDIO_PAGE_ID.
  videos.py list      -> content/videos.json (id, title, length, dates, where it came from). Read-only.
  videos.py download  -> also saves video/<id>.mp4 for every ORIGINAL not yet on disk: Meta's Auto_Cropped
                         variants and Page re-uploads of the same cut are skipped, as are files > 95 MB
                         (raw.githubusercontent.com will not serve those).
Also collects the ad copy (message/title) that ran with each video, so a repost can reuse proven text.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPH = "https://graph.facebook.com/v21.0"
TOKEN = os.environ["META_TOKEN"]
MAX_MB = 95
FIELDS = "id,title,length,created_time,updated_time,source,permalink_url,thumbnails.limit(1){uri}"


def get(path, _token=None, **params):
    params["access_token"] = _token or TOKEN
    req = urllib.request.Request(f"{GRAPH}/{path}?{urllib.parse.urlencode(params)}")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"{path}: {e.code} {e.read().decode(errors='replace')[:300]}")


def page_token(page_id):
    try:
        return get(page_id, fields="access_token").get("access_token") or TOKEN
    except SystemExit:
        return TOKEN


def paged(path, token, **params):
    out, url = [], None
    while True:
        r = get(path, _token=token, **params) if url is None else json.load(urllib.request.urlopen(url, timeout=90))
        out += r.get("data", [])
        url = r.get("paging", {}).get("next")
        if not url:
            return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "list"
    sources = []
    acct = os.environ.get("AD_ACCOUNT_ID")
    if acct:
        sources.append(("ads", f"act_{acct.removeprefix('act_')}/advideos", TOKEN))
    for key, env in (("money", "PAGE_ID"), ("studio", "STUDIO_PAGE_ID")):
        if os.environ.get(env):
            sources.append((key, f"{os.environ[env]}/videos", page_token(os.environ[env])))

    copy = {}  # video_id -> [{message,title}] from the ad creatives that used it
    if acct:
        for c in paged(f"act_{acct.removeprefix('act_')}/adcreatives", TOKEN, fields="video_id,body,title,object_story_spec", limit=200):
            vd = ((c.get("object_story_spec") or {}).get("video_data") or {})
            vid = c.get("video_id") or vd.get("video_id")
            text = (vd.get("message") or c.get("body") or "").strip()
            if vid and text and text not in [x["message"] for x in copy.get(vid, [])]:
                copy.setdefault(vid, []).append({"message": text, "title": (vd.get("title") or c.get("title") or "").strip()})

    videos = {}
    for origin, path, tok in sources:
        rows = paged(path, tok, fields=FIELDS, limit=100)
        for v in rows:
            e = videos.setdefault(v["id"], {"id": v["id"], "title": v.get("title") or "", "seconds": round(float(v.get("length") or 0)),
                                            "created": (v.get("created_time") or "")[:10], "origins": [], "permalink": v.get("permalink_url", ""),
                                            "thumb": ((v.get("thumbnails") or {}).get("data") or [{}])[0].get("uri", "")})
            e["origins"].append(origin)
            e["_source"] = v.get("source")  # signed CDN url, not committed
            e["ad_copy"] = copy.get(v["id"], [])
            e["original"] = origin == "ads" and not e["title"].startswith("Auto_Cropped")

    vdir = ROOT / "video"; vdir.mkdir(exist_ok=True)
    for e in videos.values():
        f = vdir / f"{e['id']}.mp4"
        e["file"] = f"video/{f.name}" if f.exists() else ""
        if mode == "download" and e["original"] and not f.exists() and e.get("_source"):
            with urllib.request.urlopen(e["_source"], timeout=600) as r:
                size = int(r.headers.get("Content-Length") or 0)
                if size > MAX_MB * 1024 * 1024:
                    e["skipped"] = f"{size // 1024 // 1024} MB > {MAX_MB} MB"; print("skip (too big)", e["id"], e["title"], e["skipped"]); continue
                f.write_bytes(r.read())
            e["file"] = f"video/{f.name}"
            print("saved", e["id"], f"{f.stat().st_size // 1024 // 1024} MB", e["title"])
        e.pop("_source", None)

    rows = sorted(videos.values(), key=lambda x: x["created"], reverse=True)
    (ROOT / "content").mkdir(exist_ok=True)
    (ROOT / "content" / "videos.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(rows)} videos; on disk: {sum(1 for r in rows if r['file'])}")
    for r in rows:
        print(f"- {r['id']}  {r['seconds']:>4}s  {r['created']}  {'orig' if r['original'] else 'dup ':<5} copy×{len(r['ad_copy'])}  {r['title'][:60]}")


if __name__ == "__main__":
    main()
