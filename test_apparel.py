"""Quick apparel-only test to verify Myntra gateway API gains."""
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
import scraper
import croma

CASES = [
    ("sneaker", "B0000ATCP4", "Converse Chuck Taylor"),
    ("sneaker", "B0GSRDSKYD", "Nike Court Vision Alta"),
    ("sneaker", "B0CJ55P4M8", "Skechers Uno Lite"),
    ("sneaker", "B0DPHV2SVJ", "Nike Revolution 8"),
    ("sneaker", "B0GFN1LBFG", "adidas Breaknet 3.0"),
    ("apparel", "B0D9JYRZGB", "adidas MU 24/25 Jersey"),
    ("apparel", "B0B4CZWYTH", "adidas TIRO 23 Jersey"),
    ("apparel", "B09167TMLD", "Puma teamLIGA Jersey"),
    ("apparel", "B0DDTH33PL", "Puma Essential Polo"),
    ("apparel", "B07XK9H5KF", "Levi's 025 Black T-shirt"),
]
STAT = {"in_stock":"IN","out_of_stock":"OOS","not_listed":"NO"}

def one(cat, asin, label):
    url = f"https://www.amazon.in/dp/{asin}"
    try:
        p = scraper.extract_amazon_product(url)
    except Exception as e:
        return f"{asin} {label[:30]}: extract err {e}"
    results = []
    for platform in ("flipkart", "myntra"):
        fn = scraper.find_on_flipkart if platform == "flipkart" else scraper.find_on_myntra
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(fn, p)
            try:
                r = fut.result(timeout=60)  # hard cap 60s per platform
            except FutTimeout:
                r = {"status": "not_listed", "url": "", "matched_title": "TIMEOUT"}
        results.append((platform, r, time.time() - t0))
    return results, p

for cat, asin, label in CASES:
    out = one(cat, asin, label)
    if isinstance(out, str):
        print(out); continue
    results, p = out
    parts = [f"{asin}", f"{label[:28]:<28}"]
    for platform, r, t in results:
        s = STAT.get(r["status"], r["status"])
        parts.append(f"{platform}:{s}({t:.1f}s)")
    print("  ".join(parts))
    # show matched title for quality check
    for platform, r, t in results:
        if r.get("matched_title"):
            print(f"    {platform}: {r['matched_title'][:120]}")
