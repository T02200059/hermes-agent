#!/usr/bin/env python3
"""
Update NewAPI exchange rate and DeepSeek model pricing.

Data sources:
  - Exchange rate: open.er-api.com (free, no key)
  - DeepSeek pricing: static mapping (CNY, from https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)
    Extensible: replace DEEPSEEK_PRICING_CNY with a scraper function.

NewAPI endpoint: https://genai.damodel.com

NewAPI pricing formula:
    CNY per M = ModelRatio × 2 × USDExchangeRate
    => ModelRatio = CNY_blend / (2 × USDExchangeRate)

This script runs daily (08:30) as a no_agent cron job.
"""
import json
import os
import urllib.request

# ── Config ──────────────────────────────────────────────────────────────
EXCHANGE_API_URL = "https://open.er-api.com/v6/latest/USD"
NEWAPI_BASE_URL = "https://genai.damodel.com"
NEWAPI_USERNAME = os.environ.get("NEWAPI_USERNAME", "admin")
NEWAPI_PASSWORD = os.environ.get("NEWAPI_PASSWORD", "")
COOKIE_FILE = "/tmp/napi_rate_cookie.txt"

# ── Pricing Source (extensible) ─────────────────────────────────────────
#
# Structure: { newapi_model_name: {input, output, blend_weight} }
#   input/output: CNY per million tokens (cache miss)
#   blend_weight: weight of input vs output (default 3 → 3:1 ratio)
#
# To add a model: append an entry.
# To replace with scraper: swap this dict with a fetch_deepseek_pricing() call.
# To add a provider: create e.g. OPENAI_PRICING_USD dict + its own compute fn.
# ─────────────────────────────────────────────────────────────────────────
DEEPSEEK_PRICING_CNY = {
    # v4-flash (aliases point to same pricing)
    "deepseek-chat":   {"input": 1.0, "output": 2.0, "blend_weight": 3},
    "deepseek-v4-flash": {"input": 1.0, "output": 2.0, "blend_weight": 3},
    "deepseek-coder":  {"input": 1.0, "output": 2.0, "blend_weight": 3},
    # v4-pro (75% off until 2026-05-31)
    "deepseek-v4-pro": {"input": 3.0, "output": 6.0, "blend_weight": 3},
}

# ── Helpers ─────────────────────────────────────────────────────────────

def _blend_cny_price(input_cny: float, output_cny: float, blend_weight: int) -> float:
    """Blended CNY price per M tokens using weighted input:output ratio."""
    return (blend_weight * input_cny + output_cny) / (blend_weight + 1)


def _compute_model_ratio(blend_cny: float, usd_rate: float) -> float:
    """Convert CNY/M → ModelRatio using NewAPI's internal formula.

    CNY/M = ModelRatio × 2 × USDExchangeRate
    => ModelRatio = CNY/M ÷ (2 × USDExchangeRate)
    """
    return round(blend_cny / (2.0 * usd_rate), 6)

# ── API helpers ─────────────────────────────────────────────────────────

def _fetch_cny_rate() -> float:
    try:
        with urllib.request.urlopen(EXCHANGE_API_URL, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        raise RuntimeError(f"Failed to fetch exchange rate: {e}")
    if data.get("result") != "success":
        raise RuntimeError(f"API returned non-success: {data.get('result')}")
    cny = data.get("rates", {}).get("CNY")
    if cny is None:
        raise RuntimeError("CNY rate not found in API response")
    return float(cny)


def _newapi_login():
    payload = json.dumps({"username": NEWAPI_USERNAME, "password": NEWAPI_PASSWORD}).encode()
    req = urllib.request.Request(
        f"{NEWAPI_BASE_URL}/api/user/login",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        raise RuntimeError(f"NewAPI login failed: {e}")
    if not data.get("success"):
        raise RuntimeError(f"NewAPI login rejected: {data.get('message')}")
    cookies = resp.headers.get_all("Set-Cookie")
    if cookies:
        cookie_str = "; ".join(c.split(";")[0] for c in cookies)
        with open(COOKIE_FILE, "w") as f:
            f.write(cookie_str)


def _newapi_get_option(key: str):
    """Return raw option value as a string (or None if not found)."""
    with open(COOKIE_FILE) as f:
        cookie_str = f.read().strip()
    req = urllib.request.Request(
        f"{NEWAPI_BASE_URL}/api/option/",
        headers={"Cookie": cookie_str, "New-Api-User": "1"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    for opt in data["data"]:
        if opt["key"] == key:
            return opt["value"]
    return None


def _newapi_put_option(key: str, value):
    with open(COOKIE_FILE) as f:
        cookie_str = f.read().strip()
    payload = json.dumps({"key": key, "value": value}).encode()
    req = urllib.request.Request(
        f"{NEWAPI_BASE_URL}/api/option/",
        data=payload,
        headers={"Content-Type": "application/json", "Cookie": cookie_str, "New-Api-User": "1"},
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    if not data.get("success"):
        raise RuntimeError(f"PUT {key} rejected: {data.get('message')}")


# ── Main ────────────────────────────────────────────────────────────────

def main():
    if not NEWAPI_PASSWORD:
        raise RuntimeError("NEWAPI_PASSWORD env var not set.")

    # 1. Login
    _newapi_login()
    print("🔑 NewAPI login OK")

    # 2. Fetch exchange rate
    usd_rate = _fetch_cny_rate()
    print(f"📊 USD/CNY: {usd_rate:.4f}")

    # 3. Update USDExchangeRate
    old_rate_str = _newapi_get_option("USDExchangeRate")
    old_rate = float(old_rate_str)
    if abs(usd_rate - old_rate) > 0.0001:
        _newapi_put_option("USDExchangeRate", f"{usd_rate:.4f}")
        print(f"✅ USDExchangeRate: {old_rate} → {usd_rate:.4f}")
    else:
        print(f"⏭️  USDExchangeRate unchanged: {old_rate}")

    # 4. Recompute DeepSeek ModelRatios from CNY pricing
    model_ratios = json.loads(_newapi_get_option("ModelRatio"))
    updated = 0

    for model_name, price_info in DEEPSEEK_PRICING_CNY.items():
        blend_cny = _blend_cny_price(
            price_info["input"], price_info["output"], price_info.get("blend_weight", 3)
        )
        new_ratio = _compute_model_ratio(blend_cny, usd_rate)
        old_ratio = model_ratios.get(model_name)

        if old_ratio is not None and abs(new_ratio - old_ratio) < 0.0001:
            continue  # unchanged

        model_ratios[model_name] = new_ratio
        updated += 1
        print(f"  {model_name}: {old_ratio} → {new_ratio}  (CNY blend={blend_cny}/M)")

    if updated > 0:
        _newapi_put_option("ModelRatio", json.dumps(model_ratios, ensure_ascii=False))
        print(f"✅ Updated {updated} ModelRatio entries")
    else:
        print("⏭️  ModelRatio unchanged")

    # 5. Verify
    verify_rate = _newapi_get_option("USDExchangeRate")
    print(f"✔️  Verified USDExchangeRate: {verify_rate}")


if __name__ == "__main__":
    main()
