"""HTTP boundary; document processing and agent logic live in services."""
from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from .config import ROOT
from .retrieval import parse_file
from .schemas import ChatInput, ChatOutput, DocumentInput, NoteInput, SessionInput

router = APIRouter(prefix="/api")


@router.get("/health")
async def health(request: Request):
    state = request.app.state
    return {"status": "ok", "mode": state.settings.provider,
            "project_name": state.settings.project_name, "owner_name": state.settings.owner_name,
            "embedding_model": state.settings.embedding_space, **state.store.counts()}


@router.get("/documents")
async def documents(request: Request):
    return request.app.state.store.documents()


@router.post("/documents", status_code=201)
async def add_document(body: DocumentInput, request: Request):
    state = request.app.state
    async with state.ingest_lock:
        return await state.retrieval.ingest(body.title, body.title + ".txt", [{"text": body.content, "page": None}])


@router.post("/documents/upload", status_code=201)
async def upload(request: Request, file: UploadFile):
    state = request.app.state
    filename = PurePosixPath((file.filename or "document.txt").replace("\\", "/")).name[:200]
    try:
        payload = await file.read(state.settings.max_upload_mb * 1024 * 1024 + 1)
        if len(payload) > state.settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, "File exceeds the size limit.")
        pages = await run_in_threadpool(parse_file, filename, payload)
        async with state.ingest_lock:
            return await state.retrieval.ingest(filename, filename, pages)
    finally:
        await file.close()


@router.get("/documents/{document_id}")
async def document(document_id: str, request: Request):
    document = request.app.state.store.document(document_id)
    if document is None:
        raise HTTPException(404, "Document not found.")
    return document


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str, request: Request):
    async with request.app.state.ingest_lock:
        if not request.app.state.store.delete_document(document_id):
            raise HTTPException(404, "Document not found.")
    return {"deleted": True}


@router.post("/demo/seed")
async def seed(request: Request):
    state = request.app.state
    async with state.ingest_lock:
        before = state.store.counts()["document_count"]
        for path in sorted((ROOT / "examples").glob("*.md")):
            await state.retrieval.ingest(path.stem, path.name, [{"text": path.read_text(encoding="utf-8"), "page": None}])
        return {"added": state.store.counts()["document_count"] - before}


@router.get("/sessions")
async def sessions(request: Request):
    return request.app.state.store.sessions()


@router.post("/sessions", status_code=201)
async def create_session(body: SessionInput, request: Request):
    return request.app.state.store.create_session(body.title)


@router.get("/sessions/{session_id}")
async def session(session_id: str, request: Request):
    result = request.app.state.store.session(session_id)
    if result is None:
        raise HTTPException(404, "Session not found.")
    return result


@router.post("/chat", response_model=ChatOutput)
async def chat(body: ChatInput, request: Request):
    state = request.app.state
    # Single-user workspace: serialize turns so two tabs cannot interleave history.
    async with state.chat_lock:
        if body.session_id:
            session = state.store.session(body.session_id)
            if session is None:
                raise HTTPException(404, "Session not found.")
        else:
            session = state.store.create_session(body.message[:80]) | {"messages": []}
        result = await state.agent.run(body.message, session["messages"], body.top_k)
        state.store.save_turn(session["id"], body.message, result["answer"], result["citations"], result["trace"])
        return {"session_id": session["id"], **result}


@router.get("/notes")
async def notes(request: Request):
    return request.app.state.store.notes()


@router.post("/notes", status_code=201)
async def add_note(body: NoteInput, request: Request):
    return request.app.state.store.add_note(body.title, body.content)


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str, request: Request):
    if not request.app.state.store.delete_note(note_id):
        raise HTTPException(404, "Note not found.")
    return {"deleted": True}
