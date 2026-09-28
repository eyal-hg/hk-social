"""Read-only: look up Meta targeting options (interests, job titles, employers) for a list of terms and
write ads/targeting-options.json with ids + audience sizes, so a plan can name a precise audience.
Env: META_TOKEN, AD_ACCOUNT_ID.  Usage: ads_search.py
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPH = "https://graph.facebook.com/v21.0"
TOKEN = os.environ["META_TOKEN"]
ACCT = "act_" + os.environ["AD_ACCOUNT_ID"].removeprefix("act_")

TERMS = {
    "adinterest": ["Business consultant", "Management consulting", "Consulting", "Financial adviser", "Financial planner",
                   "Accounting", "Accountant", "Certified Public Accountant", "Bookkeeping", "Tax advisor", "Chief financial officer",
                   "Business coaching", "Business development", "Small business", "Cash flow", "Financial analysis", "Corporate finance",
                   "יועץ עסקי", "רואה חשבון", "ייעוץ עסקי", "יועץ פיננסי", "הנהלת חשבונות"],
    "adworkposition": ["Business Consultant", "Financial Consultant", "Financial Advisor", "Accountant", "CPA", "Bookkeeper",
                       "Management Consultant", "Business Coach", "Tax Consultant", "CFO", "Chief Financial Officer", "Controller",
                       "יועץ עסקי", "רואה חשבון", "יועץ פיננסי", "מנהל כספים", "יועץ מס"],
    "adworkemployer": ["Deloitte", "EY", "KPMG", "PwC", "BDO", "Grant Thornton"],
    "adeducationmajor": ["Accounting", "Economics", "Finance", "Business administration", "Business management", "Taxation", "חשבונאות", "כלכלה"],
}


def get(path, **params):
    params["access_token"] = TOKEN
    req = urllib.request.Request(f"{GRAPH}/{path}?{urllib.parse.urlencode(params)}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print(f"{path} {params.get('q')}: {e.code} {e.read().decode(errors='replace')[:200]}", file=sys.stderr)
        return {}


def main():
    out = {}
    for kind, terms in TERMS.items():
        rows = {}
        for q in terms:
            for r in get("search", type=kind, q=q, limit=8, locale="en_US").get("data", []):
                rows[r["id"]] = {"id": r["id"], "name": r.get("name"), "path": r.get("path"),
                                 "audience_lower": r.get("audience_size_lower_bound"), "audience_upper": r.get("audience_size_upper_bound"), "q": q}
        out[kind] = sorted(rows.values(), key=lambda x: -(x["audience_lower"] or 0))
        print(f"\n## {kind}: {len(rows)}")
        for x in out[kind]:
            print(f"- {x['id']}  {x['name']}  ({x['audience_lower'] or '?'}–{x['audience_upper'] or '?'})  [{' > '.join(x['path'] or [])}]  ← {x['q']}")
    # behaviors are a fixed catalogue, not searchable: list the business-related ones
    beh = get(f"{ACCT}/adTargetingCategory", **{"class": "behaviors"}).get("data", [])
    beh = [b for b in beh if any(k in (b.get("name", "") + " ".join(b.get("path", []))).lower() for k in ("business", "admin", "owner", "engaged shopper", "professional"))]
    out["behaviors"] = beh
    print(f"\n## behaviors (business-related): {len(beh)}")
    for b in beh:
        print(f"- {b['id']}  {b['name']}  ({b.get('audience_size_lower_bound')}–{b.get('audience_size_upper_bound')})  [{' > '.join(b.get('path') or [])}]")

    def resolve(node):
        """{"type": "adeducationmajor", "q": "Accounting"} inside a variant -> the top search hit {id, name}."""
        if isinstance(node, dict) and "q" in node and "type" in node:
            hit = (get("search", type=node["type"], q=node["q"], limit=3, locale="en_US").get("data") or [{}])[0]
            return {"id": hit.get("id"), "name": hit.get("name")} if hit.get("id") else None
        if isinstance(node, dict):
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [x for x in (resolve(v) for v in node) if x is not None]
        return node

    # IL reach estimates for candidate audiences (read-only, nothing is changed on the ad set)
    vf = ROOT / "ads" / "audience-variants.json"
    if vf.exists():
        variants = json.loads(vf.read_text(encoding="utf-8"))
        for v in variants:
            v["targeting"] = resolve(v["targeting"])
        print("\n## audience estimates (monthly active, IL)")
        for v in variants:
            r = get(f"{ACCT}/delivery_estimate", targeting_spec=json.dumps(v["targeting"]), optimization_goal="LANDING_PAGE_VIEWS").get("data", [{}])
            r = r[0] if r else {}
            v["estimate"] = {k: r.get(k) for k in ("estimate_mau_lower_bound", "estimate_mau_upper_bound", "estimate_ready")}
            print(f"- {v['name']}: {r.get('estimate_mau_lower_bound')}–{r.get('estimate_mau_upper_bound')}")
        vf.write_text(json.dumps(variants, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (ROOT / "ads").mkdir(exist_ok=True)
    (ROOT / "ads" / "targeting-options.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
