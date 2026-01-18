from rag.loader import load_local_contexts

LOCAL_CONTEXTS = load_local_contexts()

async def retrieve_context(query: str, limit: int = 4) -> list[str]:
    results = []

    q = query.lower()

    for ctx in LOCAL_CONTEXTS:
        if q in ctx.lower():
            results.append(ctx)

        if len(results) >= limit:
            break

    return results