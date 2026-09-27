"""Build docs/ (served by GitHub Pages): a gated index for Eyal and Ofir, and one page per
brand (money / studio), each with two tabs — the marketing plan (content/plan-<page>.html,
a fragment with its own scoped <style>) and the posts (upcoming + past, straight from
posts/**/*.json; images from raw.githubusercontent.com/<repo>/main/out, like publish.py).

The gate is client-side: the page keeps a SHA-256 of the password, never the password.
Anyone who can read the repository can read the content — this is a curtain, not a lock.
"""
import html
import json
import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
GATE_HASH = "d0f4a76d4eb86c2edee3507ef18fe54fd8ed3745f49ebf81140f07adb0c670e4"
IMAGE_BASE = os.environ.get("IMAGE_BASE_URL", "https://raw.githubusercontent.com/eyal-hg/hk-social/main/out").rstrip("/")
PAGES = {
    "money": {"title": "HK Money", "sub": "לבעלי עסקים", "site": "hak.co.il"},
    "studio": {"title": "HK Studio", "sub": "ליועצים", "site": "studio.hak.co.il"},
}
STATUS = {"pending": "ממתין לאישור", "approved": "מאושר", "published": "פורסם", "rejected": "נדחה"}

# ה-tokens שקטעי התוכנית של שני העמודים מצפים להם (plan-money / plan-studio)
CSS = """
:root{--navy:#0c4068;--navy-2:#082f4d;--navy2:#082f4d;--salmon:#e48375;--blue:#39abe2;--sky:#39abe2;--coral:#E8635A;--off:#eef4f9;
--bg:#f6f9fc;--surface:#fff;--card:#fff;--ink:#16283a;--muted:#5a6b7c;--line:#d5e2ec;--tint:#e4f0f8;--soft:#e4f0f8;--good:#2e9e6b;--green:#13895B;--bad:#c0392b;--amber:#D9922B}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Heebo,Rubik,Arial,sans-serif;line-height:1.6}
.sh-top{background:var(--navy-2);color:#fff;padding:18px 24px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
.sh-top a{color:#fff;text-decoration:none;font-weight:700}.sh-top .sh-sub{color:var(--blue);font-size:14px}
.sh-tabs{display:flex;gap:6px;padding:16px 24px 0;max-width:1100px;margin:0 auto}
.sh-tabs button{font:inherit;font-weight:700;padding:10px 18px;border:1px solid var(--line);border-bottom:0;background:#fff;color:var(--muted);border-radius:12px 12px 0 0;cursor:pointer}
.sh-tabs button[aria-selected=true]{color:var(--navy);border-color:var(--navy);border-bottom:2px solid #fff;margin-bottom:-1px}
.sh-panel{max-width:1100px;margin:0 auto;padding:24px;background:#fff;border-top:1px solid var(--navy)}
.sh-panel[hidden]{display:none}
.sh-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:18px}
.sh-card{border:1px solid var(--line);border-radius:14px;overflow:hidden;background:#fff;border-top:4px solid var(--salmon)}
.sh-card img{width:100%;display:block;aspect-ratio:4/5;object-fit:cover;background:var(--off)}
.sh-card .m{padding:12px 14px;font-size:14px}.sh-card .r{display:flex;justify-content:space-between;font-weight:700}
.sh-card .cap{color:var(--ink);white-space:pre-line;margin:8px 0 0;font-size:13.5px;line-height:1.5}
.sh-card .st{font-size:12px;color:var(--muted)}.s-approved{border-top-color:var(--good)}.s-published{border-top-color:var(--navy);opacity:.75}
.sh-h{font-family:Rubik,Heebo,sans-serif;color:var(--navy);margin:28px 0 12px;font-size:22px}.sh-h:first-child{margin-top:0}
.sh-empty{color:var(--muted);padding:14px;border:1px dashed var(--line);border-radius:12px}
@media(max-width:600px){.sh-panel{padding:16px}}
"""

GATE_JS = """
(function(){
  try{ if(sessionStorage.getItem('hk-site-ok')==='1'){ document.documentElement.classList.add('ok'); return; } }catch(e){}
  if(/index\\.html$|\\/$/.test(location.pathname)) return;
  location.replace('index.html');
})();
"""

INDEX = """<!DOCTYPE html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>HK · סושיאל</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;700&family=Rubik:wght@700;800&display=swap">
<style>%(css)s
.gate{min-height:100vh;display:grid;place-items:center;padding:24px}
.box{background:#fff;border-radius:18px;padding:32px;max-width:440px;width:100%%;box-shadow:0 18px 50px rgba(12,64,104,.12);text-align:center}
.box h1{font-family:Rubik,sans-serif;color:var(--navy);margin:0 0 6px}.box p{color:var(--muted);margin:0 0 18px}
.box input{font:inherit;width:100%%;padding:12px 14px;border:1px solid var(--line);border-radius:10px;direction:ltr;text-align:center}
.box button{font:inherit;font-weight:700;width:100%%;margin-top:10px;padding:12px;border:0;border-radius:10px;background:var(--navy);color:#fff;cursor:pointer}
.err{color:var(--bad);font-size:13px;min-height:1.4em;margin-top:8px}
.links{display:none;grid-template-columns:1fr 1fr;gap:14px}.ok .links{display:grid}.ok form{display:none}
.links a{display:block;padding:22px 16px;border-radius:14px;background:var(--navy-2);color:#fff;text-decoration:none;font-weight:700;font-size:18px}
.links a small{display:block;color:var(--blue);font-weight:500;font-size:13px}
</style></head><body><div class="gate"><div class="box">
<h1>HK · סושיאל</h1><p>תוכניות השיווק והפוסטים של שני העמודים.</p>
<form id="f"><input id="pw" type="password" autocomplete="current-password" placeholder="סיסמה" required><button>כניסה</button><div class="err" id="err"></div></form>
<div class="links"><a href="money.html">HK Money<small>לבעלי עסקים · hak.co.il</small></a><a href="studio.html">HK Studio<small>ליועצים · studio.hak.co.il</small></a></div>
</div></div>
<script>
%(gate)s
document.getElementById('f').addEventListener('submit', async function(e){
  e.preventDefault();
  var buf=new TextEncoder().encode(document.getElementById('pw').value);
  var h=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',buf))).map(function(b){return b.toString(16).padStart(2,'0')}).join('');
  if(h==='%(hash)s'){ try{sessionStorage.setItem('hk-site-ok','1')}catch(x){} document.documentElement.classList.add('ok'); }
  else { document.getElementById('err').textContent='הסיסמה לא נכונה.'; }
});
</script></body></html>"""

PAGE = """<!DOCTYPE html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>%(title)s · סושיאל</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;700;800&family=Rubik:wght@500;700;800&family=Karantina:wght@400;700&family=Frank+Ruhl+Libre:wght@700;800&display=swap">
<style>%(css)s</style><script>%(gate)s</script></head><body>
<div class="sh-top"><div><a href="index.html">← כל העמודים</a></div><div><b>%(title)s</b> <span class="sh-sub">%(sub)s · %(site)s</span></div></div>
<div class="sh-tabs" role="tablist">
  <button role="tab" aria-selected="true" aria-controls="plan">תוכנית שיווק</button>
  <button role="tab" aria-selected="false" aria-controls="posts">פוסטים</button>
</div>
<section class="sh-panel" id="plan" role="tabpanel">%(plan)s</section>
<section class="sh-panel" id="posts" role="tabpanel" hidden>
  <h2 class="sh-h">הפוסטים הבאים</h2>%(upcoming)s
  <h2 class="sh-h">הפוסטים שהיו</h2>%(past)s
</section>
<script>
(function(){
  var tabs=document.querySelectorAll('[role=tab]');
  function show(id){ tabs.forEach(function(t){ var on=t.getAttribute('aria-controls')===id; t.setAttribute('aria-selected',on); document.getElementById(t.getAttribute('aria-controls')).hidden=!on; }); }
  tabs.forEach(function(t){ t.addEventListener('click',function(){ show(t.getAttribute('aria-controls')); history.replaceState(null,'','#'+t.getAttribute('aria-controls')); }); });
  if(location.hash==='#posts') show('posts');
})();
</script></body></html>"""


def card(post):
    st = post.get("status", "pending")
    return f"""<article class="sh-card s-{html.escape(st)}">
  <img src="{IMAGE_BASE}/{html.escape(post['id'])}.jpg" alt="" loading="lazy">
  <div class="m"><div class="r"><span>{html.escape(post['publish_date'])}</span><span class="st">{STATUS.get(st, st)}</span></div>
  <div class="st">{html.escape(post.get('kicker') or post.get('type',''))} · {html.escape(post.get('layout','statement'))}</div>
  <p class="cap">{html.escape(post.get('caption',''))}</p></div></article>"""


def grid(posts):
    return f'<div class="sh-grid">{"".join(card(p) for p in posts)}</div>' if posts else '<p class="sh-empty">אין עדיין.</p>'


def main():
    DOCS.mkdir(exist_ok=True)
    (DOCS / ".nojekyll").touch()
    today = date.today().isoformat()
    posts = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "posts").rglob("*.json"))]
    (DOCS / "index.html").write_text(INDEX % {"css": CSS, "gate": GATE_JS, "hash": GATE_HASH}, encoding="utf-8")
    for key, meta in PAGES.items():
        mine = [p for p in posts if p.get("page", "money") == key and p.get("status") != "rejected"]
        past = sorted([p for p in mine if p.get("status") == "published" or p["publish_date"] < today], key=lambda p: p["publish_date"], reverse=True)
        upcoming = sorted([p for p in mine if p not in past], key=lambda p: p["publish_date"])
        plan_file = ROOT / "content" / f"plan-{key}.html"
        plan = plan_file.read_text(encoding="utf-8") if plan_file.exists() else '<p class="sh-empty">תוכנית השיווק עוד לא נכנסה לכאן.</p>'
        (DOCS / f"{key}.html").write_text(PAGE % {"css": CSS, "gate": GATE_JS, "title": meta["title"], "sub": meta["sub"], "site": meta["site"],
                                                  "plan": plan, "upcoming": grid(upcoming), "past": grid(past)}, encoding="utf-8")
        print(f"docs/{key}.html  upcoming={len(upcoming)} past={len(past)} plan={'yes' if plan_file.exists() else 'placeholder'}")
    print("docs/index.html")


if __name__ == "__main__":
    main()
