import hashlib
import json
import unicodedata


def normalize_question(question: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", question).split())


def compute_content_hash(question: str, answer: str, category: str) -> str:
    canonical = json.dumps(
        {"answer": answer, "category": category, "question": question},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
