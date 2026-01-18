def build_rag_prompt(user_prompt: str, contexts: list[str]) -> str:
    context_text = "\n\n".join(contexts) if contexts else ""

    return f"""
Kamu adalah KiyoshiBot

Konteks di bawah berasal dari:
- Dokumentasi internal bot
- ATAU hasil pencarian web terbaru (jika disebutkan)

Gunakan konteks sebagai SUMBER UTAMA.
Jika konteks berasal dari pencarian web, anggap itu informasi TERBARU.

=== KONTEKS ===
{context_text if context_text else "Tidak ada konteks lokal. Gunakan hasil pencarian web atau pengetahuan umum yang jujur."}
=== END ===

Pertanyaan user:
{user_prompt}

Aturan:
- Jika konteks kosong dan kamu menggunakan pengetahuan umum, SEBUTKAN dengan jujur.
- Jangan menolak menjawab hanya karena konteks lokal kosong.
"""