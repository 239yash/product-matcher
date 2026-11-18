"""Real scrapers for Amazon India, Flipkart, Myntra.

Uses curl_cffi (Chrome TLS fingerprint impersonation). No proxies.

Croma lives in a separate file because Akamai Bot Manager blocks direct
scraping, so it needs either a residential proxy or Claude as a shim.
"""
import json
import re
import urllib.parse
from typing import Optional

from curl_cffi import requests

IMPERSONATE = "chrome120"
TIMEOUT = 20

STOCK_IN = ["add to cart", "buy now", "add to bag", "add to basket", "go to cart"]
# strong = definitely not purchasable; weak = possibly only a variant
STOCK_OUT_STRONG = ["currently unavailable", "temporarily unavailable", "coming soon",
                    "we don't sell this product"]
STOCK_OUT_WEAK = ["out of stock", "sold out", "notify me"]


def _get(url: str, **kwargs) -> Optional[requests.Response]:
    try:
        r = requests.get(url, impersonate=IMPERSONATE, timeout=TIMEOUT, **kwargs)
        if r.status_code == 200:
            return r
    except Exception:
        pass
    return None


# -------- Amazon India --------

def extract_amazon_product(url: str) -> dict:
    r = _get(url)
    if not r:
        raise RuntimeError("Amazon fetch failed")
    html = r.text

    title_m = re.search(r'id="productTitle"[^>]*>\s*([^<]+)', html)
    if not title_m:
        raise RuntimeError("No product title on Amazon page (possibly blocked)")
    title = title_m.group(1).strip()

    brand_m = re.search(r'id="bylineInfo"[^>]*>\s*([^<]+)', html)
    brand_raw = brand_m.group(1).strip() if brand_m else ""
    brand = re.sub(r"(Visit the|Brand:|Store|,)", "", brand_raw, flags=re.I).strip()
    if not brand:
        brand = _guess_brand(title)

    category = _detect_category(title)
    key_attr = _extract_key_attr(title, category)
    model = _guess_model(title, brand)

    return {
        "brand": brand,
        "model": model,
        "category": category,
        "key_attr": key_attr,
        "title": title[:220],
    }


def _guess_brand(title: str) -> str:
    cleaned = re.sub(r"^\(.*?\)\s*", "", title).strip()
    return cleaned.split()[0] if cleaned else ""


def _guess_model(title: str, brand: str) -> str:
    cleaned = title
    if brand:
        cleaned = re.sub(rf"\b{re.escape(brand)}\b", "", cleaned, flags=re.I).strip()
    # take 2-4 meaningful tokens
    tokens = [w for w in cleaned.split() if len(w) > 1 and not w.startswith("(")][:4]
    return " ".join(tokens)


def _detect_category(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["tv", "television", "smart tv", "led tv", "oled", "qled"]):
        return "television"
    if any(k in t for k in ["smartphone", "mobile", "iphone", "android", "galaxy", "redmi",
                             "oneplus", "pixel", "5g smartphone", " 5g ", " 4g "]):
        return "smartphone"
    if any(k in t for k in ["sneaker", "running shoe", "trainers", "sneakers"]):
        return "sneaker"
    if any(k in t for k in ["t-shirt", "tshirt", "polo", "jersey"]):
        return "apparel"
    return "unknown"


def _extract_key_attr(title: str, category: str) -> str:
    if category == "smartphone":
        # explicit RAM marker
        ram = re.search(r"(\d+)\s*GB\s*RAM", title, re.I)
        # explicit storage marker
        stor = re.search(r"(\d+)\s*(GB|TB)\s*(?:Storage|ROM|Internal|Memory)", title, re.I)
        # collect any "Nx GB/TB" pairs in order
        all_pairs = [(m.group(1), m.group(2)) for m in re.finditer(r"(\d+)\s*(GB|TB)", title, re.I)]
        if not ram and len(all_pairs) >= 2:
            # convention: first pair is RAM, second is storage
            ram_val, _ = all_pairs[0]
            ram = type("M", (), {"group": lambda self, i, v=ram_val: v})()
        if not stor:
            ram_num = ram.group(1) if ram else None
            for num, unit in all_pairs:
                if num != ram_num:
                    stor = type("M", (), {"group": lambda self, i, n=num, u=unit: n if i == 1 else u})()
                    break
        parts = []
        if ram: parts.append(f"{ram.group(1)}GB RAM")
        if stor: parts.append(f"{stor.group(1)}{stor.group(2)}")
        return " ".join(parts)
    if category == "television":
        screen = re.search(r"(\d{2,3})\s*(?:inch|\"|cm)", title, re.I)
        return f"{screen.group(1)} inch" if screen else ""
    colours = ["black", "white", "red", "blue", "green", "grey", "gray", "navy",
               "pink", "yellow", "orange", "brown", "beige", "olive", "maroon", "purple",
               "titanium", "silver"]
    for c in colours:
        if re.search(rf"\b{c}\b", title, re.I):
            return c.capitalize()
    return ""


# -------- Flipkart --------

def find_on_flipkart(product: dict) -> dict:
    query = urllib.parse.quote(f'{product["brand"]} {product["model"]} {product["key_attr"]}')
    search_url = f"https://www.flipkart.com/search?q={query}"
    r = _get(search_url)
    if not r:
        return _not_listed("Flipkart", "search blocked")

    # Flipkart search results: /<slug>/p/<itm>
    product_links = re.findall(r'href="(/[^"#?]+/p/[^"&]+)(?:&amp;|\?|")', r.text)
    product_links = list(dict.fromkeys(product_links))  # dedupe
    if not product_links:
        return _not_listed("Flipkart", "no product links in search")

    for link in product_links[:5]:
        page_url = "https://www.flipkart.com" + link.replace("&amp;", "&")
        r2 = _get(page_url)
        if not r2:
            continue
        title_m = re.search(r'<title>([^<]+)</title>', r2.text)
        page_title = title_m.group(1).strip() if title_m else ""
        if _matches(product, page_title):
            status = _detect_stock(r2.text)
            return {
                "platform": "Flipkart",
                "status": status,
                "url": page_url,
                "matched_title": page_title[:150],
                "reasoning": "title matched brand+model+attr",
            }
    return _not_listed("Flipkart", "no candidate matched brand+model+attr")


# -------- Myntra --------

def find_on_myntra(product: dict) -> dict:
    # myntra treats "-" as a separator in URL searches
    q = f'{product["brand"]} {product["model"]}'.strip()
    search_url = f"https://www.myntra.com/{urllib.parse.quote(q.replace(' ', '-'))}"
    r = _get(search_url)
    if not r:
        return _not_listed("Myntra", "search blocked")

    # parse the embedded JSON window.__myx
    idx = r.text.find("window.__myx")
    if idx < 0:
        return _not_listed("Myntra", "no hydration JSON")
    eq = r.text.find("=", idx)
    start = r.text.find("{", eq)
    try:
        data, _ = json.JSONDecoder().raw_decode(r.text[start:])
    except Exception:
        return _not_listed("Myntra", "failed to parse JSON")

    products = (data.get("searchData", {}).get("results", {}).get("products", [])) or []
    if not products:
        return _not_listed("Myntra", "no search results")

    target_colour = product["key_attr"].lower()
    target_brand = product["brand"].lower()
    target_model_tokens = [w.lower() for w in product["model"].split() if len(w) > 2]

    for p in products[:10]:
        name = (p.get("productName") or "").lower()
        brand = (p.get("brand") or "").lower()
        if target_brand and target_brand not in brand and target_brand not in name:
            continue
        if target_model_tokens and not any(w in name for w in target_model_tokens):
            continue
        if target_colour and target_colour not in name:
            continue
        slug = p.get("landingPageUrl", "")
        url = f"https://www.myntra.com/{slug}" if slug else ""
        # myntra listing in search already confirms it's purchasable; detailed stock in product page
        status = "in_stock"
        if url:
            r2 = _get(url)
            if r2:
                status = _detect_stock(r2.text)
        return {
            "platform": "Myntra",
            "status": status,
            "url": url,
            "matched_title": p.get("productName", "")[:150],
            "reasoning": "name+brand+colour matched",
        }
    return _not_listed("Myntra", "no candidate matched brand+model+colour")


# -------- shared helpers --------

def _norm(s: str) -> str:
    """Lowercase and collapse all whitespace so '256 GB' == '256GB'."""
    return re.sub(r"\s+", "", s.lower())


def _matches(product: dict, page_title: str) -> bool:
    t_norm = _norm(page_title)
    brand = _norm(product["brand"])
    model_tokens = [_norm(w) for w in product["model"].split() if len(w) > 1]
    attr = product["key_attr"]
    if brand and brand not in t_norm:
        return False
    if model_tokens:
        # Tokens containing a digit are model identifiers (S24, CE3, 2024, etc.)
        # and MUST be present. Alpha-only tokens are looser and half need to hit.
        numeric = [w for w in model_tokens if any(ch.isdigit() for ch in w)]
        alpha   = [w for w in model_tokens if not any(ch.isdigit() for ch in w)]
        for w in numeric:
            if w not in t_norm:
                return False
        if alpha:
            hits = sum(1 for w in alpha if w in t_norm)
            if hits < max(1, len(alpha) // 2):
                return False
    if attr:
        attr_tokens = [_norm(w) for w in re.split(r"\s+", attr) if w and len(w) > 1]
        if attr_tokens and not any(w in t_norm for w in attr_tokens):
            return False
    return True


def _detect_stock(html: str) -> str:
    low = html.lower()
    has_buy = any(kw in low for kw in STOCK_IN)
    # Strong signals always win
    if any(kw in low for kw in STOCK_OUT_STRONG):
        return "out_of_stock"
    # If a buy button is present, treat as in_stock regardless of weak OOS hints
    # (weak hints often come from variant/related-product UI, not the main product).
    if has_buy:
        return "in_stock"
    if any(kw in low for kw in STOCK_OUT_WEAK):
        return "out_of_stock"
    return "in_stock"


def _not_listed(platform: str, reason: str) -> dict:
    return {"platform": platform, "status": "not_listed", "url": "", "matched_title": "", "reasoning": reason}
