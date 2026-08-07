import httpx, re, json
from bs4 import BeautifulSoup

url = "https://www.google.com/finance/quote/EUR-INR"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
resp = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
soup = BeautifulSoup(resp.text, "lxml")

for script in soup.find_all("script"):
    text = script.string or ""
    if "ds:10" in text and "AF_initDataCallback" in text:
        match = re.search(r"AF_initDataCallback\({key: 'ds:10'.*?data:(.*?)\}\);", text, re.DOTALL)
        if match:
            data_str = match.group(1)
            pairs = re.findall(
                r"\[(\d{4}),(\d{1,2}),(\d{1,2}),null,(\d+),null,null,\[\]\],\[([\d.]+)",
                data_str
            )
            print(f"Found {len(pairs)} intraday points:")
            for y, m, d, h, price in pairs[:15]:
                print(f"  {y}-{m}-{d} hour={h} price={price}")
            if len(pairs) > 15:
                print(f"  ... ({len(pairs)} total)")
