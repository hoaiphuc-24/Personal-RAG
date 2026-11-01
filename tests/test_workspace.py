from dataclasses import replace
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.config import Settings
from app.main import create_app
from app.providers import ProviderError
from app.text import split_text


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as connection:
        yield connection


def add_document(client, title="Release process", content="Before release, two people must review and run staging tests."):
    response = client.post("/api/documents", json={"title": title, "content": content})
    assert response.status_code == 201, response.text
    return response.json()


def test_empty_workspace_unknown_answer_and_ui(client):
    assert client.get("/api/health").json()["document_count"] == 0
    response = client.post("/api/chat", json={"message": "What was last quarter's revenue?"})
    assert response.status_code == 200
    assert response.json()["citations"] == []
    assert "No relevant information" in response.json()["answer"]
    page = client.get("/")
    assert page.status_code == 200
    assert "Personal AgenticRAG" in page.text
    assert '<html lang="en">' in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]


def test_ingest_chat_citations_persistence_and_delete(client):
    document = add_document(client)
    duplicate = add_document(client, title="Copy")
    assert duplicate["id"] == document["id"]
    assert client.get("/api/health").json()["document_count"] == 1
    response = client.post("/api/chat", json={"message": "What needs to happen before a release?"}).json()
    assert response["mode"] == "demo"
    assert len(response["citations"]) == 1
    citation = response["citations"][0]
    assert citation["document_id"] == document["id"]
    assert f"[{citation['id']}]" in response["answer"]
    session = client.get("/api/sessions/" + response["session_id"]).json()
    assert [m["role"] for m in session["messages"]] == ["user", "assistant"]
    assert session["messages"][1]["citations"] == response["citations"]
    assert client.delete("/api/documents/" + document["id"]).status_code == 200
    assert client.get("/api/health").json()["chunk_count"] == 0
    assert client.app.state.store.lexical_ids("release") == []
    new_response = client.post("/api/chat", json={"message": "release"}).json()
    assert new_response["citations"] == []


def test_reopen_workspace_persists(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as first:
        doc = add_document(first)
        turn = first.post("/api/chat", json={"message": "review"}).json()
    with TestClient(create_app(settings)) as second:
        assert second.get("/api/documents/" + doc["id"]).status_code == 200
        assert len(second.get("/api/sessions/" + turn["session_id"]).json()["messages"]) == 2


def test_sessions_are_separate_and_unknown_id_is_rejected(client):
    a = client.post("/api/sessions", json={"title": "Project A"}).json()
    b = client.post("/api/sessions", json={"title": "Project B"}).json()
    client.post("/api/chat", json={"session_id": a["id"], "message": "Question from A"})
    assert client.get("/api/sessions/" + b["id"]).json()["messages"] == []
    assert len(client.get("/api/sessions/" + a["id"]).json()["messages"]) == 2
    assert client.post("/api/chat", json={"session_id": "f" * 32, "message": "hello"}).status_code == 404
    assert client.post("/api/chat", json={"message": "   "}).status_code == 422
    assert client.post("/api/chat", json={"message": "hello", "top_k": 99}).status_code == 422


def test_upload_validation_seed_and_explicit_notes(client):
    content = "Operations guide: back up data every day.".encode()
    response = client.post("/api/documents/upload", files={"file": ("../../guide.MD", content, "text/markdown")})
    assert response.status_code == 201
    assert response.json()["filename"] == "guide.MD"
    assert client.post("/api/documents/upload", files={"file": ("bad.exe", b"abc")}).status_code == 400
    assert client.post("/api/documents/upload", files={"file": ("bad.pdf", b"not a pdf")}).status_code == 400
    assert client.post("/api/documents/upload", files={"file": ("bad.txt", b"\xff\xfe")}).status_code == 400
    assert client.post("/api/documents/upload", files={"file": ("empty.txt", b"   ")}).status_code == 400
    assert client.post("/api/demo/seed").json()["added"] == 3
    assert client.post("/api/demo/seed").json()["added"] == 0
    assert client.get("/api/notes").json() == []
    note = client.post("/api/notes", json={"title": "Note", "content": "Review checklist"}).json()
    assert len(client.get("/api/notes").json()) == 1
    assert client.delete("/api/notes/" + note["id"]).status_code == 200


def make_pdf(text="Text on page two", encrypted=False):
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 20 200 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_page_citations_and_password_rejection(client):
    response = client.post("/api/documents/upload", files={"file": ("guide.pdf", make_pdf())})
    assert response.status_code == 201, response.text
    details = client.get("/api/documents/" + response.json()["id"]).json()
    assert details["chunks"][0]["page"] == 2
    result = client.post("/api/chat", json={"message": "Text page two"}).json()
    assert result["citations"][0]["page"] == 2
    protected = client.post("/api/documents/upload", files={"file": ("secret.pdf", make_pdf(encrypted=True))})
    assert protected.status_code == 400


def test_limits_origins_and_host(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, max_upload_mb=1))) as client:
        response = client.post("/api/documents/upload", files={"file": ("big.txt", b"a" * (1024 * 1024 + 1))})
        assert response.status_code == 413
        response = client.post("/api/chat", json={"message": "hello"}, headers={"origin": "https://attacker.example"})
        assert response.status_code == 403
        assert client.get("/api/health", headers={"host": "attacker.example"}).status_code == 400


def test_embedding_spaces_do_not_mix(tmp_path):
    demo = Settings(data_dir=tmp_path)
    live = replace(demo, provider="openai", api_key="test")
    other = replace(live, embed_model="another-embedding")
    assert len({demo.db_path, live.db_path, other.db_path}) == 3


def test_split_preserves_unicode_and_has_bounded_chunks():
    text = ("Résumé café naïve coöperate: preserve Unicode text without losing content. " * 100).strip()
    pieces = split_text(text, 250, 40)
    assert all(0 < len(p) <= 250 for p in pieces)
    assert pieces[0].startswith("Résumé")
    assert pieces[-1].endswith("content.")


def test_failed_provider_does_not_save_half_turn(client):
    session = client.post("/api/sessions", json={}).json()

    async def fail(*args):
        raise ProviderError("OpenAI is not available.")

    client.app.state.agent.run = fail
    response = client.post("/api/chat", json={"message": "hello", "session_id": session["id"]})
    assert response.status_code == 502
    assert client.get("/api/sessions/" + session["id"]).json()["messages"] == []
