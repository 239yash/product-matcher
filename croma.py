"""Real Croma scraper.

Reverse-engineered from their SPA JS bundle (main.*.chunk.js). The public
browser hits:

    GET https://api.croma.com/searchservices/v1/search
        ?currentPage=0
        &query=<q>:relevance
        &fields=FULL
        &channel=WEB
        &channelCode=<pincode, we default to 400001>
        &spellOpt=DEFAULT

with header `Ocp-Apim-Subscription-Key: <OCP_APIM_SUBSCRIPTION_KEY>`.

The key is literally embedded in the public bundle — no secret. The API responds
with JSON including a `products` array; each item has `name`, `manufacturer`,
`url` (relative slug), `price.priceType`, and `stockFlag` (a list of store IDs
where the SKU is in stock — empty list = out of stock).

TLS fingerprint via curl_cffi (`impersonate="chrome120"`) gets past Akamai.
"""
import re
import urllib.parse
from typing import Optional

from curl_cffi import requests

OCP_KEY = "1131858141634e2abe2efb2b3a2a2a5d"
DEFAULT_PINCODE = "400001"  # Mumbai, used for stock lookups

SEARCH_URL = "https://api.croma.com/searchservices/v1/search"
HEADERS = {
    "Ocp-Apim-Subscription-Key": OCP_KEY,
    "Accept": "application/json",
    "Origin": "https://www.croma.com",
    "Referer": "https://www.croma.com/",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())


def _match_product(target: dict, candidate_name: str, candidate_brand: str) -> bool:
    name_norm = _norm(candidate_name)
    brand_norm = _norm(candidate_brand)
    t_brand = _norm(target["brand"])
    t_tokens = [_norm(w) for w in target["model"].split() if len(w) > 1]
    attr = target["key_attr"]

    if t_brand and t_brand not in brand_norm and t_brand not in name_norm:
        return False
    if t_tokens:
        numeric = [w for w in t_tokens if any(ch.isdigit() for ch in w)]
        alpha   = [w for w in t_tokens if not any(ch.isdigit() for ch in w)]
        for w in numeric:
            if w not in name_norm:
                return False
        if alpha:
            hits = sum(1 for w in alpha if w in name_norm)
            if hits < max(1, len(alpha) // 2):
                return False
    if attr:
        attr_tokens = [_norm(w) for w in re.split(r"\s+", attr) if w and len(w) > 1]
        if attr_tokens and not any(w in name_norm for w in attr_tokens):
            return False
    return True


def find_on_croma(product: dict) -> dict:
    query = f'{product["brand"]} {product["model"]} {product["key_attr"]}'.strip()
    q_encoded = urllib.parse.quote(query) + "%3Arelevance"
    url = (
        f"{SEARCH_URL}?currentPage=0&query={q_encoded}"
        f"&fields=FULL&channel=WEB&channelCode={DEFAULT_PINCODE}&spellOpt=DEFAULT"
    )

    try:
        r = requests.get(url, impersonate="chrome120", timeout=20, headers=HEADERS)
    except Exception as e:
        return _not_listed(f"Croma fetch failed: {e}")

    if r.status_code != 200:
        return _not_listed(f"Croma API returned {r.status_code}")

    try:
        data = r.json()
    except Exception as e:
        return _not_listed(f"Croma JSON parse failed: {e}")

    products = data.get("products") or []
    if not products:
        return _not_listed("no Croma search results")

    for p in products[:12]:
        name = p.get("name") or ""
        brand = p.get("manufacturer") or ""
        if not _match_product(product, name, brand):
            continue

        stock_flag = p.get("stockFlag") or []
        price_type = (p.get("price") or {}).get("priceType") or ""
        in_stock = bool(stock_flag) and price_type.upper() == "BUY"
        status = "in_stock" if in_stock else "out_of_stock"

        slug = p.get("url", "")
        product_url = f"https://www.croma.com{slug}" if slug else ""

        return {
            "platform": "Croma",
            "status": status,
            "url": product_url,
            "matched_title": name[:180],
            "reasoning": f"API match; stockFlag={len(stock_flag)} stores, priceType={price_type}",
        }

    return _not_listed("no Croma candidate matched brand+model+attr")


def _not_listed(reason: str) -> dict:
    return {"platform": "Croma", "status": "not_listed", "url": "", "matched_title": "", "reasoning": reason}
