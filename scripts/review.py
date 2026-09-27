"""Build review.html: every post with its image, caption, date and status — for the Sunday meeting."""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = {"pending": "ממתין לאישור", "approved": "מאושר", "published": "פורסם", "rejected": "נדחה"}


def card(post):
    tags = " ".join("#" + t.lstrip("#") for t in post.get("hashtags", []))
    err = f'<p class="err">שגיאה: {html.escape(post["last_error"])}</p>' if post.get("last_error") else ""
    return f"""
    <article class="card s-{html.escape(post.get('status','pending'))}">
      <img src="out/{html.escape(post['id'])}.jpg" alt="">
      <div class="meta">
        <div class="row"><b>{html.escape(post['publish_date'])}</b><span class="st">{STATUS.get(post.get('status'), post.get('status'))}</span></div>
        <div class="id">{html.escape(post['id'])} · {html.escape(post.get('service',''))} · {html.escape(post.get('type',''))}</div>
        <p class="cap">{html.escape(post['caption']).replace(chr(10), '<br>')}</p>
        <p class="tags">{html.escape(tags)}</p>{err}
      </div>
    </article>"""


def main():
    weeks = {}
    for p in sorted((ROOT / "posts").rglob("*.json")):
        post = json.loads(p.read_text(encoding="utf-8"))
        weeks.setdefault(p.parent.name, []).append(post)
    body = ""
    for week in sorted(weeks, reverse=True):
        body += f'<h2>{html.escape(week)}</h2><div class="grid">' + "".join(card(x) for x in sorted(weeks[week], key=lambda x: x["publish_date"])) + "</div>"
    (ROOT / "review.html").write_text(f"""<!DOCTYPE html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>HK · פוסטים לאישור</title>
<style>
body{{font-family:Heebo,Arial,sans-serif;background:#eef4f9;color:#0c4068;margin:0;padding:24px}}
h1{{margin:0 0 8px}} h2{{margin:32px 0 12px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:18px}}
.card{{background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 12px rgba(12,64,104,.08);border-top:4px solid #d8e8f2}}
.card img{{width:100%;display:block}} .meta{{padding:14px}}
.row{{display:flex;justify-content:space-between}} .id{{font-size:12px;color:#56677a;margin:4px 0 8px}}
.cap{{font-size:14px;line-height:1.55;color:#333344}} .tags{{font-size:12px;color:#39abe2}}
.st{{font-size:12px;font-weight:700}} .s-approved{{border-top-color:#2e9e6b}} .s-published{{border-top-color:#0c4068;opacity:.7}}
.s-rejected{{border-top-color:#c0392b;opacity:.5}} .s-pending{{border-top-color:#e48375}} .err{{color:#c0392b;font-size:12px}}
</style></head><body><h1>פוסטים לאישור</h1><p>מאשרים בפגישת יום ראשון. פוסט שלא אושר לא עולה.</p>{body}</body></html>""", encoding="utf-8")
    print("review.html written")


if __name__ == "__main__":
    main()
