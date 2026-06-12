"""ChromaDB persistence: three collections (schedule / pricing / general)
with locally computed sentence-transformers embeddings."""

import hashlib

import chromadb

from src.config import ALL_COLLECTIONS, CHROMA_DIR, EMBEDDING_MODEL

_client = None
_embedder = None


def get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _client


def get_embedder():
    """Lazy-load the sentence-transformers model (downloads ~90 MB on first run)."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(EMBEDDING_MODEL)
    return _embedder


def embed_texts(texts: list[str]) -> list[list[float]]:
    return get_embedder().encode(texts, show_progress_bar=False, normalize_embeddings=True).tolist()


def get_collection(name: str):
    return get_client().get_or_create_collection(
        name=name, metadata={"hnsw:space": "cosine"}
    )


def _chunk_id(chunk: dict) -> str:
    meta = chunk["metadata"]
    raw = f"{meta['source_url']}::{meta['chunk_index']}::{meta['content_hash']}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def add_chunks(collection_name: str, chunks: list[dict]) -> int:
    """Embed and upsert chunks: [{text, metadata{source_url, page_type, ...}}]."""
    if not chunks:
        return 0
    coll = get_collection(collection_name)
    coll.upsert(
        ids=[_chunk_id(c) for c in chunks],
        documents=[c["text"] for c in chunks],
        embeddings=embed_texts([c["text"] for c in chunks]),
        metadatas=[c["metadata"] for c in chunks],
    )
    return len(chunks)


def delete_source(collection_name: str, source_url: str) -> None:
    """Remove every chunk that came from one page."""
    get_collection(collection_name).delete(where={"source_url": source_url})


def clear_collection(name: str) -> None:
    """Drop and recreate a collection (used by the weekly schedule refresh)."""
    client = get_client()
    try:
        client.delete_collection(name)
    except Exception:
        pass
    get_collection(name)


def query(collection_name: str, text: str, k: int = 5) -> list[dict]:
    """Semantic search in one collection -> [{text, metadata, distance}]."""
    coll = get_collection(collection_name)
    if coll.count() == 0:
        return []
    res = coll.query(
        query_embeddings=embed_texts([text]),
        n_results=min(k, coll.count()),
        include=["documents", "metadatas", "distances"],
    )
    out = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        out.append({"text": doc, "metadata": meta, "distance": dist,
                    "collection": collection_name})
    return out


def collection_counts() -> dict:
    return {name: get_collection(name).count() for name in ALL_COLLECTIONS}
