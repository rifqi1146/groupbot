from rag.loader import load_local_contexts

async def retrieve_context(query: str) -> list[str]:
    local_contexts = load_local_contexts()

    results = []

    for ctx in local_contexts:
        if query.lower() in ctx.lower():
            results.append(ctx)

    return results[:5]