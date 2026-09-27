"""Apply an ads plan (ads/plans/<name>.json) to the HK ad account. Every action is recorded back
into the plan file under "applied". Never touches campaigns not named in the plan.

Env: META_TOKEN (ads_management), AD_ACCOUNT_ID, PAGE_ID, STUDIO_PAGE_ID, IMAGE_BASE_URL.
Usage: ads_apply.py ads/plans/2026-09-27-x.json     one plan
       ads_apply.py --auto                          every plan with "approved": true that still has unapplied actions

Guard: ads/limits.json {"max_daily_total_ils": N}. Before touching anything the script projects the
account's total daily budget after the plan; if it would exceed N the plan is marked "blocked" and
nothing is applied. Raising N is a deliberate edit by a human, not something a plan can do.
"""
import json
import os
import re
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


def norm(name):
    """Meta names carry invisible RTL marks and stray spaces; compare without them."""
    return re.sub(r"\s+", " ", re.sub(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", name or "")).strip()


def same(a, b):
    return norm(a) == norm(b)


def ils(v):
    return str(int(round(float(v) * 100)))


def find_campaign(name):
    for c in call("GET", f"{ACCT}/campaigns", fields="name,daily_budget,lifetime_budget,effective_status", limit=100).get("data", []):
        if same(c["name"], name):
            return c
    raise RuntimeError(f"campaign not found: {name}")


def set_budget(a):
    c = find_campaign(a["campaign_name"])
    if a.get("adset_name"):  # one named ad set only; the others are left as they are
        s = next(x for x in call("GET", f"{c['id']}/adsets", fields="name", limit=50)["data"] if same(x["name"], a["adset_name"]))
        call("POST", s["id"], daily_budget=ils(a["daily_budget_ils"]))
        return {"campaign_id": c["id"], "level": "adset", "adsets": [{"adset_id": s["id"], "name": s["name"], "daily_budget_ils": a["daily_budget_ils"]}]}
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


def revive(a):
    """Un-pause one campaign with exactly one ad set and the named ads inside it; everything else in it stays paused."""
    c = find_campaign(a["campaign_name"])
    adsets = call("GET", f"{c['id']}/adsets", fields="name,status,daily_budget", limit=50)["data"]
    keep = next(s for s in adsets if same(s["name"], a["adset_name"]))
    for s in adsets:
        if s["id"] != keep["id"] and s.get("status") != "PAUSED":
            call("POST", s["id"], status="PAUSED")
    ads = call("GET", f"{keep['id']}/ads", fields="name,status", limit=100)["data"]
    wanted = [norm(n) for n in a["ad_names"]]
    on, off = [], []
    for ad in ads:
        if norm(ad["name"]) in wanted:
            call("POST", ad["id"], status="ACTIVE"); on.append(ad["name"])
        elif ad.get("status") != "PAUSED":
            call("POST", ad["id"], status="PAUSED"); off.append(ad["name"])
    if not on:
        raise RuntimeError("none of the ads found: " + ", ".join(wanted))
    if c.get("daily_budget"):  # campaign budget (CBO): the budget lives on the campaign
        call("POST", c["id"], daily_budget=ils(a["daily_budget_ils"]), status="ACTIVE")
        call("POST", keep["id"], status="ACTIVE")
    else:
        call("POST", keep["id"], daily_budget=ils(a["daily_budget_ils"]), status="ACTIVE")
        call("POST", c["id"], status="ACTIVE")
    return {"campaign_id": c["id"], "adset_id": keep["id"], "ads_on": on, "ads_paused_now": off, "daily_budget_ils": a["daily_budget_ils"]}


def daily_total(exclude_adsets=(), exclude_campaigns=()):
    """Sum of daily budgets currently able to spend: active CBO campaigns + active ad sets in non-CBO campaigns."""
    camps = {c["id"]: c for c in call("GET", f"{ACCT}/campaigns", fields="daily_budget,effective_status", limit=200)["data"]}
    total = sum(int(c.get("daily_budget") or 0) for cid, c in camps.items()
                if c.get("effective_status") == "ACTIVE" and cid not in exclude_campaigns)
    for s in call("GET", f"{ACCT}/adsets", fields="campaign_id,daily_budget,effective_status", limit=500)["data"]:
        if s.get("effective_status") == "ACTIVE" and s["id"] not in exclude_adsets and s["campaign_id"] not in exclude_campaigns \
                and not camps.get(s["campaign_id"], {}).get("daily_budget"):
            total += int(s.get("daily_budget") or 0)
    return total / 100


def projected_total(plan):
    """Account daily total after the plan's still-unapplied actions, in ILS."""
    done = {x["index"] for x in plan.get("applied", []) if x.get("ok")}
    pending = [a for i, a in enumerate(plan["actions"]) if i not in done]
    ex_adsets, ex_camps, add = set(), set(), 0.0
    for a in pending:
        add += float(a["daily_budget_ils"])
        if a["type"] == "set_adset_budget":
            c = find_campaign(a["campaign_name"])
            if a.get("adset_name"):
                s = next(x for x in call("GET", f"{c['id']}/adsets", fields="name", limit=50)["data"] if same(x["name"], a["adset_name"]))
                ex_adsets.add(s["id"])
            else:
                ex_camps.add(c["id"])
        elif a["type"] == "revive":
            ex_camps.add(find_campaign(a["campaign_name"])["id"])
    return daily_total(ex_adsets, ex_camps) + add


def apply_plan(plan_path):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    applied = plan.setdefault("applied", [])
    limits = json.loads((ROOT / "ads" / "limits.json").read_text(encoding="utf-8"))
    cap = float(limits["max_daily_total_ils"])
    total = projected_total(plan)
    if total > cap:
        plan["blocked"] = {"at": datetime.now(ZoneInfo("Asia/Jerusalem")).isoformat(timespec="minutes"),
                           "reason": f"projected daily total {total:.0f} ILS > cap {cap:.0f} ILS (ads/limits.json)"}
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("BLOCKED", plan_path.name, plan["blocked"]["reason"], file=sys.stderr)
        return False
    plan.pop("blocked", None)
    print(f"{plan_path.name}: projected daily total {total:.0f} ILS (cap {cap:.0f})")
    failed = False
    for i, a in enumerate(plan["actions"]):
        if any(x.get("index") == i and x.get("ok") for x in applied):
            print("skip (done)", i, a["type"]); continue
        try:
            res = {"set_adset_budget": set_budget, "create_campaign": create_campaign, "revive": revive}[a["type"]](a)
            applied.append({"index": i, "type": a["type"], "ok": True, "at": datetime.now(ZoneInfo("Asia/Jerusalem")).isoformat(timespec="minutes"), "result": res})
            print("ok", i, a["type"], res)
        except Exception as e:  # noqa: BLE001
            failed = True
            applied.append({"index": i, "type": a["type"], "ok": False, "at": datetime.now(ZoneInfo("Asia/Jerusalem")).isoformat(timespec="minutes"), "error": str(e)[:500]})
            print("FAILED", i, a["type"], e, file=sys.stderr)
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return not failed


def unapplied(plan):
    done = {x["index"] for x in plan.get("applied", []) if x.get("ok")}
    return [i for i in range(len(plan["actions"])) if i not in done]


def main():
    if sys.argv[1] == "--auto":
        paths = [p for p in sorted((ROOT / "ads" / "plans").glob("*.json"))
                 if (d := json.loads(p.read_text(encoding="utf-8"))).get("approved") is True and unapplied(d) and not d.get("blocked")]
        if not paths:
            print("nothing to do: no approved plan with unapplied actions"); return
    else:
        paths = [ROOT / sys.argv[1]]
    ok = all([apply_plan(p) for p in paths])  # list(): apply every plan even if an earlier one failed
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
