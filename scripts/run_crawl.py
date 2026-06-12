import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src import crawler

records = crawler.crawl_site()
print("DONE:", len(records), "pages")
for r in records:
    if r["page_type"] == "schedule":
        print("SCHEDULE PAGE:", r["url"])
print("types:", {t: sum(1 for r in records if r["page_type"] == t)
                 for t in {r["page_type"] for r in records}})
