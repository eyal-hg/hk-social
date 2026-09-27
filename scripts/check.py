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
print("OK")
