from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request, send_from_directory

import croma
import scraper

app = Flask(__name__)

CATEGORY_RULES = {
    "smartphone":  {"platforms": ["flipkart", "croma"],   "must_match": "RAM and storage"},
    "television":  {"platforms": ["flipkart", "croma"],   "must_match": "screen size"},
    "sneaker":     {"platforms": ["flipkart", "myntra"],  "must_match": "colour"},
    "apparel":     {"platforms": ["flipkart", "myntra"],  "must_match": "colour"},
}

FINDERS = {
    "flipkart": scraper.find_on_flipkart,
    "myntra":   scraper.find_on_myntra,
    "croma":    croma.find_on_croma,
}


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/match", methods=["POST"])
def match():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    if not url or "amazon." not in url:
        return jsonify({"error": "Provide a valid Amazon product URL"}), 400

    try:
        product = scraper.extract_amazon_product(url)
    except Exception as e:
        return jsonify({"error": f"Could not read Amazon page: {e}"}), 500

    category = product.get("category")
    if category not in CATEGORY_RULES:
        return jsonify({"error": f"Unsupported category: {category}", "product": product}), 400

    platforms = CATEGORY_RULES[category]["platforms"]
    with ThreadPoolExecutor(max_workers=len(platforms)) as pool:
        results = list(pool.map(lambda p: FINDERS[p](product), platforms))

    return jsonify({"product": product, "results": results})


if __name__ == "__main__":
    print("\n  Open http://127.0.0.1:5050\n")
    app.run(host="127.0.0.1", port=5050, debug=True)
