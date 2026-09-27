"""Read-only report on the HK ad account: campaigns, ad sets, ads and their last-7/30-day results.

Env: META_TOKEN (must carry ads_read), AD_ACCOUNT_ID (numeric, without "act_").
Writes reports/ads-latest.md and reports/ads-latest.json. Changes nothing on Meta.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
GRAPH = "https://graph.facebook.com/v21.0"
TOKEN = os.environ["META_TOKEN"]
ACCT = "act_" + os.environ["AD_ACCOUNT_ID"].removeprefix("act_")
FIELDS = "spend,impressions,reach,clicks,ctr,cpc,actions,cost_per_action_type"
LEAD_TYPES = ("lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead", "landing_page_view")


def get(path, **params):
    params["access_token"] = TOKEN
    req = urllib.request.Request(f"{GRAPH}/{path}?{urllib.parse.urlencode(params)}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"{path}: {e.code} {e.read().decode(errors='replace')[:300]}")


def actions(ins, key):
    for a in ins.get(key, []) or []:
        if a.get("action_type") in LEAD_TYPES:
            yield a["action_type"], float(a.get("value", 0))


def insights(obj_id, preset):
    d = get(f"{obj_id}/insights", fields=FIELDS, date_preset=preset).get("data") or [{}]
    ins = d[0]
    leads = {k: v for k, v in actions(ins, "actions")}
    cpl = {k: v for k, v in actions(ins, "cost_per_action_type")}
    return {
        "spend": float(ins.get("spend", 0) or 0), "impressions": int(ins.get("impressions", 0) or 0),
        "reach": int(ins.get("reach", 0) or 0), "clicks": int(ins.get("clicks", 0) or 0),
        "ctr": float(ins.get("ctr", 0) or 0), "cpc": float(ins.get("cpc", 0) or 0),
        "leads": leads.get("lead") or leads.get("onsite_conversion.lead_grouped") or 0,
        "cost_per_lead": cpl.get("lead") or cpl.get("onsite_conversion.lead_grouped") or None,
        "landing_page_views": leads.get("landing_page_view", 0),
    }


def main():
    now = datetime.now(ZoneInfo("Asia/Jerusalem")).strftime("%d.%m.%Y %H:%M")
    acct = get(ACCT, fields="name,currency,account_status,amount_spent,balance")
    camps = get(f"{ACCT}/campaigns", fields="name,status,effective_status,objective,daily_budget,lifetime_budget,created_time", limit=50).get("data", [])
    report = {"generated": now, "account": acct, "campaigns": []}
    for c in camps:
        row = {"id": c["id"], "name": c["name"], "status": c.get("effective_status"), "objective": c.get("objective"),
               "daily_budget": c.get("daily_budget"), "lifetime_budget": c.get("lifetime_budget"),
               "last7": insights(c["id"], "last_7d"), "last30": insights(c["id"], "last_30d"), "adsets": []}
        for s in get(f"{c['id']}/adsets", fields="name,effective_status,daily_budget,optimization_goal,targeting", limit=50).get("data", []):
            t = s.get("targeting", {}) or {}
            ads = [{"id": a["id"], "name": a["name"], "status": a.get("effective_status"), "last7": insights(a["id"], "last_7d")}
                   for a in get(f"{s['id']}/ads", fields="name,effective_status", limit=50).get("data", [])]
            row["adsets"].append({"id": s["id"], "name": s["name"], "status": s.get("effective_status"),
                                  "daily_budget": s.get("daily_budget"), "goal": s.get("optimization_goal"),
                                  "age": f"{t.get('age_min', '?')}-{t.get('age_max', '?')}",
                                  "geo": (t.get("geo_locations") or {}).get("countries"),
                                  "last7": insights(s["id"], "last_7d"), "ads": ads})
        report["campaigns"].append(row)

    out = ROOT / "reports"; out.mkdir(exist_ok=True)
    (out / "ads-latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def money(v): return f"{float(v):,.0f} ₪" if v not in (None, "") else "—"
    def agor(v): return money(int(v) / 100) if v else "—"
    L = [f"# דוח מודעות · {acct.get('name')} · {now}", "",
         f"מצב חשבון: {acct.get('account_status')} · מטבע: {acct.get('currency')} · הוצאה מצטברת: {agor(acct.get('amount_spent'))}", ""]
    for c in report["campaigns"]:
        a, b = c["last7"], c["last30"]
        L += [f"## {c['name']}  ({c['status']}, {c['objective']})",
              f"תקציב: יומי {agor(c['daily_budget'])} · כולל {agor(c['lifetime_budget'])}",
              "", "| טווח | הוצאה | חשיפות | קליקים | CTR | לידים | עלות לליד |", "|---|---|---|---|---|---|---|",
              f"| 7 ימים | {money(a['spend'])} | {a['impressions']:,} | {a['clicks']:,} | {a['ctr']:.2f}% | {a['leads']:.0f} | {money(a['cost_per_lead'])} |",
              f"| 30 ימים | {money(b['spend'])} | {b['impressions']:,} | {b['clicks']:,} | {b['ctr']:.2f}% | {b['leads']:.0f} | {money(b['cost_per_lead'])} |", ""]
        for s in c["adsets"]:
            L += [f"### קבוצת מודעות: {s['name']} ({s['status']}) · יעד {s['goal']} · גילאים {s['age']} · {s['geo']} · תקציב יומי {agor(s['daily_budget'])}"]
            for ad in s["ads"]:
                x = ad["last7"]
                L += [f"- {ad['name']} ({ad['status']}): 7 ימים {money(x['spend'])}, {x['clicks']} קליקים, {x['leads']:.0f} לידים, עלות לליד {money(x['cost_per_lead'])}"]
            L += [""]
    (out / "ads-latest.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
