"""Apply an ads plan (ads/plans/<name>.json) to the HK ad account. Every action is recorded back
into the plan file under "applied". Never touches campaigns not named in the plan.

Env: META_TOKEN (ads_management), AD_ACCOUNT_ID, PAGE_ID, STUDIO_PAGE_ID, IMAGE_BASE_URL.
Usage: ads_apply.py ads/plans/2026-09-27-x.json
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
PAGES = {"money": os.environ.get("PAGE_ID", ""), "studio": os.environ.get("STUDIO_PAGE_ID", "")}
IMAGE_BASE = os.environ.get("IMAGE_BASE_URL", "").rstrip("/")


def call(method, path, **params):
    params["access_token"] = TOKEN
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"{GRAPH}/{path}" + ("?" + data.decode() if method == "GET" else ""),
                                 data=None if method == "GET" else data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode(errors='replace')[:400]}") from None


def ils(v):
    return str(int(round(float(v) * 100)))


def find_campaign(name):
    for c in call("GET", f"{ACCT}/campaigns", fields="name,daily_budget,lifetime_budget,effective_status", limit=100).get("data", []):
        if c["name"].strip() == name.strip():
            return c
    raise RuntimeError(f"campaign not found: {name}")


def set_budget(a):
    c = find_campaign(a["campaign_name"])
    if c.get("daily_budget"):  # campaign-level budget
        call("POST", c["id"], daily_budget=ils(a["daily_budget_ils"]))
        return {"campaign_id": c["id"], "level": "campaign", "daily_budget_ils": a["daily_budget_ils"]}
    adsets = [s for s in call("GET", f"{c['id']}/adsets", fields="name,daily_budget,effective_status", limit=50).get("data", [])
              if s.get("effective_status") in ("ACTIVE", "PAUSED", "CAMPAIGN_PAUSED")]
    live = [s for s in adsets if s.get("effective_status") == "ACTIVE"] or adsets[:1]
    per = float(a["daily_budget_ils"]) / max(len(live), 1)
    done = []
    for s in live:
        call("POST", s["id"], daily_budget=ils(per))
        done.append({"adset_id": s["id"], "name": s["name"], "daily_budget_ils": per})
    return {"campaign_id": c["id"], "level": "adset", "adsets": done}


def create_campaign(a):
    page_id = PAGES[a["page"]]
    if not page_id:
        raise RuntimeError("no page id for " + a["page"])
    camp = call("POST", f"{ACCT}/campaigns", name=a["name"], objective=a.get("objective", "OUTCOME_TRAFFIC"),
                status=a.get("status", "ACTIVE"), special_ad_categories="[]", buying_type="AUCTION")
    t = a.get("targeting") or {"geo_locations": {"countries": ["IL"]}, "age_min": 25, "age_max": 65}
    adset = call("POST", f"{ACCT}/adsets", name=a["name"] + " · קבוצה 1", campaign_id=camp["id"],
                 daily_budget=ils(a["daily_budget_ils"]), billing_event="IMPRESSIONS",
                 optimization_goal=a.get("optimization_goal", "LANDING_PAGE_VIEWS"),
                 bid_strategy="LOWEST_COST_WITHOUT_CAP", targeting=json.dumps(t),
                 promoted_object=json.dumps({"page_id": page_id}), status=a.get("status", "ACTIVE"))
    ads = []
    for post_id in a["posts"]:
        p = next(d for d in (json.loads(q.read_text(encoding="utf-8")) for q in ROOT.glob("posts/**/*.json")) if d["id"] == post_id)
        img = call("POST", f"{ACCT}/adimages", url=f"{IMAGE_BASE}/{post_id}.jpg")
        image_hash = next(iter(img["images"].values()))["hash"]
        creative = call("POST", f"{ACCT}/adcreatives", name=post_id,
                        object_story_spec=json.dumps({"page_id": page_id, "link_data": {
                            "link": a["link"], "message": p["caption"], "image_hash": image_hash,
                            "name": a.get("headline", ""), "call_to_action": {"type": a.get("cta", "LEARN_MORE"), "value": {"link": a["link"]}}}}))
        ad = call("POST", f"{ACCT}/ads", name=post_id, adset_id=adset["id"], creative=json.dumps({"creative_id": creative["id"]}),
                  status=a.get("status", "ACTIVE"))
        ads.append({"post": post_id, "ad_id": ad["id"], "creative_id": creative["id"]})
    return {"campaign_id": camp["id"], "adset_id": adset["id"], "ads": ads}


def main():
    plan_path = ROOT / sys.argv[1]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    applied = plan.setdefault("applied", [])
    failed = False
    for i, a in enumerate(plan["actions"]):
        if any(x.get("index") == i and x.get("ok") for x in applied):
            print("skip (done)", i, a["type"]); continue
        try:
            res = {"set_adset_budget": set_budget, "create_campaign": create_campaign}[a["type"]](a)
            applied.append({"index": i, "type": a["type"], "ok": True, "at": datetime.now(ZoneInfo("Asia/Jerusalem")).isoformat(timespec="minutes"), "result": res})
            print("ok", i, a["type"], res)
        except Exception as e:  # noqa: BLE001
            failed = True
            applied.append({"index": i, "type": a["type"], "ok": False, "at": datetime.now(ZoneInfo("Asia/Jerusalem")).isoformat(timespec="minutes"), "error": str(e)[:500]})
            print("FAILED", i, a["type"], e, file=sys.stderr)
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
