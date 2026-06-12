"""One-time setup: crawl fitit.pt, then chunk and index everything.

Usage:
    python ingest.py                # full crawl + index
    python ingest.py --skip-crawl   # re-index existing data/raw files only
    python ingest.py --limit 30     # crawl fewer pages
"""

import argparse
import sys
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.config import CRAWL_LIMIT
from src import crawler, ingestion, updater, vectorstore


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl and index fitit.pt")
    parser.add_argument("--skip-crawl", action="store_true",
                        help="Skip crawling; re-index files already in data/raw/")
    parser.add_argument("--limit", type=int, default=CRAWL_LIMIT,
                        help=f"Max pages to crawl (default {CRAWL_LIMIT})")
    args = parser.parse_args()

    t0 = time.time()

    if not args.skip_crawl:
        print(f"[1/3] A rastrear fitit.pt (limite: {args.limit} páginas)...")
        records = crawler.crawl_site(limit=args.limit)
        schedule_pages = [r["url"] for r in records if r["page_type"] == "schedule"]
        print(f"      {len(records)} páginas guardadas em data/raw/")
        print(f"      Páginas de horário detetadas: {schedule_pages or 'NENHUMA (verificar!)'}")
    else:
        print("[1/3] Crawl ignorado (--skip-crawl)")

    print("[2/3] A limpar, dividir e indexar conteúdo...")
    stats = ingestion.ingest_all(reset=True)
    print(f"      {stats['pages']} páginas -> {stats['chunks']} chunks")
    for coll, n in sorted(stats["by_collection"].items()):
        print(f"        - {coll}: {n} chunks")

    print("[3/3] A registar hashes para o sistema de atualização automática...")
    records = []
    for path in sorted(crawler.RAW_DIR.glob("*.md")):
        rec = ingestion.record_from_raw(path)
        if rec:
            rec["crawled_at"] = rec.get("crawled_at", "")
            records.append({
                "url": rec["url"], "content_hash": rec["content_hash"],
                "page_type": rec["page_type"], "crawled_at": rec["crawled_at"],
            })
    updater.record_pages(records)

    counts = vectorstore.collection_counts()
    print(f"\nConcluído em {time.time() - t0:.0f}s. Coleções ChromaDB: {counts}")
    print("Próximo passo: streamlit run app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
