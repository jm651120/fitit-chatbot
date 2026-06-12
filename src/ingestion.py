"""Cleaning, type-aware chunking and indexing of crawled pages.

Routing: schedule pages -> "schedule" collection, pricing pages -> "pricing",
everything else -> "general". Chunking strategy depends on page type so that
class times never get separated from class names and each membership plan
stays in one piece.
"""

import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import (
    COLLECTION_GENERAL,
    COLLECTION_PRICING,
    COLLECTION_SCHEDULE,
    PROCESSED_DIR,
    RAW_DIR,
)
from src import vectorstore

# ~500 tokens / 50 token overlap, approximated at 4 chars per token.
GENERAL_CHUNK_CHARS = 2000
GENERAL_OVERLAP_CHARS = 200

BOILERPLATE_FILE = PROCESSED_DIR / "boilerplate.json"

DAY_CANON = {
    "segunda": "Segunda-feira", "terca": "Terça-feira", "quarta": "Quarta-feira",
    "quinta": "Quinta-feira", "sexta": "Sexta-feira", "sabado": "Sábado",
    "domingo": "Domingo",
}

_COOKIE_NAV_RE = re.compile(
    r"cookie|consentimento|cookiebot|política de privacidade aqui|"
    r"utilizamos cookies|aceitar todos|gerir consentimento",
    re.I,
)
_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]+\)")


def _norm(text: str) -> str:
    """Lowercase and strip accents, for robust keyword matching."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


# ---------------------------------------------------------------------------
# Raw file parsing
# ---------------------------------------------------------------------------

def parse_raw_file(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    try:
        _, front, body = text.split("---", 2)
    except ValueError:
        return {}, text
    meta = {}
    for line in front.strip().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, body.strip()


def record_from_raw(path: Path) -> dict | None:
    meta, body = parse_raw_file(path)
    if not meta.get("source_url") or not body:
        return None
    return {
        "url": meta["source_url"],
        "slug": path.stem,
        "title": meta.get("title", ""),
        "markdown": body,
        "page_type": meta.get("page_type", "general"),
        "content_hash": meta.get("content_hash", ""),
        "crawled_at": meta.get("crawled_at", ""),
    }


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------

def _strip_blocks(text: str, page_type: str) -> str:
    """Remove the Cookiebot consent block (everything up to "Skip to content")
    and the site-wide footer ("TENS DÚVIDAS..." to the end). The footer holds
    the gym's address/phones, so it is KEPT on the contact page."""
    lines = text.splitlines()

    skip_idx = next(
        (i for i, l in enumerate(lines[:80]) if "skip to content" in l.lower()), None
    )
    if skip_idx is not None:
        lines = lines[skip_idx + 1:]

    if page_type != "contact":
        footer_idx = next(
            (i for i, l in enumerate(lines)
             if _norm(l.strip()).startswith("tens duvidas")), None
        )
        if footer_idx is not None:
            lines = lines[:footer_idx]

    return "\n".join(lines)


def clean_markdown(text: str, boilerplate: set[str] | None = None,
                   page_type: str = "general") -> str:
    text = _strip_blocks(text, page_type)
    text = _IMG_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)  # keep anchor text, drop URLs
    out = []
    prev = None
    for line in text.splitlines():
        stripped = line.strip()
        if _COOKIE_NAV_RE.search(stripped) and len(stripped) < 200:
            continue
        if boilerplate and page_type != "contact" and _norm(stripped) in boilerplate and stripped:
            continue
        if stripped and stripped == prev:  # collapse adjacent duplicates (carousels)
            continue
        prev = stripped if stripped else prev
        out.append(line.rstrip())
    cleaned = "\n".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def learn_boilerplate(bodies: list[str]) -> set[str]:
    """Lines repeated on >=50% of pages (menus, footers) are boilerplate."""
    if len(bodies) < 5:
        return set()
    freq: dict[str, int] = {}
    for body in bodies:
        for line in {_norm(l.strip()) for l in body.splitlines() if l.strip()}:
            if len(line) < 120:
                freq[line] = freq.get(line, 0) + 1
    threshold = max(3, len(bodies) // 2)
    boiler = {line for line, count in freq.items() if count >= threshold}
    BOILERPLATE_FILE.write_text(
        json.dumps(sorted(boiler), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return boiler


def load_boilerplate() -> set[str]:
    if BOILERPLATE_FILE.exists():
        return set(json.loads(BOILERPLATE_FILE.read_text(encoding="utf-8")))
    return set()


# ---------------------------------------------------------------------------
# Type-aware chunking
# ---------------------------------------------------------------------------

def _split_by_headings(text: str) -> list[tuple[str, str]]:
    """-> [(heading, section_text)] using markdown headings as boundaries."""
    sections, current_head, buf = [], "", []
    for line in text.splitlines():
        m = re.match(r"^#{1,6}\s+(.*)", line)
        if m:
            if buf and "".join(buf).strip():
                sections.append((current_head, "\n".join(buf).strip()))
            current_head, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if buf and "".join(buf).strip():
        sections.append((current_head, "\n".join(buf).strip()))
    return sections


def _recursive_chunks(text: str, size: int = GENERAL_CHUNK_CHARS,
                      overlap: int = GENERAL_OVERLAP_CHARS) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size, chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return [c for c in splitter.split_text(text) if c.strip()]


WEEKDAY_PT = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
              "Sexta-feira", "Sábado", "Domingo"]


def _parse_embedded_schedule(text: str) -> tuple[list[tuple[str, str]], str] | None:
    """fitit.pt embeds the weekly timetable as a JSON blob from its booking
    widget: {"HHMM": {weekday: [{turma, modalidade, inicio, fim, responsavel,
    estudio, date(unix), ...}]}}. Parsing it yields exact per-day chunks —
    far more reliable than scraping the rendered table.

    Returns (day_chunks, remaining_text) or None if no blob is found/parsable.
    """
    for line in text.splitlines():
        if len(line) < 3000 or '"turma"' not in line or '"inicio"' not in line:
            continue
        # Undo Firecrawl's markdown escaping (\[ \] \| \_ ... and \\ -> \):
        # dropping one backslash from every \X pair restores valid JSON,
        # including \\uXXXX -> \uXXXX.
        raw = re.sub(r"\\(.)", r"\1", line)
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            continue
        try:
            data = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            continue

        by_day: dict[int, dict] = defaultdict(lambda: {"date": None, "classes": []})
        for slot in data.values():
            if not isinstance(slot, dict):
                continue
            for classes in slot.values():
                if not isinstance(classes, list):
                    continue
                for c in classes:
                    if not isinstance(c, dict) or "inicio" not in c:
                        continue
                    try:
                        day_dt = datetime.fromtimestamp(int(c["date"]), tz=timezone.utc)
                    except (KeyError, ValueError, TypeError):
                        continue
                    entry = by_day[day_dt.weekday()]
                    entry["date"] = day_dt
                    entry["classes"].append(c)

        if not by_day:
            return None
        chunks = []
        for wd in sorted(by_day):
            info = by_day[wd]
            day_name = WEEKDAY_PT[wd]
            date_str = info["date"].strftime("%d/%m/%Y")
            classes = sorted(info["classes"], key=lambda c: c.get("inicio", ""))
            rows = []
            for c in classes:
                instr = (c.get("responsavel") or "").strip()
                rows.append(
                    f"- {c.get('inicio', '?')}-{c.get('fim', '?')} | "
                    f"{c.get('turma', '?')} ({c.get('modalidade', '?')})"
                    + (f" | instrutor: {instr}" if instr else "")
                    + (f" | {c.get('estudio', '')}" if c.get("estudio") else "")
                )
            body = (f"Horário de aulas FIT IT — {day_name} ({date_str}):\n"
                    + "\n".join(rows))
            chunks.append((day_name, body))
        remaining = "\n".join(l for l in text.splitlines() if l is not line and l != line)
        return chunks, remaining
    return None


def chunk_schedule(text: str, title: str) -> list[tuple[str, str]]:
    """Chunk a timetable by weekday, never separating a time from its class.

    -> [(section_name, chunk_text)]. Tries the embedded booking-widget JSON
    first, then weekday markers, then line-preserving splits.
    """
    parsed = _parse_embedded_schedule(text)
    if parsed:
        chunks, remaining = parsed
        remaining = re.sub(r"\n{3,}", "\n\n", remaining).strip()
        if len(remaining) > 300:
            chunks.append(("Informação adicional do horário", remaining[:4000]))
        return chunks

    norm_lines = [(line, _norm(line)) for line in text.splitlines()]
    day_indices = []
    for i, (line, norm) in enumerate(norm_lines):
        for key, canon in DAY_CANON.items():
            # A day marker line: short line containing the weekday name.
            if key in norm and len(norm) < 60:
                day_indices.append((i, canon))
                break

    chunks: list[tuple[str, str]] = []
    if len(day_indices) >= 3:
        intro = "\n".join(l for l, _ in norm_lines[: day_indices[0][0]]).strip()
        if intro:
            chunks.append(("Informação geral do horário", intro))
        for idx, (start, day) in enumerate(day_indices):
            end = day_indices[idx + 1][0] if idx + 1 < len(day_indices) else len(norm_lines)
            body = "\n".join(l for l, _ in norm_lines[start:end]).strip()
            if body:
                chunks.append((day, f"Horário FIT IT — {day}:\n{body}"))
        return chunks

    # Markdown table without per-day rows, or free text: keep rows intact.
    if len(text) <= 6000:
        return [(title or "Horário", text)]
    parts = _recursive_chunks(text, size=3000, overlap=300)
    return [(f"Horário (parte {i + 1})", p) for i, p in enumerate(parts)]


def chunk_pricing(text: str, title: str) -> list[tuple[str, str]]:
    """One chunk per plan/section; never split a plan's pricing details."""
    sections = _split_by_headings(text)
    if len(sections) <= 1:
        if len(text) <= 6000:
            return [(title or "Planos e preços", text)]
        return [(f"{title} (parte {i + 1})", p)
                for i, p in enumerate(_recursive_chunks(text, size=4000, overlap=200))]

    chunks: list[tuple[str, str]] = []
    for head, body in sections:
        section = f"## {head}\n{body}" if head else body
        # Merge tiny fragments into the previous section to keep plans whole.
        if len(section) < 200 and chunks:
            name, prev = chunks[-1]
            chunks[-1] = (name, prev + "\n\n" + section)
            continue
        if len(section) > 6000:
            # Split on blank lines only, so a markdown plan table never breaks.
            for i, part in enumerate(_recursive_chunks(section, size=4000, overlap=200)):
                chunks.append((f"{head or title} (parte {i + 1})", part))
        else:
            chunks.append((head or title or "Planos", section))
    return chunks


def chunk_classes(text: str, title: str) -> list[tuple[str, str]]:
    """One chunk per class/modality section."""
    sections = _split_by_headings(text)
    if len(sections) <= 1:
        if len(text) <= 3000:
            return [(title or "Modalidade", text)]
        return [(f"{title} (parte {i + 1})", p)
                for i, p in enumerate(_recursive_chunks(text))]
    chunks = []
    for head, body in sections:
        section = f"## {head}\n{body}" if head else body
        if len(section) < 120 and chunks:
            name, prev = chunks[-1]
            chunks[-1] = (name, prev + "\n\n" + section)
        else:
            chunks.append((head or title, section))
    return chunks


def chunk_general(text: str, title: str) -> list[tuple[str, str]]:
    return [(title or "Conteúdo", c) for c in _recursive_chunks(text)]


CHUNKERS = {
    "schedule": chunk_schedule,
    "pricing": chunk_pricing,
    "classes": chunk_classes,
    # Heading-based: keeps "horário de funcionamento" as its own focused
    # chunk instead of burying the opening hours among address/form text.
    "contact": chunk_classes,
}


def route_collection(page_type: str) -> str:
    if page_type == "schedule":
        return COLLECTION_SCHEDULE
    if page_type == "pricing":
        return COLLECTION_PRICING
    return COLLECTION_GENERAL


def build_chunks(record: dict, boilerplate: set[str] | None = None) -> list[dict]:
    """Clean one crawled record and produce chunk dicts ready for ChromaDB."""
    cleaned = clean_markdown(record["markdown"], boilerplate, record["page_type"])
    if not cleaned or len(cleaned) < 40:
        return []
    chunker = CHUNKERS.get(record["page_type"], chunk_general)
    pieces = chunker(cleaned, record.get("title", ""))
    chunks = []
    for i, (section, body) in enumerate(pieces):
        body = body.strip()
        if len(body) < 30:
            continue
        chunks.append({
            "text": body,
            "metadata": {
                "source_url": record["url"],
                "page_type": record["page_type"],
                "section_name": section[:120],
                "last_crawled": record.get("crawled_at", ""),
                "content_hash": record.get("content_hash", ""),
                "chunk_index": i,
            },
        })
    return chunks


def save_processed(record: dict, chunks: list[dict]) -> None:
    path = PROCESSED_DIR / f"{record['slug']}.md"
    parts = [f"<!-- {record['url']} | {record['page_type']} | "
             f"{len(chunks)} chunks -->\n"]
    for c in chunks:
        parts.append(f"\n## [{c['metadata']['section_name']}]\n{c['text']}\n")
    path.write_text("\n".join(parts), encoding="utf-8")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def ingest_records(records: list[dict], boilerplate: set[str] | None = None,
                   replace: bool = True) -> dict:
    """Chunk and index records; replace=True removes each page's old chunks first."""
    if boilerplate is None:
        boilerplate = load_boilerplate()
    stats = {"pages": 0, "chunks": 0, "by_collection": {}}
    for record in records:
        chunks = build_chunks(record, boilerplate)
        if not chunks:
            continue
        collection = route_collection(record["page_type"])
        if replace:
            vectorstore.delete_source(collection, record["url"])
        added = vectorstore.add_chunks(collection, chunks)
        save_processed(record, chunks)
        stats["pages"] += 1
        stats["chunks"] += added
        stats["by_collection"][collection] = stats["by_collection"].get(collection, 0) + added
    return stats


def ingest_all(reset: bool = True) -> dict:
    """Index every page in data/raw/, learning boilerplate across all pages."""
    records = []
    for path in sorted(RAW_DIR.glob("*.md")):
        rec = record_from_raw(path)
        if rec:
            records.append(rec)
    if not records:
        raise RuntimeError("No crawled pages found in data/raw/. Run the crawl first.")

    boilerplate = learn_boilerplate([r["markdown"] for r in records])
    if reset:
        for name in (COLLECTION_SCHEDULE, COLLECTION_PRICING, COLLECTION_GENERAL):
            vectorstore.clear_collection(name)
    return ingest_records(records, boilerplate, replace=not reset)
