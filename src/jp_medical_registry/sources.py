"""Versioned regional discovery rules. Workbook headers remain authoritative."""
import re
import unicodedata
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

BASE = "https://kouseikyoku.mhlw.go.jp"
REGIONS = {
    "hokkaido": ("北海道厚生局", "/hokkaido/gyomu/gyomu/hoken_kikan/code_ichiran.html", [1]),
    "tohoku": ("東北厚生局", "/tohoku/gyomu/gyomu/hoken_kikan/itiran.html", list(range(2,8))),
    "kanto": ("関東信越厚生局", "/kantoshinetsu/chousa/shitei.html", [8,9,10,11,12,13,14,15,19,20]),
    "tokai": ("東海北陸厚生局", "/tokaihokuriku/newpage_00287.html", [16,17,21,22,23,24]),
    "kinki": ("近畿厚生局", "/kinki/tyousa/shinkishitei.html", [18,25,26,27,28,29,30]),
    "chugoku": ("中国四国厚生局", "/chugokushikoku/chousaka/iryoukikanshitei.html", [31,32,33,34,35]),
    "shikoku": ("四国厚生支局", "/shikoku/gyomu/gyomu/hoken_kikan/shitei/index.html", [36,37,38,39]),
    "kyushu": ("九州厚生局", "/kyushu/gyomu/gyomu/hoken_kikan/index_00006.html", list(range(40,48))),
}

def compact(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))

def validate_month(month):
    if not re.fullmatch(r"20[0-9]{2}-(0[1-9]|1[0-2])", month):
        raise ValueError("month must be YYYY-MM")
    return month

def month_tokens(month):
    year, m = map(int, validate_month(month).split("-"))
    return [f"令和{year-2018}年{m}月", f"R{year-2018}年{m}月", f"{year}年{m}月"]

def discover(html, region, month, page_url=None):
    validate_month(month)
    page_url = page_url or BASE + REGIONS[region][1]
    soup = BeautifulSoup(html, "html.parser")
    year, m = map(int, month.split("-"))
    era = f"r{year-2018:02}{m:02}"
    found = {}
    for anchor in soup.select("a[href]"):
        url = urljoin(page_url, anchor["href"])
        path = urlparse(url).path.lower()
        if urlparse(url).hostname != "kouseikyoku.mhlw.go.jp" or not path.endswith((".xlsx", ".zip", ".pdf", ".xls")):
            continue
        row = anchor.find_parent("tr")
        table = anchor.find_parent("table")
        heading = anchor.find_previous(["h2", "h3", "h4"])
        head = compact(heading.get_text(" ", strip=True)) if heading else ""
        rowtext = compact(row.get_text(" ", strip=True)) if row else compact(anchor.parent.get_text(" ", strip=True))
        tabletext = compact(table.get_text(" ", strip=True))[:500] if table else ""
        text = compact(anchor.get_text(" ", strip=True))
        snapshot = False
        if region == "hokkaido":
            snapshot = "コード内容別" in head
        elif region in ("tohoku", "kanto"):
            snapshot = bool(re.search(r"shitei[-_](?:touhoku[-_])?(?:ika|shika|yakkyoku)[-_]"+era, path))
        elif region == "tokai":
            snapshot = bool(re.search(fr"/{year%100:02}{m:02}-01-(01|03|04)\.zip$", path))
        elif region == "kinki":
            snapshot = f"{year}.{m}_kikanzentai_" in path
        elif region == "chugoku":
            snapshot = "コード内容別医療機関" in head and any(t in head for t in month_tokens(month))
        elif region == "shikoku":
            snapshot = "コード内容別医療機関" in tabletext and any(t in tabletext for t in month_tokens(month))
        elif region == "kyushu":
            preceding = anchor.find_previous("strong")
            date_text = compact(preceding.get_text()) if preceding else ""
            snapshot = any(t in date_text for t in month_tokens(month)) and "現在" in date_text and "エクセル" in text
        # For non-Excel snapshots retain PDF evidence only through discovery output;
        # download avoids parallel PDF copies where an Excel equivalent is present.
        if snapshot and path.endswith((".xlsx", ".zip", ".xls")):
            found[url] = dict(url=url, category="snapshot", region=region,
                label=text, context=rowtext[:500], discovery_page=page_url)
    return list(found.values())
