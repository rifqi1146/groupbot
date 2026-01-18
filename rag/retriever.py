from .loader import load_documents
from .chunker import chunk_text

_DOCS = load_documents()

def retrieve_context(query: str, limit: int = 3):
    if not query:
        return []

    q = query.lower()
    scored = []

    for doc in _DOCS:
        for chunk in chunk_text(doc["content"]):
            score = sum(1 for w in q.split() if w in chunk.lower())
            if score > 0:
                scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:limit]]