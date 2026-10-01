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
    params.setdefault("access_token", TOKEN)
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
    try:  # a retry after a failed run reuses the campaign it already created, never a second one
        camp = find_campaign(a["name"])
        print("reusing campaign", camp["id"], a["name"])
    except RuntimeError:
        camp = call("POST", f"{ACCT}/campaigns", name=a["name"], objective=a.get("objective", "OUTCOME_TRAFFIC"),
                    status=a.get("status", "ACTIVE"), special_ad_categories="[]", buying_type="AUCTION",
                    is_adset_budget_sharing_enabled="false")  # required since 2025; budget stays on the ad set
    t = dict(a.get("targeting") or {"geo_locations": {"countries": ["IL"]}, "age_min": 25, "age_max": 65})
    if (t.get("targeting_automation") or {}).get("advantage_audience"):
        t.pop("age_max", None)  # Advantage+ audience refuses a maximum age (error 1870188)
    mk = lambda tg: call("POST", f"{ACCT}/adsets", name=a["name"] + " · קבוצה 1", campaign_id=camp["id"],
                         daily_budget=ils(a["daily_budget_ils"]), billing_event="IMPRESSIONS",
                         optimization_goal=a.get("optimization_goal", "LANDING_PAGE_VIEWS"),
                         bid_strategy="LOWEST_COST_WITHOUT_CAP", targeting=json.dumps(tg),
                         promoted_object=json.dumps({"page_id": page_id}), status=a.get("status", "ACTIVE"))
    existing = [x for x in call("GET", f"{camp['id']}/adsets", fields="name", limit=50)["data"] if same(x["name"], a["name"] + " · קבוצה 1")]
    if existing:
        adset = existing[0]; print("reusing ad set", adset["id"])
        t = None
    try:
        adset = adset if existing else mk(t)
    except RuntimeError as e:
        if "1870188" not in str(e) or not (t.get("targeting_automation") or {}).get("advantage_audience"):
            raise
        # Advantage+ audience refuses age bounds: fall back to a plain 28-65 audience. The flag itself must
        # still be present (0), otherwise Meta answers 1870227 "Advantage audience flag required".
        t["targeting_automation"] = {"advantage_audience": 0}
        t["age_max"] = (a.get("targeting") or {}).get("age_max", 65)
        print("advantage+ audience refused; using a plain audience", t)
        adset = mk(t)
    ads = []
    have = {norm(x["name"]) for x in call("GET", f"{adset['id']}/ads", fields="name", limit=100)["data"]}
    for post_id in a["posts"]:
        if norm(post_id) in have:
            print("ad exists, skipping", post_id); continue
        p = next(d for d in (json.loads(q.read_text(encoding="utf-8")) for q in ROOT.glob("posts/**/*.json")) if d["id"] == post_id)
        # picture by public URL: the adimages upload endpoint is closed to apps in development mode (error #3)
        spec = {"page_id": page_id, "link_data": {
            "link": a["link"], "message": p["caption"], "picture": f"{IMAGE_BASE}/{post_id}.jpg",
            "name": a.get("headline", ""), "call_to_action": {"type": a.get("cta", "LEARN_MORE"), "value": {"link": a["link"]}}}}
        try:
            creative = call("POST", f"{ACCT}/adcreatives", name=post_id, object_story_spec=json.dumps(spec))
        except RuntimeError as e:
            fb_post = (p.get("results") or {}).get("facebook", "")
            if "1885183" not in str(e) or not fb_post:
                raise
            # dev-mode apps may not create ad posts; promote the already-published Page post instead
            print("creative from new post refused (dev-mode app); promoting existing post", fb_post)
            creative = call("POST", f"{ACCT}/adcreatives", name=post_id, object_story_id=fb_post,
                            call_to_action=json.dumps({"type": a.get("cta", "LEARN_MORE"), "value": {"link": a["link"]}}))
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
        add += float(a.get("daily_budget_ils") or 0)  # add_ads / pause_ads move no budget
        if a["type"] == "set_adset_budget":
            c = find_campaign(a["campaign_name"])
            if a.get("adset_name"):
                s = next(x for x in call("GET", f"{c['id']}/adsets", fields="name", limit=50)["data"] if same(x["name"], a["adset_name"]))
                ex_adsets.add(s["id"])
            else:
                ex_camps.add(c["id"])
        elif a["type"] == "revive":
            ex_camps.add(find_campaign(a["campaign_name"])["id"])
        elif a["type"] == "create_campaign":
            try:  # a retry: the campaign/ad set from the failed run already counts in the live total, don't count it twice
                ex_camps.add(find_campaign(a["name"])["id"])
            except RuntimeError:
                pass
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
            res = {"set_adset_budget": set_budget, "create_campaign": create_campaign, "revive": revive,
                   "add_ads": add_ads, "pause_ads": pause_ads, "set_targeting": set_targeting, "create_pixel": create_pixel, "clone_adset": clone_adset}[a["type"]](a)
            applied.append({"index": i, "type": a["type"], "ok": True, "at": datetime.now(ZoneInfo("Asia/Jerusalem")).isoformat(timespec="minutes"), "result": res})
            print("ok", i, a["type"], res)
        except Exception as e:  # noqa: BLE001
            failed = True
            applied.append({"index": i, "type": a["type"], "ok": False, "at": datetime.now(ZoneInfo("Asia/Jerusalem")).isoformat(timespec="minutes"), "error": str(e)[:1200]})
            print("FAILED", i, a["type"], e, file=sys.stderr)
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return not failed


def unapplied(plan):
    done = {x["index"] for x in plan.get("applied", []) if x.get("ok")}
    return [i for i in range(len(plan["actions"])) if i not in done]


def _adset(a):
    c = find_campaign(a["campaign_name"])
    return c, next(x for x in call("GET", f"{c['id']}/adsets", fields="name", limit=50)["data"] if same(x["name"], a["adset_name"]))


def page_token(page_id):
    try:
        return call("GET", page_id, fields="access_token").get("access_token") or TOKEN
    except RuntimeError:
        return TOKEN


def story_id(fb_id, page_id):
    """An unpublished (dark) photo comes back as a bare photo id; ads need the page post id PAGE_POSTID."""
    if "_" in fb_id:
        return fb_id
    ptok = page_token(page_id)
    for fields in ("page_story_id", "id"):
        try:
            r = call("GET", fb_id, fields=fields, access_token=ptok)
            if r.get("page_story_id"):
                return r["page_story_id"]
        except RuntimeError as e:
            print("lookup", fb_id, fields, "->", str(e)[:120])
    return f"{page_id}_{fb_id}"


def add_ads(a):
    """Add ads to an existing ad set from posts that are already on the Page (dark or public)."""
    c, adset = _adset(a)
    page_id = PAGES[a.get("page", "money")]
    have = {norm(x["name"]) for x in call("GET", f"{adset['id']}/ads", fields="name", limit=100)["data"]}
    ads = []
    suffix = a.get("suffix", "")  # e.g. " · b" to re-create an ad Meta flagged, next to the old one
    for post_id in a["posts"]:
        ad_name = post_id + suffix
        if norm(ad_name) in have:
            print("ad exists, skipping", ad_name); continue
        p = next(d for d in (json.loads(q.read_text(encoding="utf-8")) for q in ROOT.glob("posts/**/*.json")) if d["id"] == post_id)
        if a.get("fresh"):  # a brand-new ad post, born from the (now Live) app — not tied to a post made in development mode
            spec = {"page_id": page_id, "link_data": {
                "link": a["link"], "message": p["caption"], "picture": f"{IMAGE_BASE}/{post_id}.jpg",
                "name": a.get("headline", ""), "call_to_action": {"type": a.get("cta", "LEARN_MORE"), "value": {"link": a["link"]}}}}
            creative = call("POST", f"{ACCT}/adcreatives", name=ad_name, object_story_spec=json.dumps(spec))
        else:
            fb_post = (p.get("results") or {}).get("facebook")
            if not fb_post:
                raise RuntimeError(f"{post_id} is not on the Page yet (publish it first)")
            fb_post = story_id(fb_post, page_id)
            print(post_id, "->", fb_post)
            creative = call("POST", f"{ACCT}/adcreatives", name=ad_name, object_story_id=fb_post,
                            call_to_action=json.dumps({"type": a.get("cta", "LEARN_MORE"), "value": {"link": a["link"]}}))
        ad = call("POST", f"{ACCT}/ads", name=ad_name, adset_id=adset["id"], creative=json.dumps({"creative_id": creative["id"]}),
                  status=a.get("status", "ACTIVE"))
        ads.append({"post": post_id, "ad": ad_name, "ad_id": ad["id"], "creative_id": creative["id"]})
    return {"campaign_id": c["id"], "adset_id": adset["id"], "ads": ads}


def set_targeting(a):
    """Replace an ad set's audience. The plan carries the full targeting spec (geo, ages, flexible_spec, flag)."""
    c, adset = _adset(a)
    before = call("GET", adset["id"], fields="targeting").get("targeting")
    t = json.loads(json.dumps(a["targeting"]))
    try:
        call("POST", adset["id"], targeting=json.dumps(t))
    except RuntimeError as e:
        # job titles are the fragile part of Meta targeting (many were retired); keep the interests if they are refused
        if not any("work_positions" in fs for fs in t.get("flexible_spec", [])):
            raise
        print("targeting refused, retrying without job titles:", str(e)[:200])
        for fs in t.get("flexible_spec", []):
            fs.pop("work_positions", None)
        call("POST", adset["id"], targeting=json.dumps(t))
    est = call("GET", f"{adset['id']}/delivery_estimate", fields="estimate_mau_lower_bound,estimate_mau_upper_bound,estimate_ready").get("data", [{}])
    return {"campaign_id": c["id"], "adset_id": adset["id"], "targeting": t, "before": before, "estimate": est[0] if est else None}


def create_pixel(a):
    """Create (or reuse by name) a Meta pixel on the ad account and record its id."""
    for px in call("GET", f"{ACCT}/adspixels", fields="name,id", limit=50).get("data", []):
        if same(px["name"], a["name"]):
            print("pixel exists", px["id"]); return {"pixel_id": px["id"], "name": px["name"], "existing": True}
    px = call("POST", f"{ACCT}/adspixels", name=a["name"])
    return {"pixel_id": px["id"], "name": a["name"], "existing": False}


def clone_adset(a):
    """Duplicate an ad set (settings + its active ads) with a different audience — an A/B inside the same campaign.
    In a CBO campaign the budget is shared, so this adds no spend; otherwise daily_budget_ils is required."""
    c, src = _adset(a)
    srcd = call("GET", src["id"], fields="name,targeting,optimization_goal,billing_event,bid_strategy,promoted_object,destination_type,attribution_spec,daily_budget")
    for x in call("GET", f"{c['id']}/adsets", fields="name", limit=50)["data"]:
        if same(x["name"], a["name"]):
            raise RuntimeError("ad set already exists: " + a["name"])
    t = srcd.get("targeting") or {}
    nt = {"geo_locations": t.get("geo_locations", {"countries": ["IL"]}), "age_min": t.get("age_min", 25), "age_max": t.get("age_max", 65),
          "targeting_automation": {"advantage_audience": 0},
          "custom_audiences": [{"id": i} for i in a["custom_audiences"]]}
    if a.get("excluded_custom_audiences"):
        nt["excluded_custom_audiences"] = [{"id": i} for i in a["excluded_custom_audiences"]]
    if t.get("publisher_platforms"): nt["publisher_platforms"] = t["publisher_platforms"]
    params = dict(name=a["name"], campaign_id=c["id"], optimization_goal=srcd.get("optimization_goal"), billing_event=srcd.get("billing_event"),
                  bid_strategy=srcd.get("bid_strategy") or "LOWEST_COST_WITHOUT_CAP", targeting=json.dumps(nt), status=a.get("status", "ACTIVE"))
    if srcd.get("promoted_object"): params["promoted_object"] = json.dumps(srcd["promoted_object"])
    if srcd.get("destination_type"): params["destination_type"] = srcd["destination_type"]
    if srcd.get("attribution_spec"): params["attribution_spec"] = json.dumps(srcd["attribution_spec"])
    if not c.get("daily_budget"):  # not CBO: the new ad set needs its own budget
        params["daily_budget"] = ils(a["daily_budget_ils"])
    new = call("POST", f"{ACCT}/adsets", **params)
    ads = []
    for ad in call("GET", f"{src['id']}/ads", fields="name,status,creative", limit=100)["data"]:
        if ad.get("status") != "ACTIVE": continue
        r = call("POST", f"{ACCT}/ads", name=ad["name"] + " · " + a.get("tag", "LAL"), adset_id=new["id"],
                 creative=json.dumps({"creative_id": ad["creative"]["id"]}), status=a.get("status", "ACTIVE"))
        ads.append({"from": ad["name"], "ad_id": r["id"]})
    est = call("GET", f"{new['id']}/delivery_estimate", fields="estimate_mau_lower_bound,estimate_mau_upper_bound").get("data", [{}])
    return {"campaign_id": c["id"], "adset_id": new["id"], "targeting": nt, "ads": ads, "estimate": est[0] if est else None}


def pause_ads(a):
    c, adset = _adset(a)
    wanted, done = [norm(n) for n in a["ad_names"]], []
    for ad in call("GET", f"{adset['id']}/ads", fields="name,status", limit=100)["data"]:
        if norm(ad["name"]) in wanted and ad.get("status") != "PAUSED":
            call("POST", ad["id"], status="PAUSED"); done.append(ad["name"])
    return {"campaign_id": c["id"], "adset_id": adset["id"], "paused": done}


def main():
    if sys.argv[1] == "--auto":
        paths = [p for p in sorted((ROOT / "ads" / "plans").glob("*.json"))
                 if (d := json.loads(p.read_text(encoding="utf-8"))).get("approved") is True and unapplied(d)]  # a blocked plan is re-checked on every push
        if not paths:
            print("nothing to do: no approved plan with unapplied actions"); return
    else:
        paths = [ROOT / sys.argv[1]]
    ok = all([apply_plan(p) for p in paths])  # list(): apply every plan even if an earlier one failed
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
