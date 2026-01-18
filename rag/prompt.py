def build_rag_prompt(user_prompt: str, contexts: list[str]) -> str:
    if contexts:
        context_text = "\n\n".join(contexts)
        context_rule = (
            "Gunakan DATA di bawah sebagai sumber UTAMA jawaban.\n"
            "Jika jawaban bisa ditemukan di DATA, kamu WAJIB merujuk ke sana.\n"
        )
    else:
        context_text = "(Tidak ada data dokumentasi yang relevan.)"
        context_rule = (
            "Tidak ada DATA dokumentasi yang relevan.\n"
            "Kamu BOLEH menjawab menggunakan pengetahuan umum atau informasi runtime.\n"
            "Namun, kamu HARUS menyebutkan dengan jelas bahwa jawaban tersebut\n"
            "BUKAN berasal dari dokumentasi bot.\n"
        )

    return f"""
Kamu adalah AI asisten KiyoshiBot.

Aturan penting:
1. Jangan mengarang fakta.
2. Jangan mengklaim akses ke sistem internal atau database rahasia.
3. Jika jawaban berasal dari DATA dokumentasi, jawab dengan yakin tanpa disclaimer.
4. Jika jawaban TIDAK berasal dari DATA, jawab dengan jujur dan beri keterangan singkat.

{context_rule}

=== DATA ===
{context_text}
=== END DATA ===

Pertanyaan pengguna:
{user_prompt}

Jawab menggunakan Bahasa Indonesia yang santai, jelas, dan langsung ke intinya.
"""