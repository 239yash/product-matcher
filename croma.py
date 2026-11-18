"""Croma scraper via their internal product-search API.

Discovered by reading https://www.croma.com/static/js/main.*.chunk.js:
  - host:   https://api.croma.com
  - path:   /searchservices/v1/search
  - key:    Ocp-Apim-Subscription-Key is hardcoded in the public bundle
  - sort:   the query value needs a `:relevance` suffix
  - channel/pincode: `channel=WEB&channelCode=<pincode>&spellOpt=DEFAULT`

Each product in the response has `name`, `manufacturer`, `url`, `price.priceType`
and `stockFlag` (a list of store codes where the SKU is in stock — empty = OOS).

TLS fingerprint via curl_cffi gets past the Akamai edge.
"""
import urllib.parse
from typing import Optional

from curl_cffi import requests

from scraper import matches, _queries_for  # reuse the matcher

OCP_KEY = "1131858141634e2abe2efb2b3a2a2a5d"
DEFAULT_PINCODE = "400001"  # Mumbai; used only for stock lookup

SEARCH_URL = "https://api.croma.com/searchservices/v1/search"
HEADERS = {
    "Ocp-Apim-Subscription-Key": OCP_KEY,
    "Accept": "application/json",
    "Origin": "https://www.croma.com",
    "Referer": "https://www.croma.com/",
}


def _call(query: str) -> Optional[dict]:
    q = urllib.parse.quote(query) + "%3Arelevance"
    url = (
        f"{SEARCH_URL}?currentPage=0&query={q}"
        f"&fields=FULL&channel=WEB&channelCode={DEFAULT_PINCODE}&spellOpt=DEFAULT"
    )
    try:
        r = requests.get(url, impersonate="chrome120", timeout=20, headers=HEADERS)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except Exception:
        return None


def find_on_croma(product: dict) -> dict:
    for query in _queries_for(product):
        data = _call(query)
        if not data:
            continue
        products = data.get("products") or []
        for p in products[:15]:
            name = p.get("name") or ""
            brand = p.get("manufacturer") or ""
            full = f"{brand} {name}"
            if not matches(product, full):
                continue
            stock_flag = p.get("stockFlag") or []
            price_type = ((p.get("price") or {}).get("priceType") or "").upper()
            in_stock = bool(stock_flag) and price_type == "BUY"
            status = "in_stock" if in_stock else "out_of_stock"
            slug = p.get("url", "")
            return {
                "platform": "Croma",
                "status": status,
                "url": f"https://www.croma.com{slug}" if slug else "",
                "matched_title": name[:180],
                "reasoning": f"API match via query: {query} ({len(stock_flag)} stores)",
            }
    return {
        "platform": "Croma",
        "status": "not_listed",
        "url": "",
        "matched_title": "",
        "reasoning": "no candidate matched any query",
    }
