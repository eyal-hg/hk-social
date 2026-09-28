"""Read-only report on the HK ad account: campaigns, ad sets, ads and their last-7/30-day results.

Env: META_TOKEN (must carry ads_read), AD_ACCOUNT_ID (numeric, without "act_").
Writes reports/ads-latest.md and reports/ads-latest.json. Changes nothing on Meta.
Uses 4 API calls in total (account-level insights with level=ad / level=campaign) to stay under Meta's rate limit.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
GRAPH = "https://graph.facebook.com/v21.0"
TOKEN = os.environ["META_TOKEN"]
ACCT = "act_" + os.environ["AD_ACCOUNT_ID"].removeprefix("act_")
LEAD_TYPES = ("lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead")


def get(path, **params):
    params["access_token"] = TOKEN
    req = urllib.request.Request(f"{GRAPH}/{path}?{urllib.parse.urlencode(params)}")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"{path}: {e.code} {e.read().decode(errors='replace')[:300]}")


def parse(row):
    def pick(key):
        for a in row.get(key, []) or []:
            if a.get("action_type") in LEAD_TYPES:
                return float(a.get("value", 0))
        return 0.0
    lpv = next((float(a.get("value", 0)) for a in row.get("actions", []) or [] if a.get("action_type") == "landing_page_view"), 0.0)
    return {"spend": float(row.get("spend", 0) or 0), "impressions": int(row.get("impressions", 0) or 0),
            "reach": int(row.get("reach", 0) or 0), "clicks": int(row.get("clicks", 0) or 0),
            "ctr": float(row.get("ctr", 0) or 0), "cpc": float(row.get("cpc", 0) or 0),
            "leads": pick("actions"), "cost_per_lead": pick("cost_per_action_type") or None, "landing_page_views": lpv}


def insights(level, preset):
    fields = "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,spend,impressions,reach,clicks,ctr,cpc,actions,cost_per_action_type"
    rows = get(f"{ACCT}/insights", level=level, fields=fields, date_preset=preset, limit=500).get("data", [])
    key = {"campaign": "campaign_id", "adset": "adset_id", "ad": "ad_id"}[level]
    return {r[key]: {**parse(r), "_names": r} for r in rows}


def money(v):
    return f"{float(v):,.0f} ₪" if v not in (None, "", 0, 0.0) else "—"


def agor(v):
    return money(int(v) / 100) if v else "—"


def main():
    now = datetime.now(ZoneInfo("Asia/Jerusalem")).strftime("%d.%m.%Y %H:%M")
    acct = get(ACCT, fields="name,currency,account_status,amount_spent")
    camps = get(f"{ACCT}/campaigns", fields="name,effective_status,objective,daily_budget,lifetime_budget,start_time,stop_time,updated_time", limit=50).get("data", [])
    c7, c30, ad7 = insights("campaign", "last_7d"), insights("campaign", "last_30d"), insights("ad", "last_7d")
    call_ = insights("campaign", "maximum")
    adall = insights("ad", "maximum")
    cy, sy, ady = insights("campaign", "yesterday"), insights("adset", "yesterday"), insights("ad", "yesterday")
    ctd, adtd = insights("campaign", "today"), insights("ad", "today")
    adsets = defaultdict(list)
    for s in get(f"{ACCT}/adsets", fields="campaign_id,name,effective_status,daily_budget,optimization_goal,destination_type,start_time,end_time", limit=200).get("data", []):
        adsets[s["campaign_id"]].append(s)
    zero = parse({})
    by_camp = defaultdict(list)
    for aid, row in ad7.items():
        by_camp[row["_names"]["campaign_id"]].append((aid, row))

    by_camp_all = defaultdict(list)
    for aid, row in adall.items():
        by_camp_all[row["_names"]["campaign_id"]].append((aid, row))
    report = {"generated": now, "account": acct, "campaigns": []}
    L = [f"# דוח מודעות · {acct.get('name')} · {now}", "",
         f"מצב חשבון: {acct.get('account_status')} · מטבע: {acct.get('currency')} · הוצאה מצטברת: {agor(acct.get('amount_spent'))}", ""]
    for c in camps:
        a, b, z = c7.get(c["id"], zero), c30.get(c["id"], zero), call_.get(c["id"], zero)
        ads = [{"id": aid, "adset": r["_names"].get("adset_name"), "name": r["_names"].get("ad_name"),
                **{k: v for k, v in r.items() if k != "_names"}} for aid, r in by_camp.get(c["id"], [])]
        report["campaigns"].append({"id": c["id"], "name": c["name"], "status": c.get("effective_status"), "objective": c.get("objective"),
                                    "daily_budget": c.get("daily_budget"), "lifetime_budget": c.get("lifetime_budget"),
                                    "start_time": c.get("start_time"), "stop_time": c.get("stop_time"), "updated_time": c.get("updated_time"),
                                    "adsets": adsets.get(c["id"], []),
                                    "last7": {k: v for k, v in a.items() if k != "_names"}, "last30": {k: v for k, v in b.items() if k != "_names"},
                                    "lifetime": {k: v for k, v in z.items() if k != "_names"}, "ads_last7": ads,
                                    "ads_lifetime": [{"adset": r["_names"].get("adset_name"), "name": r["_names"].get("ad_name"), **{k: v for k, v in r.items() if k != "_names"}} for _, r in by_camp_all.get(c["id"], [])]})
        L += [f"## {c['name']}  ({c.get('effective_status')}, {c.get('objective')})",
              f"תקציב: יומי {agor(c.get('daily_budget'))} · כולל {agor(c.get('lifetime_budget'))} · התחלה {str(c.get('start_time',''))[:10]} · עדכון אחרון {str(c.get('updated_time',''))[:10]}", "",
              *[f"- קבוצה: {x['name']} ({x.get('effective_status')}, {x.get('optimization_goal')}, {x.get('destination_type')}, יומי {agor(x.get('daily_budget'))}, {str(x.get('start_time',''))[:10]}→{str(x.get('end_time',''))[:10]})" for x in adsets.get(c["id"], [])], "",
              "| טווח | הוצאה | חשיפות | קליקים | CTR | לידים | עלות לליד |", "|---|---|---|---|---|---|---|",
              f"| 7 ימים | {money(a['spend'])} | {a['impressions']:,} | {a['clicks']:,} | {a['ctr']:.2f}% | {a['leads']:.0f} | {money(a['cost_per_lead'])} |",
              f"| 30 ימים | {money(b['spend'])} | {b['impressions']:,} | {b['clicks']:,} | {b['ctr']:.2f}% | {b['leads']:.0f} | {money(b['cost_per_lead'])} |",
              f"| כל הזמן | {money(z['spend'])} | {z['impressions']:,} | {z['clicks']:,} | {z['ctr']:.2f}% | {z['leads']:.0f} | {money(z['cost_per_lead'])} |", ""]
        best = sorted(by_camp_all.get(c["id"], []), key=lambda kv: -kv[1]["spend"])[:5]
        if best:
            L += ["מודעות (כל הזמן, 5 הגדולות):"]
            for _, r in best:
                L += [f"- {r['_names'].get('adset_name')} › {r['_names'].get('ad_name')}: {money(r['spend'])}, {r['clicks']} קליקים, CTR {r['ctr']:.2f}%, {r['leads']:.0f} לידים, עלות לליד {money(r['cost_per_lead'])}"]
            L += [""]
        if ads:
            L += ["מודעות (7 ימים):"]
            for x in sorted(ads, key=lambda x: -x["spend"]):
                L += [f"- {x['adset']} › {x['name']}: {money(x['spend'])}, {x['clicks']} קליקים, {x['leads']:.0f} לידים, עלות לליד {money(x['cost_per_lead'])}"]
            L += [""]
        else:
            L += ["לא רצה ב-7 הימים האחרונים.", ""]

    # ads that Meta flags (errors, disapproved, in review) — the Ads Manager "שגיאות במודעה" badge
    # everything Meta flags on ACTIVE campaigns: ad-set issues, ad issues, review feedback (the "שגיאות במודעה" badge)
    active_ids = [c["id"] for c in camps if c.get("effective_status") == "ACTIVE"]
    L += ["## מצב מפורט של הקמפיינים הפעילים", ""]
    detail = {}
    for cid in active_ids:
        name = next(c["name"] for c in camps if c["id"] == cid)
        sets = get(f"{cid}/adsets", fields="name,status,effective_status,issues_info,daily_budget", limit=50).get("data", [])
        ads_ = get(f"{cid}/ads", fields="name,status,effective_status,issues_info,ad_review_feedback,adset_id", limit=100).get("data", [])
        detail[cid] = {"adsets": sets, "ads": ads_}
        L += [f"### {name}"]
        for st in sets:
            L += [f"- קבוצה {st['name']}: {st.get('status')}/{st.get('effective_status')} · יומי {agor(st.get('daily_budget'))}"]
            for i in st.get("issues_info") or []:
                L += [f"  - ⚠ {i.get('error_summary', '')}: {i.get('error_message', '')} [{i.get('level', '')} {i.get('error_code', '')}]"]
            for ad in [a for a in ads_ if a.get("adset_id") == st["id"]]:
                L += [f"  - מודעה {ad['name']} ({ad['id']}): {ad.get('status')}/{ad.get('effective_status')}"]
                for i in ad.get("issues_info") or []:
                    L += [f"    - ⚠ {i.get('error_summary', '')}: {i.get('error_message', '')} [{i.get('level', '')} {i.get('error_code', '')}]"]
                if ad.get("ad_review_feedback"):
                    L += [f"    - ביקורת: {json.dumps(ad['ad_review_feedback'], ensure_ascii=False)[:400]}"]
        L += [""]
    report["active_detail"] = detail

    # today so far, per active campaign and ad (for intraday questions)
    L += [f"## היום עד עכשיו ({now})", ""]
    for c in camps:
        if c.get("effective_status") != "ACTIVE":
            continue
        t = ctd.get(c["id"], zero)
        L += [f"- {c['name']}: {money(t['spend'])}, {t['impressions']:,} חשיפות, {t['clicks']} קליקים, {t['landing_page_views']:.0f} צפיות בדף, {t['leads']:.0f} לידים ({money(t['cost_per_lead'])}/ליד)"]
        for aid, r in adtd.items():
            if r["_names"].get("campaign_id") == c["id"] and (r["spend"] or r["leads"]):
                L += [f"  - {r['_names'].get('ad_name')}: {money(r['spend'])}, {r['clicks']} קליקים, {r['leads']:.0f} לידים"]
    L += [""]
    report["today"] = {cid: {k: v for k, v in r.items() if k != "_names"} for cid, r in ctd.items()}

    # delivery diagnostics for active campaigns with zero impressions today (why is Meta not showing the ads?)
    stuck = [c for c in camps if c.get("effective_status") == "ACTIVE" and not ctd.get(c["id"], zero)["impressions"]]
    if stuck:
        L += ["## אבחון אי-הצגה", ""]
        acct_diag = get(ACCT, fields="account_status,disable_reason,spend_cap,amount_spent,funding_source_details")
        L += [f"- חשבון: status {acct_diag.get('account_status')} · disable_reason {acct_diag.get('disable_reason')} · spend_cap {acct_diag.get('spend_cap')} · מימון {json.dumps(acct_diag.get('funding_source_details'), ensure_ascii=False)[:120]}"]
        for c in stuck:
            cd = get(c["id"], fields="effective_status,configured_status,issues_info,start_time,stop_time,daily_budget,lifetime_budget,special_ad_categories")
            L += [f"- קמפיין {c['name']}: {json.dumps(cd, ensure_ascii=False)[:400]}"]
            for st in get(f"{c['id']}/adsets", fields="name,effective_status,configured_status,learning_stage_info,issues_info,start_time,end_time,daily_budget,bid_strategy,optimization_goal,billing_event,targeting,recommendations", limit=20).get("data", []):
                L += [f"  - קבוצה {st['name']}: {json.dumps({k: v for k, v in st.items() if k not in ('name', 'id')}, ensure_ascii=False)[:1500]}"]
            for ad in get(f"{c['id']}/ads", fields="name,effective_status,configured_status,issues_info,ad_review_feedback,preview_shareable_link,created_time,updated_time", limit=20).get("data", []):
                L += [f"  - מודעה {ad['name']}: {json.dumps({k: v for k, v in ad.items() if k not in ('name', 'id')}, ensure_ascii=False)[:600]}"]
        L += [""]

    # pixel health: last event time + last-day event counts (PageView / Lead)
    L += ["## פיקסל", ""]
    pixels = get(f"{ACCT}/adspixels", fields="name,last_fired_time", limit=10).get("data", [])
    if not pixels:  # the account listing comes back empty for this app; fall back to the ids recorded by ads_apply
        ids = set()
        for q in (ROOT / "ads" / "plans").glob("*.json"):
            for x in json.loads(q.read_text(encoding="utf-8")).get("applied", []):
                if x.get("ok") and (x.get("result") or {}).get("pixel_id"):
                    ids.add(x["result"]["pixel_id"])
        pixels = [get(i, fields="name,last_fired_time") | {"id": i} for i in sorted(ids)]
    for px in pixels:
        stats = get(f"{px['id']}/stats", aggregation="event", start_time=int(datetime.now().timestamp()) - 86400 * 3).get("data", [])
        counts = {}
        for row in stats:
            for d in row.get("data", []):
                counts[d.get("value")] = counts.get(d.get("value"), 0) + int(d.get("count", 0))
        L += [f"- {px['name']} ({px['id']}): ירה לאחרונה {str(px.get('last_fired_time', '—'))[:16]} · 3 ימים: " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "אין אירועים")]
        report.setdefault("pixels", []).append({"id": px["id"], "name": px["name"], "last_fired_time": px.get("last_fired_time"), "events_3d": counts})
    L += [""]

    # ---- daily e-mail: yesterday, per active campaign / ad set / ad ----
    yday = (datetime.now(ZoneInfo("Asia/Jerusalem")) - __import__("datetime").timedelta(days=1)).strftime("%d.%m.%Y")
    def pct(v): return f"{float(v):.2f}%"
    def num(v): return f"{int(v):,}"
    def row(name, r, bold=False):
        st = ' style="font-weight:700;background:#eef4f9"' if bold else ""
        return (f"<tr{st}><td>{name}</td><td>{money(r['spend'])}</td><td>{num(r['impressions'])}</td><td>{num(r['reach'])}</td>"
                f"<td>{num(r['clicks'])}</td><td>{pct(r['ctr'])}</td><td>{money(r['cpc'])}</td><td>{num(r['landing_page_views'])}</td>"
                f"<td>{r['leads']:.0f}</td><td>{money(r['cost_per_lead'])}</td></tr>")
    head = ("<tr><th>שם</th><th>הוצאה</th><th>חשיפות</th><th>הגעה</th><th>קליקים</th><th>CTR</th><th>עלות לקליק</th>"
            "<th>צפיות בדף</th><th>לידים</th><th>עלות לליד</th></tr>")
    css = ("<style>body{font-family:Arial,Helvetica,sans-serif;direction:rtl;color:#0c4068;max-width:900px;margin:0 auto;padding:16px}"
           "h1{font-size:22px}h2{font-size:17px;margin:22px 0 6px}table{border-collapse:collapse;width:100%;font-size:13px}"
           "th,td{border:1px solid #d6e0ea;padding:6px 8px;text-align:right;white-space:nowrap}th{background:#0c4068;color:#fff}"
           ".muted{color:#5a6f84;font-size:12px}.warn{background:#fff1ee;border:1px solid #e48375;padding:8px 12px;border-radius:8px;margin:8px 0}</style>")
    H = [f"<!doctype html><html lang=he dir=rtl><head><meta charset=utf-8>{css}</head><body>",
         f"<h1>דוח מודעות יומי · HK · ביצועי אתמול {yday}</h1>",
         f"<p class=muted>נוצר {now} · חשבון {acct.get('name')} · הוצאה מצטברת {agor(acct.get('amount_spent'))}</p>"]
    tot = parse({})
    for c in camps:
        if c.get("effective_status") != "ACTIVE":
            continue
        y = cy.get(c["id"], zero)
        for k in ("spend", "impressions", "reach", "clicks", "leads", "landing_page_views"):
            tot[k] += y[k]
        H += [f"<h2>{c['name']} <span class=muted>({c.get('objective')})</span></h2>", "<table>", head, row("קמפיין · אתמול", y, True)]
        for st in detail.get(c["id"], {}).get("adsets", []):
            if st.get("effective_status") != "ACTIVE":
                continue
            H += [row(f"קבוצה · {st['name']} · יומי {agor(st.get('daily_budget'))}", sy.get(st["id"], zero))]
            for ad in detail[c["id"]]["ads"]:
                if ad.get("adset_id") == st["id"] and ad.get("effective_status") == "ACTIVE":
                    H += [row(f"&nbsp;&nbsp;מודעה · {ad['name']}", ady.get(ad["id"], zero))]
        H += ["</table>"]
        a7, a30 = c7.get(c["id"], zero), c30.get(c["id"], zero)
        H += [f"<p class=muted>7 ימים: {money(a7['spend'])}, {a7['leads']:.0f} לידים ({money(a7['cost_per_lead'])}/ליד) · 30 ימים: {money(a30['spend'])}, {a30['leads']:.0f} לידים ({money(a30['cost_per_lead'])}/ליד)</p>"]
        issues = [(st["name"], i) for st in detail.get(c["id"], {}).get("adsets", []) if st.get("effective_status") == "ACTIVE" for i in st.get("issues_info") or []]
        live_sets = {st["id"] for st in detail.get(c["id"], {}).get("adsets", []) if st.get("effective_status") == "ACTIVE"}
        issues += [(ad["name"], i) for ad in detail.get(c["id"], {}).get("ads", [])
                   if ad.get("adset_id") in live_sets and ad.get("effective_status") in ("WITH_ISSUES", "DISAPPROVED") for i in ad.get("issues_info") or []]
        for nm, i in issues:
            H += [f"<div class=warn>⚠ {nm}: {i.get('error_summary', '')} — {i.get('error_message', '')}</div>"]
    if tot["impressions"]:
        tot["ctr"] = tot["clicks"] / tot["impressions"] * 100
        tot["cpc"] = tot["spend"] / tot["clicks"] if tot["clicks"] else 0
        tot["cost_per_lead"] = tot["spend"] / tot["leads"] if tot["leads"] else None
    H += ["<h2>סה״כ אתמול (קמפיינים פעילים)</h2>", "<table>", head, row("סה״כ", tot, True), "</table>"]
    if report.get("pixels"):
        H += ["<h2>פיקסל</h2><ul>"] + [f"<li>{p['name']}: ירה לאחרונה {str(p.get('last_fired_time', '—'))[:16]} · 3 ימים: " +
                                        (", ".join(f"{k} {v}" for k, v in sorted(p['events_3d'].items())) or "אין אירועים") + "</li>" for p in report["pixels"]] + ["</ul>"]
    H += ["<p class=muted>הדוח המלא (7/30 ימים, כל הזמן, קמפיינים מושהים): github.com/eyal-hg/hk-social/blob/main/reports/ads-latest.md</p>", "</body></html>"]
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "daily-email.html").write_text("\n".join(H), encoding="utf-8")
    report["yesterday"] = {"date": yday, "campaigns": {cid: {k: v for k, v in r.items() if k != "_names"} for cid, r in cy.items()}, "total": tot}

    out = ROOT / "reports"; out.mkdir(exist_ok=True)
    (out / "ads-latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "ads-latest.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
