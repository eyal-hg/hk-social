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

    out = ROOT / "reports"; out.mkdir(exist_ok=True)
    (out / "ads-latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "ads-latest.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
