"""Text normalization shared by lexical retrieval and offline embeddings."""
import re
import unicodedata

STOPWORDS = set("va la cua cac nhung cho voi trong mot duoc co toi ban hay gi nao ve de khi thi o a the is are of to in on and or what how please about this that it me my".split())


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower().replace("đ", "d"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return [t for t in re.findall(r"[a-z0-9]+", text) if t not in STOPWORDS and len(t) > 1]


def split_text(text: str, size: int, overlap: int) -> list[str]:
    text = text.replace("\x00", "").strip()
    if not text:
        return []
    result, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + size // 2, end)
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            result.append(chunk)
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return result
