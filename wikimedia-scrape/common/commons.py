"""Wikimedia Commons API helpers shared by every source: list a category's
files, fetch image metadata (url, description, member categories), and download
bytes with polite 429 backoff.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://commons.wikimedia.org/w/api.php"
UA = "FugleRammeScrape/1.0 (arnegiacomo@gmail.com) educational"

_TAG = re.compile("<[^>]+>")


def api(params):
    params["format"] = "json"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(API, data=data, headers={"User-Agent": UA})
    return json.load(urllib.request.urlopen(req))


def list_files(categories):
    """All file titles across the given categories (deduped, order preserved)."""
    seen, out = set(), []
    for cat in categories:
        cont = {}
        while True:
            d = api(dict(action="query", list="categorymembers", cmtitle=cat,
                         cmtype="file", cmlimit="500", **cont))
            for m in d["query"]["categorymembers"]:
                if m["title"] not in seen:
                    seen.add(m["title"])
                    out.append(m["title"])
            if "continue" in d:
                cont = d["continue"]
            else:
                break
    return out


def image_info(titles):
    """{title: {'url', 'mime', 'width', 'height', 'desc', 'categories'}} for up
    to 50 titles.

    `mime` is the file's media type (e.g. 'image/jpeg'); Commons categories mix
    in PDFs and other non-raster media, so callers filter on it. `desc` is the
    plain-text ImageDescription; `categories` is the file's list of (non-hidden)
    member category titles, e.g. 'Category:Tyto alba (illustrations)'.
    """
    d = api(dict(action="query", titles="|".join(titles),
                 prop="imageinfo|categories", iiprop="url|size|mime|extmetadata",
                 cllimit="max", clshow="!hidden"))
    out = {}
    for pg in d["query"]["pages"].values():
        ii = pg["imageinfo"][0]
        out[pg["title"]] = {
            "url": ii["url"],
            "mime": ii.get("mime", ""),
            "width": ii["width"],
            "height": ii["height"],
            "desc": ii["extmetadata"].get("ImageDescription", {}).get("value", ""),
            "categories": [c["title"] for c in pg.get("categories", [])],
        }
    return out


def fetch(url):
    delay = 1.0
    for _ in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=90).read()
        except urllib.error.HTTPError as e:
            if e.code == 429:                       # be polite, back off
                time.sleep(delay); delay = min(delay * 2, 30); continue
            raise
    raise RuntimeError("gave up after retries")
