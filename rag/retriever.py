from typing import List

async def retrieve_context(
    query: str,
    documents: List[str],
    top_k: int = 3,
) -> List[str]:
    """
    Ambil konteks paling relevan dari dokumen lokal
    """

    query_l = query.lower()
    scored = []

    for doc in documents:
        score = 0
        for word in query_l.split():
            if word in doc.lower():
                score += 1

        if score > 0:
            scored.append((score, doc))

    scored.sort(reverse=True, key=lambda x: x[0])

    return [doc for _, doc in scored[:top_k]]