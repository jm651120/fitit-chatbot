"""Final validation: run the ten acceptance questions through the full RAG
pipeline (intent routing -> retrieval -> Groq generation) and print answers.

Usage: python scripts/validate.py [--followup]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src import generation, retrieval, vectorstore

QUESTIONS = [
    "Que aulas têm disponíveis?",
    "Quais são os preços dos planos?",
    "A que horas abre o ginásio?",
    "Têm personal training?",
    "Como me posso inscrever?",
    "Onde ficam localizados?",
    "Que aulas têm na segunda-feira de manhã?",
    "Aceitam pagamento mensal?",
    "Têm estacionamento?",
    "Têm aulas para iniciantes?",
]


def ask(question: str, history: list[dict]) -> dict:
    search_q = generation.rewrite_followup(question, history) if history else question
    intent, results = retrieval.retrieve(search_q)
    context = retrieval.format_context(results)
    out = generation.generate_answer(question, context, history)
    out["intent"] = intent
    out["n_chunks"] = len(results)
    out["search_q"] = search_q
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--followup", action="store_true",
                        help="Also test the conversational follow-up flow")
    args = parser.parse_args()

    print("Coleções:", vectorstore.collection_counts(), "\n")

    failures = 0
    for i, q in enumerate(QUESTIONS, 1):
        out = ask(q, [])
        status = "ERRO" if out["error"] else ("SEM INFO" if out["no_info"] else "OK")
        if out["error"]:
            failures += 1
        print(f"{'=' * 70}\n[{i}/10] {q}")
        print(f"  intent={out['intent']} chunks={out['n_chunks']} "
              f"model={out['model']} -> {status}")
        print(f"  R: {out['answer']}\n")
        time.sleep(6)  # free-tier TPM limits need breathing room between questions

    if args.followup:
        print(f"{'=' * 70}\nTeste de conversa (memória + follow-up):")
        history = []
        for q in ["Que aulas têm na segunda-feira?", "E ao sábado?"]:
            out = ask(q, history)
            print(f"\n  P: {q}\n  (pesquisa: {out['search_q']})\n  R: {out['answer']}")
            history.append({"role": "user", "content": q})
            history.append({"role": "assistant", "content": out["answer"]})

    print(f"\n{'=' * 70}\nValidação completa. Erros técnicos: {failures}/10")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
