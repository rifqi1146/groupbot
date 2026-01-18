def build_rag_prompt(user_prompt: str, contexts: list[str]) -> str:
    if contexts:
        context_text = "\n\n".join(contexts)
    else:
        context_text = "Tidak ditemukan data relevan."

    return f"""
Kamu HARUS menjawab berdasarkan DATA di bawah.
Jika jawabannya tidak ada di DATA, katakan dengan jujur bahwa kamu tidak menemukannya.

=== DATA ===
{context_text}
=== END DATA ===

Pertanyaan:
{user_prompt}
"""