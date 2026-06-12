"""Crawling of fitit.pt: Firecrawl REST API with a BeautifulSoup fallback.

URLs are discovered through the WordPress sitemap (deterministic and cheap),
filtered against EXCLUDE_URL_PATTERNS and prioritised so that the schedule,
pricing and class pages always fit inside the crawl budget.
"""

import hashlib
import re
import time
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.config import (
    BASE_URL,
    CRAWL_LIMIT,
    CLASSES_SLUGS,
    EXCLUDE_URL_PATTERNS,
    FIRECRAWL_API_KEY,
    LOGS_DIR,
    PRICING_SLUGS,
    PRIORITY_SLUGS,
    RAW_DIR,
    SCHEDULE_SLUGS,
)

CRAWL_LOG = LOGS_DIR / "crawl_log.txt"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 FitItChatbotCrawler/1.0"
)
FIRECRAWL_ENDPOINTS = [
    "https://api.firecrawl.dev/v2/scrape",
    "https://api.firecrawl.dev/v1/scrape",
]

DAY_NAMES = [
    "segunda", "terça", "terca", "quarta", "quinta", "sexta",
    "sábado", "sabado", "domingo",
]
TIME_RE = re.compile(r"\b\d{1,2}[:hH]\d{2}\b")


def log_crawl(message: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(CRAWL_LOG, "a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {message}\n")


def slug_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return "home"
    return re.sub(r"[^a-z0-9-]+", "-", path.lower()).strip("-")


def is_excluded(url: str) -> bool:
    low = url.lower()
    return any(pat in low for pat in EXCLUDE_URL_PATTERNS)


def md5_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# URL discovery
# ---------------------------------------------------------------------------

def _fetch_sitemap_locs(url: str) -> list[str]:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        return re.findall(r"<loc>(.*?)</loc>", resp.text)
    except requests.RequestException as exc:
        log_crawl(f"SITEMAP ERROR {url}: {exc}")
        return []


def discover_urls(limit: int = CRAWL_LIMIT) -> list[str]:
    """Build a prioritised, filtered URL list from the WordPress sitemaps."""
    index = _fetch_sitemap_locs(f"{BASE_URL}/sitemap.xml")
    page_urls: list[str] = []
    post_urls: list[str] = []
    for sitemap in index:
        if "users" in sitemap or "taxonomies" in sitemap or "elementskit" in sitemap:
            continue
        locs = [u for u in _fetch_sitemap_locs(sitemap) if not is_excluded(u)]
        if "posts-post-" in sitemap:
            post_urls.extend(locs)
        else:
            page_urls.extend(locs)

    if not page_urls and not post_urls:
        # Sitemap unavailable: fall back to the homepage plus known sections.
        log_crawl("SITEMAP UNAVAILABLE - falling back to priority slugs only")
        page_urls = [f"{BASE_URL}/{slug}/".replace("//", "/").replace(":/", "://")
                     for slug in PRIORITY_SLUGS]

    by_slug = {slug_from_url(u): u for u in page_urls}
    ordered: list[str] = []
    for slug in PRIORITY_SLUGS:
        key = slug_from_url(f"{BASE_URL}/{slug}") if slug else "home"
        if key in by_slug:
            ordered.append(by_slug.pop(key))
    ordered.extend(by_slug.values())          # remaining non-blog pages
    # Newest blog posts last in the sitemap -> reverse so newest fill first.
    ordered.extend(reversed(post_urls))

    seen, final = set(), []
    for u in ordered:
        if u not in seen:
            seen.add(u)
            final.append(u)
    return final[:limit]


# ---------------------------------------------------------------------------
# Firecrawl scraping (REST, with retries) + BeautifulSoup fallback
# ---------------------------------------------------------------------------

def firecrawl_scrape(url: str, max_retries: int = 3) -> dict | None:
    """Scrape one URL via Firecrawl. Returns {markdown, title, status_code} or None."""
    payload = {"url": url, "formats": ["markdown"], "onlyMainContent": True}
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }
    for endpoint in FIRECRAWL_ENDPOINTS:
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(endpoint, json=payload, headers=headers, timeout=90)
                if resp.status_code == 429:
                    wait = min(2 ** attempt * 5, 60)
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        wait = min(int(retry_after) + 1, 90)
                    log_crawl(f"FIRECRAWL 429 on {url}, waiting {wait}s")
                    time.sleep(wait)
                    continue
                if resp.status_code in (401, 402, 404):
                    log_crawl(f"FIRECRAWL {resp.status_code} at {endpoint} for {url}")
                    break  # try next endpoint version
                resp.raise_for_status()
                body = resp.json()
                data = body.get("data", body)
                markdown = data.get("markdown", "")
                meta = data.get("metadata", {}) or {}
                if not markdown.strip():
                    return None
                return {
                    "markdown": markdown,
                    "title": meta.get("title", ""),
                    "status_code": int(meta.get("statusCode") or 200),
                    "scraper": "firecrawl",
                }
            except (requests.RequestException, ValueError) as exc:
                wait = 2 ** attempt
                log_crawl(f"FIRECRAWL attempt {attempt} failed for {url}: {exc}; retry in {wait}s")
                time.sleep(wait)
    return None


_BS4_STRIP_TAGS = ["script", "style", "noscript", "header", "footer", "nav",
                   "form", "iframe", "svg", "button", "aside"]
_BS4_STRIP_PATTERNS = re.compile(
    r"cookie|consent|menu|navbar|breadcrumb|sidebar|widget|social|share|"
    r"site-header|site-footer|elementor-location-header|elementor-location-footer",
    re.I,
)


def bs4_scrape(url: str) -> dict | None:
    """Fallback scraper: requests + BeautifulSoup -> rough markdown."""
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=45)
        status = resp.status_code
        resp.raise_for_status()
    except requests.RequestException as exc:
        log_crawl(f"BS4 ERROR {url}: {exc}")
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else ""
    for tag in soup(_BS4_STRIP_TAGS):
        tag.decompose()
    for tag in soup.find_all(attrs={"class": _BS4_STRIP_PATTERNS}):
        tag.decompose()
    for tag in soup.find_all(attrs={"id": _BS4_STRIP_PATTERNS}):
        tag.decompose()

    root = soup.find("main") or soup.body or soup
    lines: list[str] = []
    for el in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"]):
        if el.name == "table":
            for row in el.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
                if any(cells):
                    lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
        elif el.name == "li":
            text = el.get_text(" ", strip=True)
            if text:
                lines.append(f"- {text}")
        elif el.name.startswith("h"):
            text = el.get_text(" ", strip=True)
            if text:
                lines.append(f"\n{'#' * int(el.name[1])} {text}\n")
        else:
            if el.find_parent("li") or el.find_parent("table"):
                continue
            text = el.get_text(" ", strip=True)
            if text:
                lines.append(text + "\n")

    markdown = "\n".join(lines).strip()
    if not markdown:
        return None
    return {"markdown": markdown, "title": title, "status_code": status, "scraper": "bs4"}


# ---------------------------------------------------------------------------
# Page classification
# ---------------------------------------------------------------------------

def classify_page_type(url: str, title: str, markdown: str) -> str:
    slug = slug_from_url(url)
    low_md = unicodedata.normalize("NFKD", markdown.lower())
    low_md = "".join(c for c in low_md if not unicodedata.combining(c))

    # Slug hints first: they are authoritative for known pages.
    if slug in SCHEDULE_SLUGS or "horario" in slug or "mapa-de-aulas" in slug:
        return "schedule"
    if slug in PRICING_SLUGS:
        return "pricing"
    if slug in CLASSES_SLUGS or slug.startswith("modalidade-"):
        return "classes"
    if slug == "contactos":
        return "contact"
    if slug == "quem-somos":
        return "about"
    if slug in ("politica-de-privacidade", "condicoes-contratuais"):
        return "legal"
    if slug == "blog":
        return "blog"
    if slug in ("home", "servicos"):
        # /servicos/ lists per-day opening hours of sub-services (nutrition,
        # massages, hairdresser...) which look like a timetable but are not.
        return "general"

    # Content heuristics for unknown pages. Schedule needs near-full weekday
    # coverage AND many times (services pages list opening hours too).
    weekdays = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
    days_found = sum(1 for d in weekdays if d in low_md)
    times_found = len(TIME_RE.findall(markdown))
    if days_found >= 6 and times_found >= 12:
        return "schedule"
    if markdown.count("€") >= 2 and any(k in low_md for k in ("plano", "mensal", "preco")):
        return "pricing"
    return "general"


# ---------------------------------------------------------------------------
# Saving and orchestration
# ---------------------------------------------------------------------------

def save_page(record: dict) -> str:
    """Write one crawled page to data/raw/<slug>.md with frontmatter."""
    path = RAW_DIR / f"{record['slug']}.md"
    front = "\n".join([
        "---",
        f"source_url: {record['url']}",
        f"title: {record['title']}",
        f"page_type: {record['page_type']}",
        f"is_schedule: {str(record['page_type'] == 'schedule').lower()}",
        f"scraper: {record['scraper']}",
        f"status_code: {record['status_code']}",
        f"crawled_at: {record['crawled_at']}",
        f"content_hash: {record['content_hash']}",
        "---",
        "",
    ])
    path.write_text(front + record["markdown"], encoding="utf-8")
    return str(path)


def crawl_url(url: str) -> dict | None:
    """Scrape one URL (Firecrawl first, BeautifulSoup fallback) into a record."""
    result = firecrawl_scrape(url)
    if result is None:
        log_crawl(f"FALLBACK to BeautifulSoup for {url}")
        result = bs4_scrape(url)
    if result is None:
        log_crawl(f"FAILED {url} (both scrapers)")
        return None

    page_type = classify_page_type(url, result["title"], result["markdown"])
    record = {
        "url": url,
        "slug": slug_from_url(url),
        "title": result["title"],
        "markdown": result["markdown"],
        "page_type": page_type,
        "status_code": result["status_code"],
        "scraper": result["scraper"],
        "content_hash": md5_hash(result["markdown"]),
        "crawled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    record["filepath"] = save_page(record)
    flag = " [SCHEDULE PAGE]" if page_type == "schedule" else ""
    log_crawl(
        f"OK {url} status={record['status_code']} type={page_type} "
        f"scraper={record['scraper']} chars={len(record['markdown'])}{flag}"
    )
    return record


def crawl_urls(urls: list[str]) -> list[dict]:
    records = []
    for url in urls:
        rec = crawl_url(url)
        if rec:
            records.append(rec)
    return records


def crawl_site(limit: int = CRAWL_LIMIT) -> list[dict]:
    """Full site crawl: discover via sitemap, scrape every URL, save to data/raw."""
    log_crawl(f"=== CRAWL START (limit={limit}) ===")
    urls = discover_urls(limit)
    log_crawl(f"Discovered {len(urls)} URLs after filtering")
    records = crawl_urls(urls)
    n_sched = sum(1 for r in records if r["page_type"] == "schedule")
    log_crawl(f"=== CRAWL DONE: {len(records)}/{len(urls)} pages, {n_sched} schedule page(s) ===")
    return records
