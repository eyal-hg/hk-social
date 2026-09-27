"""Render every post JSON in posts/ into out/<id>.jpg (1080x1350) using headless Chrome."""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "template" / "post.html"
OUT = ROOT / "out"

CHROME_CANDIDATES = [
    os.environ.get("CHROME", ""),
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def chrome_bin():
    for c in CHROME_CANDIDATES:
        if c and (shutil.which(c) or Path(c).exists()):
            return shutil.which(c) or c
    sys.exit("Chrome not found; set CHROME env var")


def safe_inline(text):
    # רק <em> ו-<span> מותרים בכותרת ובהנעה לפעולה; כל השאר מוצג כטקסט
    esc = html.escape(text, quote=False)
    return re.sub(r"&lt;(/?)(em|span)&gt;", r"<\1\2>", esc)


def render(post, chrome):
    data = {k: v for k, v in post.items() if k in ("layout", "kicker", "body", "logo", "photo", "chat", "steps", "left", "right", "url")}
    data["title"] = safe_inline(post.get("title", ""))
    data["cta"] = "" if "cta" in post and not str(post["cta"]).strip() else safe_inline(post.get("cta", "פגישת אבחון <span>חינם</span>"))
    data.setdefault("logo", "hk")
    src = TEMPLATE.read_text(encoding="utf-8")
    src = re.sub(r"/\*POST_JSON\*/.*?/\*END\*/", "/*POST_JSON*/" + json.dumps(data, ensure_ascii=False) + "/*END*/", src, flags=re.S)
    with tempfile.NamedTemporaryFile("w", suffix=".html", dir=TEMPLATE.parent, delete=False, encoding="utf-8") as f:
        f.write(src)
        page = Path(f.name)
    png = OUT / f"{post['id']}.png"
    try:
        subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
             "--window-size=1080,1350", "--virtual-time-budget=6000", f"--screenshot={png}", page.as_uri()],
            check=True, capture_output=True, timeout=90,
        )
    finally:
        page.unlink(missing_ok=True)
    jpg = OUT / f"{post['id']}.jpg"
    Image.open(png).convert("RGB").resize((1080, 1350)).save(jpg, "JPEG", quality=92)
    png.unlink()
    return jpg


def main():
    OUT.mkdir(exist_ok=True)
    chrome = chrome_bin()
    force = "--force" in sys.argv
    for p in sorted((ROOT / "posts").rglob("*.json")):
        post = json.loads(p.read_text(encoding="utf-8"))
        if post.get("video"):  # video posts have no rendered card
            continue
        jpg = OUT / f"{post['id']}.jpg"
        if force or not jpg.exists() or jpg.stat().st_mtime < p.stat().st_mtime:
            print("render", post["id"], "->", render(post, chrome).name)


if __name__ == "__main__":
    main()
