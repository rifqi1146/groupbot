from pathlib import Path

RAG_DIR = Path("data/rag_docs")

def load_documents():
    docs = []
    if not RAG_DIR.exists():
        return docs

    for file in RAG_DIR.glob("*.md"):
        try:
            docs.append({
                "name": file.name,
                "content": file.read_text(encoding="utf-8")
            })
        except Exception:
            continue

    return docs