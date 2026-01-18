def build_rag_prompt(user_prompt: str, contexts: list[str]) -> str:
    if contexts:
        context_text = "\n\n".join(contexts)
        rule = (
            "Gunakan data sebagai referensi utama. "
            "Jika ada perbedaan dengan pengetahuan umum, prioritaskan search."
        )
    else:
        context_text = ""
        rule = (
            "Jika data tidak tersedia, "
            "jawab menggunakan pengetahuan umum dengan jujur, "
            "kamu adalah KiyoshiBot, bot asisten yg siap membantu,"
        )

    return f"""
{rule}

=== DATA (jika ada) ===
{context_text}
=== END DATA ===

Pertanyaan:
{user_prompt}
"""