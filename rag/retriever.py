from handlers.gsearch import google_search

async def retrieve_context(query: str, local_contexts: list[str]) -> list[str]:
    # kalau dokumen lokal ada langsung pakai
    if local_contexts:
        return local_contexts

    # fallback ke Google Search
    ok, results = await google_search(query, limit=5)
    if not ok or not results:
        return []

    contexts = []
    for r in results:
        ctx = f"{r['title']}\n{r['snippet']}\nSumber: {r['link']}"
        contexts.append(ctx)

    return contexts