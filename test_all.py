"""Run the 20 reviewer URLs through the pipeline and show a compact report.

Usage: python test_all.py
"""
import time
from concurrent.futures import ThreadPoolExecutor

import scraper
import croma

# (category, Amazon ASIN, expected label, (flipkart_expect, other_expect))
# Expectations: "found" means the product exists on that platform;
# "out" means found but currently out of stock on that platform;
# "not" means legitimately not carried.
# The tuple is (flipkart, croma_or_myntra).
CASES = [
    # Smartphones -> Flipkart + Croma
    ("smartphone", "B0FDB9ZCTD", "Samsung Galaxy M36 5G",            "found", "not"),
    ("smartphone", "B0CWPC2W5V", "Samsung Galaxy A55 5G",            "found", "found"),
    ("smartphone", "B0GS5SM6JR", "REDMI A7 Pro 5G 64GB",             "found", "not"),
    ("smartphone", "B0HJB3GZ2C", "Apple iPhone 18 Pro 512GB",        "found", "found"),
    ("smartphone", "B0H3KZHC8L", "vivo Y31 5G",                      "out",   "found"),

    # Televisions -> Flipkart + Croma
    ("television", "B0F7X5FC43", "Sony BRAVIA 2M2 55 K-55S25BM2",    "found", "found"),
    ("television", "B0F7WVPWG8", "Sony BRAVIA 2M2 43 K-43S22M2",     "found", "found"),
    ("television", "B0GTZ9TSDJ", "LG 43 NU87 43NU870BPLA",           "found", "found"),
    ("television", "B0F3JM1YP5", "Xiaomi 32 F Series",                "found", "not"),
    ("television", "B0GXB76VRW", "Samsung 43 Crystal UHD 2026",      "not",   "not"),

    # Sneakers -> Flipkart + Myntra
    ("sneaker",    "B0000ATCP4", "Converse Chuck Taylor Ox Black",   "found", "found"),
    ("sneaker",    "B0GSRDSKYD", "Nike Women's Court Vision Alta",   "found", "found"),
    ("sneaker",    "B0CJ55P4M8", "Skechers Uno Lite",                "found", "found"),
    ("sneaker",    "B0DPHV2SVJ", "Nike Revolution 8",                "found", "found"),
    ("sneaker",    "B0GFN1LBFG", "adidas Breaknet 3.0",              "not",   "found"),

    # Apparel -> Flipkart + Myntra
    ("apparel",    "B0D9JYRZGB", "adidas MU 24/25 Jersey",           "found", "found"),
    ("apparel",    "B0B4CZWYTH", "adidas TIRO 23 Jersey",            "found", "found"),
    ("apparel",    "B09167TMLD", "Puma teamLIGA Jersey",             "out",   "found"),
    ("apparel",    "B0DDTH33PL", "Puma Essential Polo",              "found", "found"),
    ("apparel",    "B07XK9H5KF", "Levi's 025 Black T-shirt",         "out",   "found"),
]

CAT_PLATFORMS = {
    "smartphone": ("flipkart", "croma"),
    "television": ("flipkart", "croma"),
    "sneaker":    ("flipkart", "myntra"),
    "apparel":    ("flipkart", "myntra"),
}

FINDERS = {
    "flipkart": scraper.find_on_flipkart,
    "myntra":   scraper.find_on_myntra,
    "croma":    croma.find_on_croma,
}

STATUS_SHORT = {"in_stock": "IN", "out_of_stock": "OOS", "not_listed": "NO"}


def run_one(cat: str, asin: str) -> dict:
    url = f"https://www.amazon.in/dp/{asin}"
    t0 = time.time()
    try:
        product = scraper.extract_amazon_product(url)
    except Exception as e:
        return {"error": f"extract failed: {e}", "asin": asin}
    plats = CAT_PLATFORMS.get(product["category"], ("flipkart", "croma"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda p: FINDERS[p](product), plats))
    return {
        "asin": asin,
        "product": product,
        "platforms": plats,
        "results": results,
        "took": time.time() - t0,
    }


def _verdict(expect: str, status: str) -> str:
    """A result counts as right if the expectation and the status agree.

    expect  'found' → in_stock or out_of_stock (platform HAS the product)
    expect  'out'   → out_of_stock
    expect  'not'   → not_listed
    """
    if expect == "found":
        return "✓" if status in ("in_stock", "out_of_stock") else "✗"
    if expect == "out":
        return "✓" if status in ("in_stock", "out_of_stock") else "✗"
    if expect == "not":
        return "✓" if status == "not_listed" else "✗"
    return "?"


def main():
    print(f"{'ASIN':<13} {'label':<40} {'cat':<10} {'plat A':<25} {'plat B':<25} {'t(s)':>6}")
    print("-" * 125)
    right = 0
    for cat, asin, label, ef, eo in CASES:
        r = run_one(cat, asin)
        if "error" in r:
            print(f"{asin:<13} {label:<40} ERROR: {r['error']}")
            continue
        p = r["product"]
        plats = r["platforms"]
        a, b = r["results"]
        va = _verdict(ef, a["status"])
        vb = _verdict(eo, b["status"])
        row_right = va == "✓" and vb == "✓"
        if row_right:
            right += 1
        a_s = f"{plats[0]}:{STATUS_SHORT[a['status']]}{va}"
        b_s = f"{plats[1]}:{STATUS_SHORT[b['status']]}{vb}"
        print(f"{asin:<13} {label:<40} {p['category']:<10} {a_s:<25} {b_s:<25} {r['took']:>6.1f}")
    print(f"\nFULLY CORRECT: {right}/{len(CASES)}")


if __name__ == "__main__":
    main()
