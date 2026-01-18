import os

DOC_DIR = "data/rag_docs"

def load_local_contexts() -> list[str]:
    contexts = []

    for fname in os.listdir(DOC_DIR):
        if not fname.endswith(".md"):
            continue

        path = os.path.join(DOC_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            contexts.append(f.read())

    return contexts