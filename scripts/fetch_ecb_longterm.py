"""Fetch long-term ECB history via SDW JSON API (single request, all currencies)."""
import json, sys, time, calendar
from pathlib import Path

import httpx

START = "2015-01-01"
END = "2026-12-31"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def main():
    print("Fetching long-term ECB history (all currencies, single request)...")
    t0 = time.time()

    url = (
        "https://data-api.ecb.europa.eu/service/data/EXR/D..EUR.SP00.A"
        f"?startPeriod={START}&endPeriod={END}&format=jsondata"
    )
    resp = httpx.get(url, headers=HEADERS, timeout=120, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json()
    print(f"  Downloaded {len(resp.content)//1024}KB in {time.time()-t0:.1f}s")

    # Extract dimensions
    structure = data["structure"]
    dims = structure["dimensions"]

    # Get currency codes from series dimension
    currency_dim = None
    for d in dims.get("series", []):
        if d["id"] == "CURRENCY":
            currency_dim = d
            break
    if not currency_dim:
        print("ERROR: CURRENCY dimension not found")
        return

    currency_values = currency_dim["values"]
    currency_codes = [v["id"] for v in currency_values]
    print(f"  Currencies: {len(currency_codes)}")

    # Get time periods
    time_dim = None
    for d in dims.get("observation", []):
        if d["id"] == "TIME_PERIOD":
            time_dim = d
            break
    if not time_dim:
        print("ERROR: TIME_PERIOD dimension not found")
        return

    time_values = [v["id"] for v in time_dim["values"]]
    print(f"  Time periods: {len(time_values)} ({time_values[0]} to {time_values[-1]})")

    # Extract observations
    series_data = data["dataSets"][0]["series"]
    by_date = {}

    for series_key, series_obj in series_data.items():
        # series_key format: "0:CURRENCY_IDX:0:0:0"
        parts = series_key.split(":")
        currency_idx = int(parts[1])
        if currency_idx >= len(currency_codes):
            continue
        currency_code = currency_codes[currency_idx]

        obs = series_obj.get("observations", {})
        for idx_str, vals in obs.items():
            idx = int(idx_str)
            if idx >= len(time_values):
                continue
            date_str = time_values[idx]
            rate = vals[0]
            if rate is None:
                continue

            if date_str not in by_date:
                ts = calendar.timegm(time.strptime(date_str, "%Y-%m-%d"))
                by_date[date_str] = {"ts": ts, "rates": {}}
            by_date[date_str]["rates"][currency_code] = float(rate)

    # Convert to sorted list
    all_events = [by_date[k] for k in sorted(by_date)]
    print(f"  Total events: {len(all_events)}")

    if all_events:
        first = all_events[0]
        last = all_events[-1]
        print(f"  First: {time.strftime('%Y-%m-%d', time.gmtime(first['ts']))} ({len(first['rates'])} currencies)")
        print(f"  Last:  {time.strftime('%Y-%m-%d', time.gmtime(last['ts']))} ({len(last['rates'])} currencies)")

    # Save
    out = Path(__file__).resolve().parent.parent / "docs" / "data" / "ecb_history.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"events": all_events}, indent=1), encoding="utf-8")
    print(f"  Saved to {out} ({out.stat().st_size // 1024}KB)")
    print(f"  Done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
