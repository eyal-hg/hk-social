"""Verify the Meta token can reach the Page and the Instagram account. Posts nothing."""
import os
import sys

sys.argv.append("--dry-run")
import publish  # noqa: E402

PAGE_ID = publish.PAGES["money"]["page"]; IG_ID = publish.PAGES["money"]["ig"]
ptoken = publish.page_token(PAGE_ID)
page = publish.call("GET", PAGE_ID, fields="name,instagram_business_account", access_token=ptoken)
ig = publish.call("GET", IG_ID, fields="username", access_token=ptoken)
print("page:", page.get("name"), "| linked IG id:", page.get("instagram_business_account", {}).get("id"))
print("instagram:", ig.get("username"))
if page.get("instagram_business_account", {}).get("id") != IG_ID:
    sys.exit("IG account linked to the page does not match IG_ID")
studio = publish.PAGES["studio"]["page"]
names = [a.get("name") for a in publish.call("GET", "me/accounts", fields="name", limit="100", access_token=publish.TOKEN).get("data", [])]
print("pages the saved token can reach:", names)
if studio:
    try:
        st = publish.call("GET", studio, fields="name,access_token", access_token=publish.TOKEN)
        print("studio page:", st.get("name"), "| token ok:", bool(st.get("access_token")))
        sig = publish.PAGES["studio"]["ig"]
        if sig:
            linked = publish.call("GET", studio, fields="instagram_business_account", access_token=st["access_token"]).get("instagram_business_account", {}).get("id")
            ig2 = publish.call("GET", sig, fields="username", access_token=st["access_token"])
            print("studio instagram:", ig2.get("username"), "| linked to page:", linked == sig)
            if linked != sig:
                sys.exit("STUDIO IG not linked to the studio page (linked id: %s)" % linked)
    except RuntimeError as e:
        print("STUDIO NOT REACHABLE:", str(e)[:200])
print("OK")
