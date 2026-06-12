"""Change detection and re-indexing.

Weekly: re-crawl only schedule pages; on MD5 change, rebuild the "schedule"
collection. Monthly: full site re-crawl, re-indexing only changed pages.
State lives in data/logs/hashes.json:
  {"meta": {...timestamps...}, "pages": {url: {hash, page_type, last_crawled}}}
"""

import json
from datetime import datetime

from src.config import BASE_URL, COLLECTION_SCHEDULE, CRAWL_LIMIT, LOGS_DIR
from src import crawler, ingestion, vectorstore

HASHES_FILE = LOGS_DIR / "hashes.json"
UPDATE_LOG = LOGS_DIR / "update_log.txt"
DEFAULT_SCHEDULE_URLS = [f"{BASE_URL}/mapa-de-aulas/"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_update(message: str) -> None:
    with open(UPDATE_LOG, "a", encoding="utf-8") as fh:
        fh.write(f"[{_now()}] {message}\n")


def load_state() -> dict:
    if HASHES_FILE.exists():
        try:
            state = json.loads(HASHES_FILE.read_text(encoding="utf-8"))
            if "pages" in state:
                return state
        except (json.JSONDecodeError, OSError):
            pass
    return {"meta": {}, "pages": {}}


def save_state(state: dict) -> None:
    HASHES_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def record_pages(records: list[dict]) -> None:
    """Store hashes for freshly crawled+indexed records."""
    state = load_state()
    for rec in records:
        state["pages"][rec["url"]] = {
            "hash": rec["content_hash"],
            "page_type": rec["page_type"],
            "last_crawled": rec["crawled_at"],
        }
    save_state(state)


def schedule_urls() -> list[str]:
    state = load_state()
    urls = [u for u, e in state["pages"].items() if e.get("page_type") == "schedule"]
    return urls or DEFAULT_SCHEDULE_URLS


# ---------------------------------------------------------------------------
# Weekly schedule refresh (Mondays 07:00)
# ---------------------------------------------------------------------------

def update_schedule(force: bool = False) -> dict:
    """Re-crawl schedule pages; rebuild the schedule collection if changed."""
    log_update("Weekly schedule check starting")
    state = load_state()
    urls = schedule_urls()
    records = crawler.crawl_urls(urls)
    result = {"checked": len(urls), "crawled": len(records), "changed": False}

    if not records:
        log_update("Schedule check FAILED: could not crawl any schedule page")
        state["meta"]["last_schedule_check"] = _now()
        save_state(state)
        result["error"] = "crawl failed"
        return result

    changed = force or any(
        state["pages"].get(rec["url"], {}).get("hash") != rec["content_hash"]
        for rec in records
    )

    if changed:
        vectorstore.clear_collection(COLLECTION_SCHEDULE)
        stats = ingestion.ingest_records(records, replace=False)
        record_pages(records)
        state = load_state()
        state["meta"]["last_schedule_update"] = _now()
        log_update(
            f"Schedule CHANGED: re-indexed {stats['chunks']} chunks "
            f"from {stats['pages']} page(s)"
        )
        result.update(changed=True, chunks=stats["chunks"])
    else:
        log_update("Schedule check: no changes detected")

    state["meta"]["last_schedule_check"] = _now()
    save_state(state)
    return result


# ---------------------------------------------------------------------------
# Monthly full re-crawl (1st of the month, 06:00)
# ---------------------------------------------------------------------------

def full_recrawl(limit: int = CRAWL_LIMIT) -> dict:
    """Re-crawl the whole site and re-index only the pages whose hash changed."""
    log_update("Monthly full re-crawl starting")
    state = load_state()
    records = crawler.crawl_site(limit)

    changed_records, unchanged, report_lines = [], 0, []
    for rec in records:
        old = state["pages"].get(rec["url"], {}).get("hash")
        if old != rec["content_hash"]:
            changed_records.append(rec)
            status = "NEW" if old is None else "CHANGED"
            report_lines.append(f"{status}: {rec['url']} ({rec['page_type']})")
        else:
            unchanged += 1

    stats = {"pages": 0, "chunks": 0}
    if changed_records:
        stats = ingestion.ingest_records(changed_records, replace=True)
        record_pages(changed_records)

    state = load_state()
    state["meta"]["last_full_crawl"] = _now()
    if any(r["page_type"] == "schedule" for r in changed_records):
        state["meta"]["last_schedule_update"] = _now()
    save_state(state)

    report = LOGS_DIR / f"update_report_{datetime.now():%Y%m%d_%H%M%S}.txt"
    report.write_text(
        f"FIT IT full re-crawl report — {_now()}\n"
        f"Pages crawled: {len(records)}\n"
        f"Unchanged: {unchanged}\n"
        f"Changed/new: {len(changed_records)} ({stats['chunks']} chunks re-indexed)\n\n"
        + "\n".join(report_lines or ["(no changes)"]),
        encoding="utf-8",
    )
    log_update(
        f"Full re-crawl done: {len(records)} pages, {len(changed_records)} changed, "
        f"report: {report.name}"
    )
    return {"crawled": len(records), "changed": len(changed_records),
            "chunks": stats["chunks"], "report": str(report)}


def get_status() -> dict:
    """Freshness info for the UI."""
    state = load_state()
    meta = state["meta"]
    sched_pages = [e for e in state["pages"].values() if e.get("page_type") == "schedule"]
    last_sched_crawl = max((e["last_crawled"] for e in sched_pages), default=None)
    return {
        "last_schedule_update": meta.get("last_schedule_update"),
        "last_schedule_check": meta.get("last_schedule_check"),
        "last_full_crawl": meta.get("last_full_crawl"),
        "last_schedule_crawl": last_sched_crawl,
        "pages_indexed": len(state["pages"]),
    }
