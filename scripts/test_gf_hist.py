import httpx, re, json
from bs4 import BeautifulSoup
import calendar, time

url = "https://www.google.com/finance/quote/EUR-INR"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
resp = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
soup = BeautifulSoup(resp.text, "lxml")

for script in soup.find_all("script"):
    text = script.string or ""
    if "ds:12" in text and "AF_initDataCallback" in text:
        match = re.search(r"AF_initDataCallback\({key: 'ds:12'.*?data:(.*?)\}\);", text, re.DOTALL)
        if match:
            data_str = match.group(1)
            # Daily data: [[2026,7,7,23,58,...],[108.202,...]]
            pairs = re.findall(
                r"\[(\d{4}),(\d{1,2}),(\d{1,2}),(\d+),(\d+),null,null,\[\]\],\[([\d.]+)",
                data_str
            )
            print(f"Found {len(pairs)} daily points from Google Finance:")
            for y, m, d, h, mi, price in pairs:
                ts = int(calendar.timegm((int(y), int(m), int(d), int(h), int(mi), 0, 0, 0, 0)))
                print(f"  {y}-{m}-{d} {h}:{mi} ts={ts} price={price}")
