"""Build a self-contained review brief (Markdown) per brand, for an outside reviewer's AI (e.g. Ofir's):
the product facts, the marketing plan, what was decided since, every post (published and upcoming) with its
on-image text and caption, and the questions we want answered.

Usage: review_md.py   -> reviews/review-money.md, reviews/review-studio.md
"""
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
RAW = "https://raw.githubusercontent.com/eyal-hg/hk-social/main"


MOCK = {"feed", "hl"}


class MD(HTMLParser):
    """Small HTML -> Markdown converter for the plan fragments (headings, paragraphs, lists, tables, bold)."""
    def __init__(self):
        super().__init__(); self.out = []; self.buf = ""; self.skip = 0; self.row = None; self.rows = []; self.li = 0
        self.mock = 0  # depth inside a decorative mock block (feed tiles, highlight circles)
    def flush(self, prefix=""):
        t = re.sub(r"\s+", " ", self.buf).strip(); self.buf = ""
        if t: self.out.append(prefix + t)
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg"): self.skip += 1; return
        if self.mock:
            self.mock += tag == "div"; return
        if tag == "div" and set((dict(attrs).get("class") or "").split()) & MOCK:
            self.flush(); self.mock = 1; return
        if tag in ("h1", "h2", "h3", "h4", "p", "div", "section", "ul", "ol", "table", "blockquote"): self.flush()
        if tag == "li": self.flush(); self.li += 1
        if tag in ("strong", "b"): self.buf += "**"
        if tag == "br": self.buf += " "
        if tag == "tr": self.row = []
        if tag in ("td", "th"): self.flush()
    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg"): self.skip -= 1; return
        if self.mock:
            self.mock -= tag == "div"; return
        if tag in ("h1", "h2", "h3", "h4"): self.flush("#" * (int(tag[1]) + 2) + " "); self.out.append("")
        elif tag == "li": self.flush("- "); self.li -= 1
        elif tag in ("p", "div", "section", "blockquote"): self.flush(); self.out.append("")
        elif tag in ("strong", "b"): self.buf += "**"
        elif tag in ("td", "th") and self.row is not None:
            self.row.append(re.sub(r"\s+", " ", self.buf).strip().replace("|", "/")); self.buf = ""
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row); self.row = None
        elif tag == "table" and self.rows:
            w = max(len(r) for r in self.rows)
            for i, r in enumerate(self.rows):
                self.out.append("| " + " | ".join(r + [""] * (w - len(r))) + " |")
                if i == 0: self.out.append("|" + "---|" * w)
            self.out.append(""); self.rows = []
    def handle_data(self, data):
        if not self.skip and not self.mock: self.buf += data


def html_to_md(path):
    p = MD(); p.feed(path.read_text(encoding="utf-8")); p.flush()
    text = "\n".join(p.out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def strip(t):
    return re.sub(r"<[^>]+>", "", t or "").strip()


def on_image(p):
    L = []
    if p.get("video"):
        return [f"- **סרטון** ({p.get('video_title', '')}) — קובץ: {RAW}/video/{p['video']}.mp4"]
    if p.get("kicker"): L.append(f"- תגית: {p['kicker']}")
    if p.get("title"): L.append(f"- כותרת: {strip(p['title'])}")
    if p.get("body"): L.append(f"- משפט משנה: {strip(p['body'])}")
    for s in p.get("steps", []): L.append(f"- שלב: **{strip(s.get('title'))}** — {strip(s.get('text'))}")
    for c in p.get("chat", []): L.append(f"- {'שאלה' if c.get('from') == 'q' else 'תשובה'}: {strip(c.get('text'))}")
    for side in ("left", "right"):
        if p.get(side): L.append(f"- עמודה \"{strip(p[side].get('title'))}\": " + " · ".join(strip(x) for x in p[side].get("items", [])))
    if p.get("cta"): L.append(f"- שורת הנעה בתמונה: {strip(p['cta'])}")
    L.append(f"- התמונה: {RAW}/out/{p['id']}.jpg")
    return L


def post_block(p):
    status = {"published": "רץ כמודעה" if p.get("dark") else "פורסם", "approved": "מאושר, מתוזמן", "pending": "טיוטה, מחכה לאישור", "rejected": "נדחה"}.get(p.get("status"), p.get("status"))
    L = [f"### {p['id']} · {p['publish_date']} · {p.get('type', '')} · {status}", "", "**מה כתוב בתמונה**"] + on_image(p)
    L += ["", "**הכיתוב (caption)**", "", "> " + (p.get("caption") or "").strip().replace("\n", "\n> ")]
    if p.get("hashtags"): L += ["", "האשטגים: " + " ".join("#" + h for h in p["hashtags"])]
    if p.get("note"): L += ["", f"הערת עבודה: {p['note']}"]
    return L + [""]


BRANDS = {
    "money": {
        "title": "HK Money", "plan": "plan-money.html", "guide": "guidelines.md",
        "who": "בעלי עסקים קטנים ובינוניים בישראל. לא אנשי כספים.",
        "what": "HK Money הוא שירות (לא תוכנה) לבעלי עסקים: מנהל תזרים אישי שעובר על הכסף של העסק כל יום עסקים, פגישה חודשית עם יועץ פיננסי, ועוזר AI שעונה על המספרים של העסק. הלקוח רואה תחזית תזרים חודשים קדימה, עם חריגה צפויה מסומנת מראש.",
        "since": [
            "המוצר נקרא **HK Money בלבד** (בלי \"פלוס\", בלי מסלולים וחבילות). הוא כולל את הפגישה החודשית עם היועץ.",
            "במקום \"תחזית עד 60 יום\" כותבים **\"חודשים קדימה\"**.",
            "מסר חדש: **אנחנו מתחברים לבנק, לאשראי ולמערכות המידע של העסק**, כך שהתחזית מתעדכנת יום-יום.",
            "אייל: **ה-AI הוא לב המוצר**, והוא צריך להופיע במסרים. ה-AI מוצג כעוזר שעונה על שאלות; את העבודה עושה אדם.",
            "ממומן (3.10): המודעה שמביאה את הלידים הזולים ביותר היא סרטון מינואר 2025 שמוכר ליווי תזרים בלי AI (כ-47 ₪ לליד). נוספו לצדו שני סרטונים מסדרת ה-AI (\"מיקונוס\" המקוצר ו\"מהפכת ה-AI\"). עדיין מוקדם להשוות ביניהם.",
        ],
        "extra_q": [
            "הסרטון שמביא הכי הרבה לידים לא מזכיר AI. האם לדעתך המסר של ה-AI משכנע בעל עסק, או שהוא מרחיק? איך היית מנסח אותו?",
            "הפוסט 2026-W41-02 אומר \"רואה החשבון מסתכל אחורה. אנחנו קדימה.\" כרואה חשבון: הניסוח הוגן ומדויק? הוא עלול להרגיז רואי חשבון שמפנים אלינו לקוחות?",
        ],
    },
    "studio": {
        "title": "HK Studio", "plan": "plan-studio.html", "guide": "guidelines-studio.md",
        "who": "יועצים עסקיים, יועצים פיננסיים ורואי חשבון בישראל שמלווים לקוחות עסקיים.",
        "what": "HK Studio הוא תשתית ליועצים: מערכת עבודה, AI שמסכם, זוכר ומכין כל פגישה, וצוות פיננסי של HK שעובד מאחורי היועץ. הכול יוצא ללקוח בשם המשרד של היועץ ועם הלוגו שלו.",
        "since": [
            "ממומן (27.9–4.10): כ-357 ₪ הושקעו בקמפיינים ליועצים, **בלי אף ליד**.",
            "קמפיין שהפנה לדף הנחיתה (studio.hak.co.il): 207 כניסות לדף, 0 טפסים.",
            "מ-3.10 רץ קמפיין עם טופס בתוך פייסבוק (שם, טלפון, \"כמה לקוחות עסקיים אתה מלווה היום?\"). ביממה הראשונה: 291 איש נחשפו, 5 לחצו על המודעה, אף אחד לא השאיר פרטים. מוקדם להסיק.",
            "ההצעה בכל המודעות והפוסטים: \"שלושים דקות עם אופיר\". ההשערה שלנו: יועצים לוחצים מסקרנות, אבל פגישה היא בקשה גדולה מדי למי שלא מכיר אותנו.",
            "המודעות שרצות עכשיו (SA2, SA3) מופיעות למטה תחת \"מודעות\".",
        ],
        "extra_q": [
            "אתה רואה חשבון ויועץ. אם היית רואה את המודעות והפוסטים האלה בפיד, מה היה גורם לך להשאיר פרטים, ומה מונע ממך?",
            "\"שלושים דקות עם אופיר\" — האם זו ההצעה הנכונה לפתיחה? מה היית מציע במקומה (הדגמה מוקלטת, סיור במערכת, מקרה לדוגמה)?",
            "מה הכאב שהכי מניע יועץ לשנות את דרך העבודה שלו, ואיך הוא עצמו היה מנסח אותו?",
        ],
    },
}


def main():
    now = datetime.now(ZoneInfo("Asia/Jerusalem")).strftime("%d.%m.%Y")
    posts = [json.loads(q.read_text(encoding="utf-8")) for q in sorted(ROOT.glob("posts/**/*.json"))]
    (ROOT / "reviews").mkdir(exist_ok=True)
    for key, b in BRANDS.items():
        mine = sorted([p for p in posts if p.get("page", "money") == key], key=lambda p: (p["publish_date"], p["id"]))
        organic = [p for p in mine if not p.get("dark")]
        ads = [p for p in mine if p.get("dark")]
        L = [f"# {b['title']} — בקשה לחוות דעת על הפוסטים ועל תוכנית השיווק", "",
             f"עודכן: {now} · הוכן עבור אופיר קריספין", "",
             "## איך להשתמש במסמך הזה", "",
             "המסמך הזה מיועד להדבקה או לצירוף ל-AI שעובד עם אופיר. הוא עומד בפני עצמו: יש בו מה המוצר, מה התוכנית, מה כבר פורסם ומה מתוכנן.", "",
             "**הוראות ל-AI שקורא את המסמך:**", "",
             "אתה עוזר לאופיר קריספין, רואה חשבון ולשעבר סמנכ״ל כספים, שותף ב-HK (חזות קריספין), לגבש חוות דעת מקצועית על הנוכחות של " + b["title"] + " בפייסבוק ובאינסטגרם.",
             "עבור על המסמך כולו. אחר כך שאל את אופיר את השאלות שבסעיף \"מה אנחנו רוצים לדעת\", אחת אחת או בקבוצות קטנות, והוסף את ההערות שלך על כל פוסט.",
             "כשאופיר סיים, הפק את חוות הדעת בפורמט שבסוף המסמך. כתוב בעברית פשוטה וישירה. אל תמציא מספרים, שמות לקוחות או יכולות שלא מופיעות כאן.", "",
             "## המוצר והקהל", "", b["what"], "", f"**למי מדברים:** {b['who']}", "",
             "## מה השתנה מאז שנכתבה התוכנית", ""] + [f"- {x}" for x in b["since"]] + ["",
             "## מה מותר ומה אסור לומר (הנחיות התוכן)", "", re.sub(r"(?m)^(#+) ", lambda m: "#" * (len(m.group(1)) + 2) + " ", (ROOT / "content" / b["guide"]).read_text(encoding="utf-8").strip()), "",
             "## תוכנית השיווק", "", "כך נכתבה התוכנית ב-27.9.2026. שים לב לסעיף \"מה השתנה\" למעלה, שגובר עליה.", "",
             html_to_md(ROOT / "content" / b["plan"]), "",
             "## הפוסטים", "", f"סה\"כ {len(organic)} פוסטים: {sum(1 for p in organic if p.get('status') == 'published')} פורסמו, {sum(1 for p in organic if p.get('status') != 'published')} מתוכננים.", ""]
        for p in organic: L += post_block(p)
        if ads:
            L += ["## מודעות (קריאייטיב ממומן, לא מופיע בפיד)", ""]
            for p in ads: L += post_block(p)
        L += ["## מה אנחנו רוצים לדעת", "", "**על כל פוסט:**", "",
              "1. האם כל מה שנאמר בו נכון מקצועית? יש ניסוח שרואה חשבון או בעל עסק יתפוס כלא מדויק או כמבטיח יותר מדי?",
              "2. האם מי שהפוסט מיועד לו יעצור עליו? מה חזק בו ומה חלש?",
              "3. איך אופיר היה אומר את זה במילים שלו?",
              "4. ציון 1–5, והחלטה: להשאיר / לתקן / להוריד.", "",
              "**על התמונה הכוללת:**", "",
              "5. אילו סוגי פוסטים להמשיך, ואילו להפסיק?",
              "6. אילו נושאים חסרים, מנקודת מבט של מי שיושב מול לקוחות כל יום?",
              "7. חמישה רעיונות לפוסטים ממצבים אמיתיים (בלי שמות ובלי פרטים מזהים)."]
        L += [f"{n}. {q}" for n, q in enumerate(b["extra_q"], 8)]
        L += ["", "## הפורמט שבו נרצה לקבל את חוות הדעת", "",
              "1. **שורה תחתונה** — שלושה-ארבעה משפטים: מה עובד, מה לא, ומה הדבר האחד שהכי כדאי לשנות.",
              "2. **טבלה** — שורה לכל פוסט: מזהה, ציון, החלטה (להשאיר / לתקן / להוריד), והערה במשפט אחד.",
              "3. **תיקוני ניסוח** — לכל פוסט שסומן \"לתקן\": הנוסח המוצע לכותרת ולכיתוב.",
              "4. **טעויות מקצועיות** — כל ניסוח שאינו מדויק, עם הנוסח הנכון.",
              "5. **רעיונות חדשים** — רשימה קצרה, כל רעיון במשפט או שניים.",
              "6. **תשובות לשאלות 5 ואילך.**", ""]
        out = ROOT / "reviews" / f"review-{key}.md"
        out.write_text("\n".join(L), encoding="utf-8")
        print(out.name, len("\n".join(L)), "chars", len(organic), "posts", len(ads), "ads")


if __name__ == "__main__":
    main()
