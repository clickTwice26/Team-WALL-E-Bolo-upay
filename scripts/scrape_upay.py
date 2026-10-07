"""Scrape upay's public website (www.upaybd.com) into a knowledge base for RAG.

The site is a Next.js app backed by a public read-only CMS API
(``api.upaybd.com/api/v2/pages/<slug>``, the same calls the site makes from
the browser). Every page's content comes as JSON with English and Bangla side
by side. This script walks both: the site pages (their ``__NEXT_DATA__``,
which also carries the charge calculator table) and the CMS pages, following
every slug and link it finds. It writes:

  data/upay_kb/pages/<slug>.json   raw pageProps for each page (for audits)
  data/upay_kb/kb.jsonl            one retrieval chunk per line
  data/upay_kb/manifest.json       crawl date, page list, counts

Only public pages are fetched, politely (a few workers, a short delay).

    .venv/bin/python scripts/scrape_upay.py
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

import httpx

BASE = "https://www.upaybd.com"
API = "https://api.upaybd.com/api/v2/pages/"
# CMS slugs the site's own JS requests, plus the service menu (rendered client-side)
API_SEEDS = ["home", "Home-Slider", "Navigation", "Footer", "who-we-are", "prepaid-card",
             "card-campaign", "Partner-with-us", "partners", "Latest-offer", "Cash-in", "Cash-Out",
             "need-help", "faq", "Pay-Bill", "Add-Money", "Blog", "Media", "Media-Contact",
             "Newsroom", "Service-location", "discontinued-agent", "limits-and-charges",
             "schedule-charges", "Get-App", "product-and-campaigns",
             "upay-account-creation", "mtb-islamic-dps", "pin-reset", "send-money",
             "mobile-recharge", "cash-in-options", "make-payment", "upay-request-money",
             "transfer-fund", "donation", "remittance-service", "payoneer-service",
             "prepaid-card-process", "traffic-fine", "land-tax", "e-porcha", "dncc", "e-mutation",
             "nid-service", "toll-booth-payment", "education", "privacy-policy",
             "terms-and-condition", "privacy-policy-bhorosha"]
# where a CMS slug lives on the website, for citations
SLUG_URL = {"home": "/", "Cash-Out": "/products/Cash-Out", "Pay-Bill": "/products/Pay-Bill",
            "Add-Money": "/products/Add-Money", "Cash-in": "/ProductServices/Cash-in",
            "cash-in-options": "/products/cash-in-options", "make-payment": "/products/make-payment",
            "prepaid-card-process": "/products/prepaid-card-process",
            "transfer-fund": "/products/utility/transfer-fund", "education": "/products/utility/education",
            "remittance-service": "/ProductServices/remittance-service",
            "privacy-policy": "/ProductServices/privacy-policy",
            "terms-and-condition": "/ProductServices/terms-and-condition",
            "privacy-policy-bhorosha": "/ProductServices/privacy-policy-bhorosha",
            "Service-location": "/service-location", "discontinued-agent": "/discontinued-agents",
            "faq": "/need-help", "Navigation": "/need-help", "Footer": "/",
            "Newsroom": "/Media", "Media-Contact": "/Media", "Home-Slider": "/",
            "Partner-with-us": "/partners", "product-and-campaigns": "/", "Get-App": "/"}
SEEDS = ["/", "/limits-and-charges", "/schedule-charges", "/need-help", "/who-we-are",
         "/Latest-offer", "/Blog", "/Media", "/partners", "/prepaid-card", "/card-campaign",
         "/service-location", "/discontinued-agents", "/ProductServices/privacy-policy",
         "/ProductServices/terms-and-condition", "/ProductServices/privacy-policy-bhorosha"]
SKIP_PATHS = re.compile(r"^/(nav/|Footer$|_next/|api/|images/|media/)", re.I)
SKIP_KEYS = re.compile(r"image|icon|logo|banner|video|thumb|gif|svg|color|css|class|slug|"
                       r"url|link|^id$|_id$|order|position|status|template|created|updated", re.I)
OUT = Path(__file__).resolve().parents[1] / "data" / "upay_kb"
UA = "Mozilla/5.0 (BoloUpay-KB-builder; hackathon research; contact: team WALL-E)"
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
HREF_RE = re.compile(r'href="([^"]+)"')
TAG_RE = re.compile(r"<[^>]+>")
CHUNK_CHARS = 1200


# ---------------------------------------------------------------- crawling
def norm_path(href: str, page: str) -> str | None:
    url, _ = urldefrag(urljoin(BASE + page, href.strip()))
    u = urlparse(url)
    if u.netloc not in ("www.upaybd.com", "upaybd.com") or u.scheme not in ("http", "https"):
        return None
    path = re.sub(r"/+$", "", u.path) or "/"
    if SKIP_PATHS.search(path) or re.search(r"\.(png|jpe?g|svg|gif|pdf|webp|ico|css|js)$", path, re.I):
        return None
    return path


def links_in(page: str, raw_html: str, props: dict) -> set[str]:
    found = {norm_path(h, page) for h in HREF_RE.findall(raw_html)}

    def walk(x):  # CMS "slug url" / "link" fields point at other pages
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(v, str) and ("slug" in k.lower() or "link" in k.lower() or "url" in k.lower()):
                    found.add(norm_path(v, page))
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(props)
    return {p for p in found if p}


def fetch(client: httpx.Client, path: str) -> tuple[str, str | None, dict | None]:
    for attempt in range(3):
        try:
            r = client.get(BASE + path)
            if r.status_code == 404:
                return path, None, None
            r.raise_for_status()
            m = NEXT_RE.search(r.text)
            props = json.loads(m.group(1))["props"]["pageProps"] if m else None
            return path, r.text, props
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
            if attempt == 2:
                print(f"  ! {path}: {e}", file=sys.stderr)
            time.sleep(1 + attempt)
    return path, None, None


def crawl(max_pages: int = 400) -> dict[str, dict]:
    pages: dict[str, dict] = {}
    seen, frontier = set(SEEDS), list(SEEDS)
    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client, \
            ThreadPoolExecutor(max_workers=6) as pool:
        while frontier and len(pages) < max_pages:
            batch, frontier = frontier[:24], frontier[24:]
            for path, raw, props in pool.map(lambda p: fetch(client, p), batch):
                if raw is None or props is None:
                    continue
                pages[path] = props
                for nxt in links_in(path, raw, props):
                    if nxt not in seen:
                        seen.add(nxt)
                        frontier.append(nxt)
            print(f"  crawled {len(pages)} pages, {len(frontier)} queued")
            time.sleep(0.3)
    return pages


def slug_url(slug: str, site_paths: set[str]) -> str:
    if slug in SLUG_URL:
        return BASE + SLUG_URL[slug]
    for p in site_paths:  # e.g. /Latest-offer/sharetrip-offer
        if p.rsplit("/", 1)[-1].lower() == slug.lower():
            return BASE + p
    return f"{BASE}/services/details/{slug}"


def crawl_api(extra: set[str], max_pages: int = 400) -> dict[str, dict]:
    """CMS pages by slug; new slugs come from links inside each page."""
    pages: dict[str, dict] = {}
    seen = {s.lower() for s in API_SEEDS}
    frontier = list(API_SEEDS) + [s for s in extra if s.lower() not in seen]
    seen |= {s.lower() for s in extra}

    def get(client, slug):
        for attempt in range(3):
            try:
                r = client.get(API + slug)
                if r.status_code in (301, 404):
                    return slug, None
                r.raise_for_status()
                return slug, r.json()
            except (httpx.HTTPError, ValueError) as e:
                if attempt == 2:
                    print(f"  ! api {slug}: {e}", file=sys.stderr)
                time.sleep(1 + attempt)
        return slug, None

    with httpx.Client(headers={"User-Agent": UA}, timeout=30) as client, \
            ThreadPoolExecutor(max_workers=6) as pool:
        while frontier and len(pages) < max_pages:
            batch, frontier = frontier[:24], frontier[24:]
            for slug, data in pool.map(lambda x: get(client, x), batch):
                if not isinstance(data, dict):
                    continue
                pages[slug] = data
                for path in links_in("/", "", data):
                    nxt = path.rsplit("/", 1)[-1]
                    if nxt and nxt.lower() not in seen:
                        seen.add(nxt.lower())
                        frontier.append(nxt)
            print(f"  api: {len(pages)} pages, {len(frontier)} queued")
            time.sleep(0.3)
    return pages


# ---------------------------------------------------------------- flattening
CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)


def _row(m: re.Match) -> str:
    cells = [re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", c))).strip()
             for c in CELL_RE.findall(m.group(1))]
    return "\n" + " | ".join(cells) + "\n" if any(cells) else ""


def clean(s: str) -> str:
    s = re.sub(r"<tr[^>]*>(.*?)</tr>", _row, s, flags=re.S | re.I)  # one line per table row
    s = re.sub(r"<\s*(br|/p|/li|/tr|/h\d)\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<\s*li[^>]*>", "\n• ", s, flags=re.I)
    s = re.sub(r"<\s*/t[dh]\s*>", " | ", s, flags=re.I)
    s = html.unescape(TAG_RE.sub("", s)).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def is_bn(key: str) -> bool:
    k = key.lower()
    return k.endswith((" bn", "_bn", "bangla", "_bengali")) or k in ("bn", "bangla")


def is_text(key: str, v) -> bool:
    if not isinstance(v, str) or not v.strip() or SKIP_KEYS.search(key):
        return False
    if v.startswith(("/media/", "http://", "https://", "/")) and " " not in v.strip():
        return False  # an asset path or link, not prose
    return True


def table_row(d: dict) -> str | None:
    """A flat record (all scalar values), e.g. a charge row: one line.
    A question/answer record becomes "Q: ... / A: ..." in each language."""
    if not d or any(isinstance(v, (dict, list)) for v in d.values()):
        return None
    vals = {k: clean(str(v)) for k, v in d.items()
            if v not in ("", None) and not SKIP_KEYS.search(k) and is_text(k, str(v))}
    q = {k: v for k, v in vals.items() if k.lower().startswith("question")}
    a = {k: v for k, v in vals.items() if k.lower().startswith("answer")}
    if q and a:
        lines = []
        for lang_bn in (False, True):
            qq = next((v for k, v in q.items() if is_bn(k) == lang_bn), "")
            aa = next((v for k, v in a.items() if is_bn(k) == lang_bn), "")
            if qq or aa:
                lines.append(f"Q: {qq}\nA: {aa}")
        return "\n".join(dict.fromkeys(lines))
    cells, seen = [], set()
    for k, v in vals.items():
        if v in seen:  # "title bn" that only repeats the English
            continue
        seen.add(v)
        cells.append(f"{k.replace('_', ' ')}: {v}")
    return " | ".join(cells) if len(cells) >= 2 else None


def charge_rows(rows: list) -> list[tuple[str, str]] | None:
    """The charge calculator (service_name, transaction_type, calculation_type,
    charge, min/max): one section per service, one readable line per type."""
    if not rows or not all(isinstance(r, dict) and "service_name" in r and "charge" in r for r in rows):
        return None
    by_service: dict[str, list[str]] = {}
    for r in rows:
        charge, how = str(r.get("charge") or "").strip(), str(r.get("calculation_type") or "").strip()
        if how == "%":
            value = f"{charge}% of the amount"
        elif how.upper() in ("BDT", "TK"):
            value = f"Tk {charge}"
        elif how:
            value = f"{charge} (calculation: {how})"
        else:
            value = charge or "not listed"
        for k, label in (("min_charge", "minimum"), ("max_charge", "maximum")):
            if str(r.get(k) or "").strip():
                value += f", {label} Tk {r[k]}"
        kind = str(r.get("transaction_type") or "").strip()
        name = r["service_name"].strip()
        by_service.setdefault(name, []).append(f"{name}{f' ({kind})' if kind else ''}: charge {value}")
    return [(f"Charges › {name}", "\n".join(lines)) for name, lines in by_service.items()]


def flatten(x, heading: str, out: list[tuple[str, str]]) -> None:
    """Collect (section heading, text) pairs in reading order."""
    if isinstance(x, list):
        charges = charge_rows(x)
        if charges:
            out.extend(charges)
            return
        rows = [table_row(v) for v in x if isinstance(v, dict)]
        if rows and all(rows) and len(rows) >= 3:  # a table: keep rows together
            out.append((heading, "\n".join(rows)))
            return
        for v in x:
            flatten(v, heading, out)
        return
    if not isinstance(x, dict):
        return
    title = next((clean(x[k]) for k in ("title", "title_english", "name", "heading", "question")
                  if is_text(k, x.get(k))), None)
    here = f"{heading} › {title}" if title and heading and title not in heading else (title or heading)
    en, bn = [], []
    for k, v in x.items():
        if is_text(k, v):
            (bn if is_bn(k) else en).append(clean(v))
    lines = [t for t in dict.fromkeys(en + bn) if t and t != title]
    if lines:
        out.append((here, "\n".join(lines)))
    for k, v in x.items():
        if isinstance(v, (dict, list)) and not SKIP_KEYS.search(k):
            flatten(v, here, out)


def page_title(path: str, props: dict) -> str:
    page = (props.get("page") or {}).get("data") or props
    return clean(page.get("title_english") or props.get("title") or "") or \
        path.strip("/").split("/")[-1].replace("-", " ").title() or "Home"


def category(path: str) -> str:
    p = path.lower()
    for key, cat in (("limits", "charges_limits"), ("charge", "charges_limits"),
                     ("privacy", "policy"), ("terms", "policy"), ("need-help", "help_faq"),
                     ("latest-offer", "offer"), ("campaign", "offer"), ("blog", "press"),
                     ("media", "press"), ("services/details", "service"), ("products", "service"),
                     ("productservices", "service"), ("agent", "agents"), ("location", "agents"),
                     ("who-we-are", "company"), ("partner", "company"), ("card", "service")):
        if key in p:
            return cat
    return "general"


def chunk(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Pack sections into ~CHUNK_CHARS chunks; a long section is split by line."""
    chunks, head, first, buf = [], None, None, ""  # first: the chunk's first heading
    for h, text in sections:
        block = text if h == head else (f"## {h}\n{text}" if h else text)
        own = h.startswith("Charges ›") or (head or "").startswith("Charges ›")
        if buf and (len(buf) + len(block) > CHUNK_CHARS or (own and h != head)):
            chunks.append((first, buf))
            buf = ""
        while len(block) > CHUNK_CHARS * 1.5:  # a big table: split on line boundaries
            cut = block.rfind("\n", 0, CHUNK_CHARS)
            if cut < CHUNK_CHARS // 3:  # one long line: split at a space instead
                cut = block.rfind(" ", CHUNK_CHARS // 3, CHUNK_CHARS)
                cut = cut if cut > 0 else CHUNK_CHARS
            chunks.append((h, block[:cut]))
            block = (f"## {h} (cont.)\n" if h else "") + block[cut:].lstrip("\n")
        if not buf:
            first = h
        buf = f"{buf}\n{block}".strip()
        head = h
    if buf:
        chunks.append((first, buf))
    return chunks


def build(pages: dict[str, dict]) -> list[dict]:
    """``pages``: website URL -> page JSON."""
    records, seen_text = [], set()
    for url in sorted(pages):
        props = pages[url]
        path = url.split("#")[0][len(BASE):] or "/"
        title = page_title(path, props)
        sections: list[tuple[str, str]] = []
        flatten(props, "", sections)
        # drop the site chrome (nav menu, footer) repeated on every page
        sections = [(h, t) for h, t in sections
                    if len(t) > 15 and "lorem ipsum" not in t.lower()]
        for i, (h, text) in enumerate(chunk(sections)):
            key = hashlib.sha1(text.encode()).hexdigest()
            if key in seen_text:
                continue
            seen_text.add(key)
            records.append({
                "id": f"{path.strip('/').replace('/', '__') or 'home'}#{len(records)}",
                "url": url,
                "title": title,
                "section": h or title,
                "category": category(path),
                "lang": "bn+en" if re.search("[ঀ-৿]", text) else "en",
                "text": text,
            })
    return records


def main() -> None:
    started = dt.datetime.now(dt.timezone.utc)
    print(f"Crawling {BASE} ...")
    site = crawl()
    print(f"Crawling the CMS API {API} ...")
    api = crawl_api({p.rsplit("/", 1)[-1] for p in site if p != "/"})
    (OUT / "pages").mkdir(parents=True, exist_ok=True)
    for old in (OUT / "pages").glob("*.json"):
        old.unlink()
    pages: dict[str, dict] = {}
    for path, props in site.items():
        pages[BASE + path] = props
        name = "site__" + (path.strip("/").replace("/", "__") or "home")
        (OUT / "pages" / f"{name}.json").write_text(
            json.dumps({"url": BASE + path, "pageProps": props}, ensure_ascii=False, indent=1))
    for slug, data in api.items():
        url = slug_url(slug, set(site))
        # several slugs can live on one URL (home, slider, footer): keep each
        pages[f"{url}#cms:{slug}"] = data
        (OUT / "pages" / f"cms__{slug}.json").write_text(
            json.dumps({"url": url, "api": API + slug, "data": data}, ensure_ascii=False, indent=1))
    records = build(pages)
    for r in records:
        r["url"] = r["url"].split("#")[0]
    with (OUT / "kb.jsonl").open("w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    cats: dict[str, int] = {}
    for r in records:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    (OUT / "manifest.json").write_text(json.dumps({
        "source": BASE, "crawled_at": started.isoformat(timespec="seconds"),
        "site_pages": len(site), "cms_pages": len(api), "chunks": len(records),
        "chunks_by_category": cats, "urls": sorted({u.split("#")[0] for u in pages}),
        "note": "Public pages of upay's website, for retrieval in the Bolo agent. "
                "Offers and charges change; always cite the URL and crawl date.",
    }, ensure_ascii=False, indent=1))
    print(f"Done: {len(site)} site + {len(api)} CMS pages -> {len(records)} chunks in {OUT}")


if __name__ == "__main__":
    main()
