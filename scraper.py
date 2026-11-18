"""Scrapers for Amazon India, Flipkart, Myntra.

Uses curl_cffi (Chrome TLS fingerprint impersonation) + Amazon's own
structured data (po-* feature bullets, breadcrumb, detail bullets) so
extraction doesn't depend on brittle title regexes.
"""
import html as html_lib
import json
import re
import urllib.parse
from typing import Optional

from curl_cffi import requests

IMPERSONATE = "chrome120"
TIMEOUT = 10

STOCK_IN = ["add to cart", "buy now", "add to bag", "add to basket", "go to cart"]
STOCK_OUT_STRONG = ["currently unavailable", "temporarily unavailable", "coming soon",
                    "we don't sell this product"]
STOCK_OUT_WEAK = ["out of stock", "sold out", "notify me"]

# Tokens that carry no product-matching signal in fashion titles.
FASHION_NOISE = {
    "men", "mens", "man", "women", "womens", "woman", "unisex", "kids", "boy", "girl",
    "cotton", "polyester", "blend", "silk", "linen", "nylon", "spandex",
    "solid", "printed", "striped", "slim", "regular", "fit", "fitted",
    "premium", "soft", "pack", "piece", "round", "neck", "collar",
    "short", "full", "half", "long", "sleeve", "sleeves", "sleeveless",
    "with", "side", "branding", "of", "size", "the", "a", "an", "and", "or", "for",
    "wear", "wears", "worn", "fits", "fitting", "designed", "built", "made",
    "x", "by", "signature", "style", "stylish", "mid", "high", "low",
    "lightweight", "breathable", "sports", "casual", "formal", "classic",
    "running", "training", "gym", "performance", "athleisure",
    "shoes", "shoe", "sneaker", "sneakers", "trainers",
    "jersey", "tshirt", "t-shirt", "polo", "shirt", "tees", "tee",
    "ikd", "jsy", "rn",
}

# Common colour base words — used to decide if a token is a colour.
COLOUR_WORDS = {
    "black", "white", "red", "blue", "green", "grey", "gray", "navy", "pink",
    "yellow", "orange", "brown", "beige", "olive", "maroon", "purple",
    "titanium", "silver", "gold", "copper", "bronze", "ivory", "cream",
    "iceblue", "violet", "indigo", "teal", "turquoise", "burgundy", "khaki",
    "charcoal", "sand", "mint", "aqua", "coral", "ruby", "emerald", "amber",
}

# Short category words that can live inside a model token — don't drop them.
BRAND_WORDS = {
    "samsung", "sony", "lg", "xiaomi", "redmi", "oneplus", "apple", "vivo",
    "oppo", "realme", "motorola", "nothing", "poco", "iqoo", "google", "pixel",
    "nike", "adidas", "puma", "reebok", "skechers", "converse", "newbalance", "asics",
    "tommy", "hilfiger", "levi", "levis", "wrangler", "pepe", "pumax",
}


def _fetch(url: str, **kwargs) -> Optional[requests.Response]:
    try:
        r = requests.get(url, impersonate=IMPERSONATE, timeout=TIMEOUT, **kwargs)
        if r.status_code == 200:
            return r
    except Exception:
        pass
    return None


# --- Amazon structured-data extraction -------------------------------

def _unescape(s: str) -> str:
    return html_lib.unescape(s).strip() if s else ""


def _amazon_title(html: str) -> str:
    m = re.search(r'id="productTitle"[^>]*>\s*([^<]+)', html)
    return _unescape(m.group(1)) if m else ""


def _amazon_breadcrumb(html: str) -> list[str]:
    wf = re.findall(r'wayfinding[\s\S]{0,2000}?</div>', html)
    if not wf:
        return []
    anchors = re.findall(r'<a[^>]*>\s*([^<]+?)\s*</a>', wf[0])
    return [_unescape(a) for a in anchors]


def _amazon_po_fields(html: str) -> dict:
    """<tr class="... po-<key>"> ... <span class="po-break-word">VALUE</span>"""
    out = {}
    for m in re.finditer(r'<tr class="[^"]*\bpo-([a-z_.]+)[^"]*"[^>]*>([\s\S]{1,1500}?)</tr>', html, re.I):
        key = m.group(1).strip()
        v = re.search(r'po-break-word[^>]*>\s*([^<]+)', m.group(2))
        if v and key not in out:
            out[key] = _unescape(v.group(1))
    return out


def _amazon_detail_bullets(html: str) -> dict:
    """The right-column `#detailBullets_feature_div` list items of the form
       `<span class="a-text-bold">Item model number</span><span>HR4608</span>`."""
    out = {}
    for m in re.finditer(r'<span class="a-text-bold">([^<]+)</span>\s*<span>\s*([^<]+?)\s*</span>', html):
        raw_key = re.sub(r'[‎‏\s:]+', ' ', m.group(1)).strip().lower().rstrip(":").strip()
        raw_val = re.sub(r'[‎‏]', '', m.group(2)).strip()
        if raw_key and raw_val and raw_key not in out:
            out[raw_key] = _unescape(raw_val)
    return out


def _parse_parens(title: str) -> dict:
    """Pull colour / RAM / storage out of something like
       'Samsung Galaxy A55 5G (Awesome Iceblue, 8GB RAM, 256GB Storage) | …'.
       Only the first parenthesis group is examined.
    """
    out = {}
    m = re.search(r'\(([^)]+)\)', title)
    if not m:
        return out
    parts = [p.strip() for p in m.group(1).split(",")]
    gb_bare: list[str] = []  # unlabeled "128 GB"
    for p in parts:
        has_ram_label = bool(re.search(r'\bRAM\b', p, re.I))
        has_stor_label = bool(re.search(r'\b(Storage|ROM|Internal|Memory)\b', p, re.I))
        gb_m = re.search(r'(\d+)\s*(GB|TB)', p, re.I)
        if gb_m and has_ram_label:
            out["ram"] = f"{gb_m.group(1)}{gb_m.group(2).upper()}"
        elif gb_m and has_stor_label:
            out["storage"] = f"{gb_m.group(1)}{gb_m.group(2).upper()}"
        elif gb_m:
            gb_bare.append(f"{gb_m.group(1)}{gb_m.group(2).upper()}")
        elif re.search(r'\d+\s*(?:inch|inches|cm)', p, re.I):
            sm = re.search(r'(\d+)\s*(?:inch|inches)', p, re.I)
            if sm:
                out["screen_size"] = sm.group(1)
        elif not any(ch.isdigit() for ch in p) and len(p) < 40:
            # pure word phrase → likely a colour
            out.setdefault("colour", p)
    # convention: first bare = ram, second = storage
    if gb_bare and "ram" not in out and "storage" not in out:
        out["ram"] = gb_bare[0]
        if len(gb_bare) >= 2:
            out["storage"] = gb_bare[1]
    elif gb_bare and "ram" not in out:
        out["ram"] = gb_bare[0]
    elif gb_bare and "storage" not in out:
        out["storage"] = gb_bare[0]
    return out


# --- Category detection ---------------------------------------------

def _category(breadcrumb: list[str], title: str) -> str:
    bc = " ".join(breadcrumb).lower()
    t = title.lower()

    if "smartphone" in bc or "mobile" in bc:
        return "smartphone"
    if "television" in bc or "smart tv" in bc:
        return "television"
    if "shoe" in bc or "sneaker" in bc or "footwear" in bc:
        return "sneaker"
    if any(x in bc for x in ("clothing", "t-shirt", "polo", "jersey", "shirt", "men's", "women's")):
        return "apparel"

    # No breadcrumb (Amazon fashion commonly). Fall back to the title.
    if re.search(r'\b(smart ?tv|led tv|qled|oled|smart television|google tv|fire tv|webos)\b', t, re.I):
        return "television"
    if re.search(r'\b(smartphone|mobile phone|iphone|android phone|5g smartphone)\b', t, re.I):
        return "smartphone"
    if re.search(r'\b(running\s?shoes?|sneakers?|trainers?|footwear|shoes?)\b', t, re.I):
        return "sneaker"
    if re.search(r'\b(t-?shirts?|polos?|jerseys?|tees?|shirts?)\b', t, re.I):
        return "apparel"
    return "unknown"


# --- Model / model-code extraction ----------------------------------

def _clean_model_name(title: str, brand: str, category: str) -> str:
    """Strip brand + noise and return a crisp model phrase."""
    t = title

    if category in ("smartphone", "television"):
        t = re.sub(r'\([^)]*\)', ' ', t)
        t = re.sub(r'\|[\s\S]*$', ' ', t)
        t = re.split(r'\s[–—-]\s', t)[0]
        # Drop marketing chaff like "with No Cost EMI / Additional Exchange"
        t = re.split(r'\bwith\b|\bfor\b', t, maxsplit=1, flags=re.I)[0]
        t = t.split(",")[0]

    t = re.sub(rf'^\s*{re.escape(brand)}\b[\s,]*', '', t, flags=re.I)

    if category == "television":
        # remove screen-size hints "139 cm (55 inches)" patterns
        t = re.sub(r'\d+\s*(?:cms|cm|centim\w*)[\s\w]*?\(\s*\d+\s*inches?\s*\)', ' ', t, flags=re.I)
        t = re.sub(r'\d+(?:\.\d+)?\s*(?:inches|inch|cms|cm)\b', ' ', t, flags=re.I)
        # drop generic TV words
        drops = ["Smart", "LED", "OLED", "QLED", "NanoCell", "Nano", "Smartchoice",
                 "Ultra HD", "Ultra", "HD", "Ready", "UHD", "4K", "3D",
                 "Google TV", "Fire TV", "webOS", "WebOS", "Google", "Fire",
                 "Series", "AI", "TV", "Television", "with", "at", "Best",
                 "Latest", "New", "2024", "2025", "2026"]
        for w in drops:
            t = re.sub(rf'\b{re.escape(w)}\b', ' ', t, flags=re.I)
        t = re.sub(r'\d+\s*x\s*\d+', ' ', t)  # resolution like 3840 x 2160

    if category == "smartphone":
        for w in ["Smartphone", "Mobile", "5G", "4G", "AI"]:
            t = re.sub(rf'\b{re.escape(w)}\b', ' ', t, flags=re.I)

    if category in ("sneaker", "apparel"):
        # Strip trailing junk after comma or dash
        t = re.split(r'\s[–—-]\s', t)[0]
        t = t.split(",")[0]
        # Also split on slash (e.g. "TENABL/White")
        t = t.split("/")[0]
        tokens = re.findall(r"[A-Za-z0-9']+", t)
        keep = []
        for tok in tokens:
            raw = tok.lower()
            low = re.sub(r"'s$", "", raw)
            low_sing = low.rstrip("s") if len(low) > 2 else low
            if low == brand.lower() or low_sing == brand.lower():
                continue
            if low in FASHION_NOISE or low_sing in FASHION_NOISE:
                continue
            if low in COLOUR_WORDS or low_sing in COLOUR_WORDS:
                continue
            if len(tok) == 1 and not tok.isdigit():
                continue
            # Skip ALL-CAPS tokens 4+ chars that look like adidas-style colour codes
            # (TENABL, TENABLWHT, etc.) — distinct from brand model names which are
            # normally mixed-case or standalone alphanumeric.
            # drop adidas-style ALL-CAPS colour codes (TENABL, TENABLWHT) — 5+ letters only
            if len(tok) >= 5 and tok.isupper() and tok.isalpha():
                continue
            keep.append(tok)
        return " ".join(keep[:4])

    t = re.sub(r'\s+', ' ', t).strip(' ,-|')
    tokens = t.split()
    # trim to the first 6 significant tokens
    return " ".join(tokens[:6])


# A TV model code: 6+ characters, letters AND digits, optional dashes.
_TV_CODE_RE = re.compile(r'\b([A-Z0-9][A-Z0-9-]{5,})\b')
# A fashion item model number: Letters+digits like HR4608 / IU1397 / KH7234 / 687093.
_FASHION_CODE_RE = re.compile(r'\b([A-Z]{1,4}\d{3,6}|[0-9]{5,8})\b')
_CODE_STOPWORDS = {
    "BRAVIA", "WEBOS", "NANOCELL", "NANO", "QLED", "OLED", "ULTRA", "VISION",
    "SMART", "GOOGLE", "CRYSTAL", "SMARTCHOICE", "SERIES", "GEMINI", "GORILLA",
    "MOBILE", "SMARTPHONE", "ANDROID", "IPHONE", "TELEVISION",
    "NIGHTOGRAPHY", "VICTUS", "SAMOLED", "SAMSUNG", "APPLE", "XIAOMI", "ONEPLUS",
    "WOMENS", "MENS", "WOMEN", "SPORTS",
}


def _tv_model_code(title: str) -> str:
    for m in _TV_CODE_RE.finditer(title):
        tok = m.group(1)
        if tok.upper() in _CODE_STOPWORDS:
            continue
        if not (any(c.isalpha() for c in tok) and any(c.isdigit() for c in tok)):
            continue
        # skip codes that are just screen-size cm/inch artefacts
        if re.fullmatch(r'\d+(?:CM|CMS|INCHES?)', tok, re.I):
            continue
        return tok
    return ""


def _fashion_model_code(details: dict) -> str:
    for k, v in details.items():
        if "model number" in k or "item model" in k:
            return v.strip()
    return ""


# --- Colour / screen / storage from title ---------------------------

def _title_storage(title: str, ram: str = "") -> str:
    # explicit "X GB Storage" wins
    m = re.search(r'(\d+)\s*(GB|TB)\s*(?:Storage|ROM|Internal|Memory)', title, re.I)
    if m:
        return f"{m.group(1)}{m.group(2).upper()}"
    # else: first GB/TB that isn't the RAM number
    ram_num = re.sub(r'[^\d]', '', ram) if ram else None
    seen_ram = False
    for m in re.finditer(r'(\d+)\s*(GB|TB)', title, re.I):
        n = m.group(1)
        if ram_num and n == ram_num and not seen_ram:
            seen_ram = True
            continue
        return f"{n}{m.group(2).upper()}"
    return ""


def _title_ram(title: str) -> str:
    m = re.search(r'(\d+)\s*GB\s*RAM', title, re.I)
    if m:
        return f"{m.group(1)}GB"
    return ""


def _title_colour(title: str, parens_colour: str = "") -> str:
    if parens_colour:
        return parens_colour.strip()
    # Fall back: look for a colour word + its preceding adjective in the title.
    tokens = re.findall(r"[A-Za-z]+", title)
    for i, tok in enumerate(tokens):
        if tok.lower() in COLOUR_WORDS:
            prev = tokens[i - 1] if i > 0 else ""
            if prev and prev.lower() not in FASHION_NOISE and prev[0].isupper() and prev.lower() not in BRAND_WORDS:
                return f"{prev} {tok}".strip()
            return tok
    return ""


# --- Amazon brand ----------------------------------------------------

def _brand_from_byline(html: str) -> str:
    m = re.search(r'id="bylineInfo"[^>]*>\s*([^<]+)', html)
    if not m:
        return ""
    raw = _unescape(m.group(1))
    raw = re.sub(r'(Visit the|Brand:|Store|,)', '', raw, flags=re.I).strip()
    return raw


def _brand_guess(title: str) -> str:
    cleaned = re.sub(r'^\(.*?\)\s*', '', title).strip()
    return cleaned.split()[0] if cleaned else ""


# --- Main Amazon extractor ------------------------------------------

def extract_amazon_product(url: str) -> dict:
    r = _fetch(url)
    if not r:
        raise RuntimeError("Amazon fetch failed")
    html = r.text

    title = _amazon_title(html)
    if not title:
        raise RuntimeError("No product title on Amazon page (possibly blocked)")

    breadcrumb = _amazon_breadcrumb(html)
    po = _amazon_po_fields(html)
    details = _amazon_detail_bullets(html)
    parens = _parse_parens(title)

    brand = po.get("brand") or _brand_from_byline(html) or _brand_guess(title)

    category = _category(breadcrumb, title)

    ram = ""
    storage = ""
    screen_size = ""
    colour = ""
    model_code = ""

    if category == "smartphone":
        ram = parens.get("ram") or _normalize_gb(po.get("ram_memory.installed_size")) or _title_ram(title)
        storage = parens.get("storage") or _title_storage(title, ram)
        colour = parens.get("colour") or _title_colour(title)
    elif category == "television":
        screen_size = _normalize_screen(po.get("display.size")) or parens.get("screen_size") or _regex_screen(title)
        model_code = _tv_model_code(title)
        colour = parens.get("colour") or _title_colour(title)
    elif category in ("sneaker", "apparel"):
        colour = parens.get("colour") or _title_colour(title)
        model_code = _fashion_model_code(details)
    else:
        colour = parens.get("colour") or _title_colour(title)

    model = _clean_model_name(title, brand, category)

    # Derived key_attr for the UI
    if category == "smartphone":
        parts = []
        if ram: parts.append(f"{ram} RAM")
        if storage: parts.append(storage)
        key_attr = " ".join(parts)
    elif category == "television":
        parts = []
        if screen_size: parts.append(f"{screen_size} inch")
        if model_code: parts.append(model_code)
        key_attr = " · ".join(parts)
    else:
        parts = []
        if colour: parts.append(colour)
        if model_code: parts.append(model_code)
        key_attr = " · ".join(parts)

    return {
        "brand": brand,
        "model": model,
        "model_code": model_code,
        "category": category,
        "ram": ram,
        "storage": storage,
        "screen_size": screen_size,
        "colour": colour,
        "title": title[:250],
        "key_attr": key_attr,
    }


def _normalize_gb(s: str) -> str:
    if not s: return ""
    m = re.search(r'(\d+)\s*(GB|TB)', s, re.I)
    return f"{m.group(1)}{m.group(2).upper()}" if m else ""


def _normalize_screen(s: str) -> str:
    if not s: return ""
    m = re.search(r'(\d{2,3})', s)
    return m.group(1) if m else ""


def _regex_screen(title: str) -> str:
    m = re.search(r'\(\s*(\d{2,3})\s*inches?\s*\)', title, re.I)
    if m: return m.group(1)
    m = re.search(r'(\d{2,3})\s*(?:inch|inches|")', title, re.I)
    return m.group(1) if m else ""


# --- Matching -------------------------------------------------------

def _norm(s: str) -> str:
    """Lowercase + strip whitespace AND dashes so '256 GB' == '256gb' and 'K-55S25BM2' == 'k55s25bm2'."""
    return re.sub(r'[\s\-]+', '', (s or '').lower())


def _tokens(s: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", s or '')


def _model_tokens(product: dict) -> list[str]:
    """Return the tokens from the product's model name worth checking.
       Drops brand repeats; keeps single-digit tokens."""
    brand = product.get("brand", "").lower()
    out = []
    for t in _tokens(product.get("model", "")):
        low = t.lower()
        if low == brand: continue
        if low in FASHION_NOISE: continue
        if low in COLOUR_WORDS: continue
        if low in BRAND_WORDS and low != brand: continue
        out.append(t)
    return out


def _digit_tokens(tokens: list[str]) -> list[str]:
    return [t for t in tokens if any(c.isdigit() for c in t)]


def _alpha_tokens(tokens: list[str]) -> list[str]:
    return [t for t in tokens if not any(c.isdigit() for c in t)]


def matches(product: dict, candidate_title: str, candidate_body: str = "") -> bool:
    """Return True if the candidate plausibly refers to the same product.

    `candidate_body` is an optional HTML or text blob — used to find model codes
    hidden in product descriptions (Flipkart) that aren't in the <title> tag.
    """
    cand_full = candidate_title + " " + candidate_body
    cand_norm = _norm(cand_full)
    cand_lower = cand_full.lower()

    brand = _norm(product.get("brand", ""))
    if brand and brand not in _norm(candidate_title):
        return False

    code = product.get("model_code", "")
    cat = product.get("category", "")

    # Model code is a strong positive signal.
    code_hit = bool(code) and _norm(code) in cand_norm
    if code_hit:
        return True

    # For TVs, if a model code is known AND wasn't found, reject.
    # (Sneakers/apparel can legitimately miss the code from listings.)
    if cat == "television" and code:
        return False

    if cat == "smartphone":
        ram = _norm(product.get("ram", ""))
        storage = _norm(product.get("storage", ""))
        if ram and ram not in cand_norm:
            return False
        if storage and storage not in cand_norm:
            return False
    elif cat == "television":
        ss = product.get("screen_size", "")
        if ss and not re.search(rf'\b{ss}\b', candidate_title):
            return False
    elif cat in ("sneaker", "apparel"):
        colour = product.get("colour", "")
        if colour:
            colour_tokens = [w.lower() for w in _tokens(colour)]
            base_hits = [w for w in colour_tokens if w in COLOUR_WORDS]
            if base_hits and not any(w in cand_lower for w in base_hits):
                return False

    # Model name tokens
    model_tokens = _model_tokens(product)
    digit = _digit_tokens(model_tokens)
    alpha = _alpha_tokens(model_tokens)

    for w in digit:
        if _norm(w) not in _norm(candidate_title):
            return False
    if alpha:
        hits = sum(1 for w in alpha if _norm(w) in _norm(candidate_title))
        # Fashion needs EVERY alpha token (different model lines share digits).
        # Phones/TVs can drop one series word (e.g. "Galaxy" on Flipkart listings).
        if cat in ("sneaker", "apparel"):
            required = len(alpha)
        else:
            required = len(alpha) // 2
        if hits < required:
            return False

    return True


# --- Stock detection ------------------------------------------------

def detect_stock(html: str) -> str:
    low = html.lower()
    if any(kw in low for kw in STOCK_OUT_STRONG):
        return "out_of_stock"
    if any(kw in low for kw in STOCK_IN):
        return "in_stock"
    if any(kw in low for kw in STOCK_OUT_WEAK):
        return "out_of_stock"
    return "in_stock"


# --- Platform-specific search queries --------------------------------

def _queries_for(product: dict) -> list[str]:
    """Candidate search query strings for the product, best-first."""
    brand = product.get("brand", "")
    model = product.get("model", "")
    code = product.get("model_code", "")
    cat = product.get("category", "")

    queries = []
    if code:
        queries.append(f"{brand} {code}".strip())

    if cat == "smartphone":
        storage = product.get("storage", "")
        ram = product.get("ram", "")
        queries.append(f"{brand} {model} {storage}".strip())
        queries.append(f"{brand} {model} {ram} {storage}".strip())
        queries.append(f"{brand} {model}".strip())
    elif cat == "television":
        ss = product.get("screen_size", "")
        queries.append(f"{brand} {model} {ss} inch".strip())
        queries.append(f"{brand} {ss} inch {model}".strip())
        queries.append(f"{brand} {model}".strip())
    elif cat in ("sneaker", "apparel"):
        # Infer a category word from the title so queries pick up the right aisle
        title_low = product.get("title", "").lower()
        if cat == "sneaker":
            cat_hint = "shoes"
        elif "polo" in title_low:
            cat_hint = "polo"
        elif "jersey" in title_low:
            cat_hint = "jersey"
        else:
            cat_hint = "t-shirt"
        colour = product.get("colour", "")
        queries.append(f"{brand} {model} {cat_hint}".strip())
        queries.append(f"{brand} {model} {colour}".strip())
        queries.append(f"{brand} {model}".strip())
    else:
        queries.append(f"{brand} {model}".strip())

    # Dedup, keep order
    seen, out = set(), []
    for q in queries:
        q = re.sub(r"\s+", " ", q).strip()
        if q and q.lower() not in seen:
            seen.add(q.lower()); out.append(q)
    return out


# --- Flipkart -------------------------------------------------------

def find_on_flipkart(product: dict) -> dict:
    tried_links: set[str] = set()
    for query in _queries_for(product)[:3]:
        url = f"https://www.flipkart.com/search?q={urllib.parse.quote_plus(query)}"
        r = _fetch(url)
        if not r:
            continue
        links = re.findall(r'href="(/[^"#?]+/p/[^"&]+)(?:&amp;|\?|")', r.text)
        links = [l.replace('&amp;', '&') for l in dict.fromkeys(links)]
        if not links:
            continue
        for link in links[:15]:
            page_url = "https://www.flipkart.com" + link
            if page_url in tried_links:
                continue
            tried_links.add(page_url)
            r2 = _fetch(page_url)
            if not r2:
                continue
            title_m = re.search(r'<title>([^<]+)</title>', r2.text)
            page_title = _unescape(title_m.group(1)) if title_m else ""
            # Pass a body snippet so a model-code hiding in the description still hits.
            body_snippet = r2.text[:80000]
            if matches(product, page_title, body_snippet):
                return {
                    "platform": "Flipkart",
                    "status": detect_stock(r2.text),
                    "url": page_url,
                    "matched_title": page_title[:180],
                    "reasoning": f"matched via query: {query}",
                }
    return _not_listed("Flipkart", "no candidate matched any query")


# --- Myntra ---------------------------------------------------------

_MYNTRA_PATH_SAFE = re.compile(r"[^a-zA-Z0-9\- ]")


def _myntra_slug(query: str) -> str:
    # HTML-decode (already done upstream), strip unsafe chars, collapse spaces.
    q = _unescape(query)
    q = _MYNTRA_PATH_SAFE.sub(' ', q)
    q = re.sub(r'\s+', ' ', q).strip()
    return urllib.parse.quote(q.replace(' ', '-'))


def find_on_myntra(product: dict) -> dict:
    for query in _queries_for(product):
        slug = _myntra_slug(query)
        if not slug:
            continue
        url = f"https://www.myntra.com/{slug}"
        r = _fetch(url)
        if not r:
            continue
        idx = r.text.find("window.__myx")
        if idx < 0:
            continue
        eq = r.text.find("=", idx)
        start = r.text.find("{", eq)
        try:
            data, _ = json.JSONDecoder().raw_decode(r.text[start:])
        except Exception:
            continue
        products = (data.get("searchData", {}).get("results", {}).get("products", [])) or []
        for p in products[:15]:
            name = p.get("productName") or ""
            brand = p.get("brand") or ""
            full = f"{brand} {name}"
            if not matches(product, full):
                continue
            slug_url = p.get("landingPageUrl", "")
            page_url = f"https://www.myntra.com/{slug_url}" if slug_url else ""
            status = "in_stock"
            if page_url:
                r2 = _fetch(page_url)
                if r2:
                    status = detect_stock(r2.text)
            return {
                "platform": "Myntra",
                "status": status,
                "url": page_url,
                "matched_title": name[:180],
                "reasoning": f"matched via query: {query}",
            }
    return _not_listed("Myntra", "no candidate matched any query")


# --- Helpers --------------------------------------------------------

def _not_listed(platform: str, reason: str) -> dict:
    return {
        "platform": platform,
        "status": "not_listed",
        "url": "",
        "matched_title": "",
        "reasoning": reason,
    }
