"""Query intent classification and routed semantic search."""

import re
import unicodedata

from src.config import (
    COLLECTION_GENERAL,
    COLLECTION_PRICING,
    COLLECTION_SCHEDULE,
)
from src import vectorstore

TOP_K = 5

# Accent-stripped keyword sets (queries are normalised before matching).
SCHEDULE_KEYWORDS = [
    "horario", "horarios", "que horas", "a que hora", "quando", "abre", "fecha",
    "abertura", "fecho", "encerra", "aula de", "aulas de", "mapa de aulas",
    "segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo",
    "manha", "tarde", "noite", "fim de semana", "feriado", "agenda", "timetable",
]
PRICING_KEYWORDS = [
    "preco", "precos", "plano", "planos", "mensalidade", "mensal", "anuidade",
    "custa", "custo", "valor", "valores", "pagamento", "pagar", "inscricao",
    "inscrever", "matricula", "taxa", "desconto", "pack", "tarifa", "euros",
    "assinatura", "fidelizacao", "cancelar", "cancelamento", "joia", "quanto",
]


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def classify_intent(query: str) -> str:
    """-> "schedule" | "pricing" | "general" via keyword scoring."""
    norm = _norm(query)
    schedule_score = sum(1 for kw in SCHEDULE_KEYWORDS if kw in norm)
    pricing_score = sum(1 for kw in PRICING_KEYWORDS if kw in norm)
    if "€" in query or re.search(r"\b\d+\s*eur", norm):
        pricing_score += 1
    if re.search(r"\b\d{1,2}[:h]\d{2}\b", norm):
        schedule_score += 1
    if schedule_score == 0 and pricing_score == 0:
        return "general"
    return "schedule" if schedule_score >= pricing_score else "pricing"


def _dedupe(results: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in results:
        key = (r["metadata"].get("source_url"), r["metadata"].get("chunk_index"))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


WEEKDAYS = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]


def _days_in_query(query: str) -> list[str]:
    norm = _norm(query)
    found = [d for d in WEEKDAYS if d in norm]
    if "fim de semana" in norm and not found:
        found = ["sabado", "domingo"]
    return found


def retrieve(query: str, k: int = TOP_K) -> tuple[str, list[dict]]:
    """Route by intent, search, and return (intent, top chunks).

    Schedule intent: the timetable is only ~8 chunks (one per weekday), so we
    fetch them all and deterministically rank chunks for any weekday named in
    the query first — semantic distance alone confuses similar day chunks.
    Schedule/pricing intents top up with general results (e.g. opening hours
    live on the contacts page). General intent merges all three collections.
    """
    intent = classify_intent(query)

    norm_q = _norm(query)
    if intent == "schedule":
        sched = vectorstore.query(COLLECTION_SCHEDULE, query, 12)
        days = _days_in_query(query)
        # Opening-hours questions ("a que horas abre?") need the contacts
        # page, not the whole class timetable — keep the context lean.
        hours_only = (
            any(w in norm_q for w in ("abre", "fecha", "funcionamento",
                                      "abertura", "fecho", "encerra"))
            and "aula" not in norm_q and "modalidade" not in norm_q
        )
        if hours_only:
            sched = sched[:2]
            # Query expansion: the answer lives under "horário de
            # funcionamento" on the contacts page.
            query = f"{query} horário de funcionamento abertura encerramento"
        elif days:
            matching = [r for r in sched
                        if any(d in _norm(r["metadata"].get("section_name", ""))
                               for d in days)]
            rest = [r for r in sched if r not in matching]
            sched = (matching + rest)[:6]
        else:
            sched = sched[:8]  # whole week, e.g. "horário desta semana"
        extra = vectorstore.query(COLLECTION_GENERAL, query, 4)
        results = _dedupe(sched + sorted(extra, key=lambda r: r["distance"]))[:10]
    elif intent == "pricing":
        primary = vectorstore.query(COLLECTION_PRICING, query, k + 1)
        extra = vectorstore.query(COLLECTION_GENERAL, query, 3)
        results = _dedupe(primary + sorted(extra, key=lambda r: r["distance"]))[: k + 3]
    else:
        merged = (
            vectorstore.query(COLLECTION_GENERAL, query, k)
            + vectorstore.query(COLLECTION_SCHEDULE, query, 3)
            + vectorstore.query(COLLECTION_PRICING, query, 3)
        )
        results = _dedupe(sorted(merged, key=lambda r: r["distance"]))[: k + 1]

    return intent, results


def format_context(results: list[dict]) -> str:
    """Render retrieved chunks as a context block for the LLM prompt."""
    if not results:
        return "(nenhuma informação relevante encontrada)"
    blocks = []
    for i, r in enumerate(results, 1):
        meta = r["metadata"]
        blocks.append(
            f"--- Excerto {i} (fonte: {meta.get('source_url', '?')}, "
            f"secção: {meta.get('section_name', '?')}) ---\n{r['text']}"
        )
    return "\n\n".join(blocks)
