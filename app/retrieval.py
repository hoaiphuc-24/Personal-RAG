from collections import defaultdict
import hashlib
from io import BytesIO
import json
from pathlib import PurePosixPath

from pypdf import PdfReader

from .config import Settings
from .database import Store
from .providers import Provider, ProviderError
from .text import split_text


class DocumentError(ValueError):
    pass


def parse_file(filename: str, payload: bytes) -> list[dict]:
    extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if extension not in {".pdf", ".txt", ".md", ".markdown"}:
        raise DocumentError("Only PDF, TXT, and Markdown files are supported.")
    if extension != ".pdf":
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise DocumentError("Text files must use UTF-8 encoding.") from None
        return [{"text": text, "page": None}]
    try:
        reader = PdfReader(BytesIO(payload), strict=False)
        if reader.is_encrypted:
            raise DocumentError("The PDF is password-protected. Upload an unencrypted copy.")
        if len(reader.pages) > 200:
            raise DocumentError("PDF files are limited to 200 pages.")
        pages, total = [], 0
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            total += len(text)
            if total > 500_000:
                raise DocumentError("The document exceeds the 500,000-character text limit.")
            pages.append({"text": text, "page": i + 1})
        return pages
    except DocumentError:
        raise
    except Exception:
        raise DocumentError("Could not read the PDF. Check the file or convert it to TXT.") from None


class Retrieval:
    def __init__(self, settings: Settings, store: Store, provider: Provider):
        self.settings, self.store, self.provider = settings, store, provider

    async def ingest(self, title: str, filename: str, pages: list[dict]) -> dict:
        if sum(len(p["text"]) for p in pages) > 500_000:
            raise DocumentError("The document exceeds the 500,000-character text limit.")
        chunks = [{"content": content, "page": page.get("page")}
                  for page in pages for content in split_text(page["text"], self.settings.chunk_size, self.settings.chunk_overlap)]
        if not chunks:
            raise DocumentError("The file contains no text. Scanned PDFs require OCR before upload.")
        digest = hashlib.sha256(json.dumps(pages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        existing = self.store.by_digest(digest)
        if existing:
            return {k: v for k, v in existing.items() if k != "chunks"}
        counts = self.store.counts()
        if counts["document_count"] >= 200 or counts["chunk_count"] + len(chunks) > 10_000:
            raise DocumentError("The personal workspace limit of 200 documents / 10,000 passages has been reached. Delete documents you no longer need.")
        vectors = await self.provider.embed([title + "\n" + c["content"] for c in chunks])
        current = self.store.vector_rows()
        if current and vectors and len(current[0]["embedding"]) != len(vectors[0]):
            raise ProviderError("The embedding dimensions have changed. Choose a new DATA_DIR and re-import your documents.")
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk["embedding"] = vector
        result = self.store.add_document(title, filename, digest, chunks)
        return {k: v for k, v in result.items() if k != "chunks"}

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        rows = self.store.vector_rows()
        if not rows:
            return []
        query_vector = (await self.provider.embed([query]))[0]
        if any(len(row["embedding"]) != len(query_vector) for row in rows):
            raise ProviderError("The embeddings are incompatible. Choose a new DATA_DIR and re-import your documents.")
        snapshot_ids = {row["id"] for row in rows}
        lexical = [chunk_id for chunk_id in self.store.lexical_ids(query) if chunk_id in snapshot_ids]
        similarity = {row["id"]: sum(a * b for a, b in zip(query_vector, row["embedding"], strict=True)) for row in rows}
        vector_rank = sorted(similarity, key=similarity.get, reverse=True)
        # Offline hashing has no semantic understanding. Require a lexical match
        # so a hash collision cannot invent supporting evidence.
        if self.settings.provider == "demo":
            allowed = set(lexical)
        else:
            allowed = set(lexical) | {key for key, value in similarity.items() if value >= 0.25}
        vector_rank = [key for key in vector_rank if key in allowed][:24]
        fused = defaultdict(float)
        for ranking in (lexical, vector_rank):
            for rank, chunk_id in enumerate(ranking, start=1):
                fused[chunk_id] += 1 / (60 + rank)
        lookup = {row["id"]: row for row in rows}
        result = []
        for chunk_id in sorted(fused, key=fused.get, reverse=True)[:top_k]:
            row = lookup[chunk_id]
            result.append({k: row[k] for k in ("id", "document_id", "title", "content", "page")}
                          | {"score": round(fused[chunk_id], 6)})
        return result
