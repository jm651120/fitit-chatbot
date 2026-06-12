"""Re-apply page-type classification to already-crawled raw files (used after
tuning the classifier, to avoid re-crawling)."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.config import RAW_DIR
from src.crawler import classify_page_type
from src.ingestion import parse_raw_file

changed = 0
for path in sorted(RAW_DIR.glob("*.md")):
    meta, body = parse_raw_file(path)
    if not meta.get("source_url"):
        continue
    new_type = classify_page_type(meta["source_url"], meta.get("title", ""), body)
    if new_type != meta.get("page_type"):
        print(f"{path.name}: {meta.get('page_type')} -> {new_type}")
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"^page_type: .*$", f"page_type: {new_type}",
                      text, count=1, flags=re.M)
        text = re.sub(r"^is_schedule: .*$",
                      f"is_schedule: {str(new_type == 'schedule').lower()}",
                      text, count=1, flags=re.M)
        path.write_text(text, encoding="utf-8")
        changed += 1
print(f"reclassified: {changed} files")
