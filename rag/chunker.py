def chunk_text(text: str, max_size: int = 500):
    chunks = []
    buf = ""

    for line in text.splitlines():
        if len(buf) + len(line) > max_size:
            if buf.strip():
                chunks.append(buf.strip())
            buf = ""
        buf += line + "\n"

    if buf.strip():
        chunks.append(buf.strip())

    return chunks