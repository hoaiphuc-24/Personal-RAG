# Personal AgenticRAG — Implementation Plan

## Goal
Build an independent project inspired by the FastAPI + retrieval + tool-loop architecture of
https://github.com/ShenSeanChen/launch-agentic-rag. Do not copy personal data or configuration
from the parent directory. The default experience is an English-language personal document assistant.

## Scope
- FastAPI backend; SQLite stores documents, chunks, embeddings, conversations, and notes.
- Upload text-based PDFs, Markdown, and TXT; split into overlapping chunks and preserve PDF page numbers.
- Hybrid retrieval: FTS5/BM25 and cosine similarity combined with reciprocal rank fusion.
- Offline demo: vector hashing, excerpt results, and a fixed workflow; clearly communicate its limitations.
- OpenAI: real embeddings and a bounded function-calling loop.
- Read tools: search_documents, list_documents, read_document; draft_note only creates a draft.
- Validate citations against chunks that were actually retrieved.
- English UI: chat, sources, tool activity log, library, conversations, and saved notes.
- English README, Docker Compose volume, sample configuration, tests, and CI.

## API Contract
- GET /api/health -> status, mode, project_name, owner_name, document_count, chunk_count, session_count
- GET /api/documents -> list[{id,title,filename,chunk_count,created_at}]
- POST /api/documents -> {title,content}; POST /api/documents/upload -> multipart file
- GET /api/documents/{id} -> document + chunks[{id,content,page,ordinal}]
- DELETE /api/documents/{id}; POST /api/demo/seed -> {added}
- GET /api/sessions -> list[{id,title,created_at,updated_at}]
- POST /api/sessions -> {title?}; GET /api/sessions/{id} -> session + messages
- POST /api/chat {message,session_id?,top_k?} -> {session_id,answer,citations,trace,mode,elapsed_ms}
- citations: [{id,document_id,title,content,page,score}]
- trace: [{step,tool,detail}] — operation log, not the model's internal reasoning.
- messages: [{role,content,citations,trace,created_at}]
- GET /api/notes -> list; POST /api/notes {title,content}; DELETE /api/notes/{id}
- Errors: {detail: string}; sensitive information is not returned to the browser.

## Sequence and Verification
1. [x] Review the reference repository, inspect the environment, and create PLAN.md.
2. [x] Build the database, retrieval, providers, and agent loop.
3. [x] Build the UI against the API contract (frontend specialist).
4. [x] Complete docs, Docker, CI, and sample configuration.
5. [x] Pass 15 tests: pipeline, PDF pages, uploads, session isolation, tool limits, citations, provider mock, and concurrency.
6. [x] Run the demo server; manually verify seeding, chat, citation dialog, and saving notes.

## Intentional Limitations
The personal version runs on loopback and has no authentication or multi-tenancy. Scanned PDFs require external OCR.
Email/calendar sending is not integrated; notes are saved only when the user clicks the button.
Do not automatically use API keys from the parent directory or call paid APIs in tests.
