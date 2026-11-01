from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DocumentInput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=500_000)


class SessionInput(StrictModel):
    title: str = Field(default="New chat", min_length=1, max_length=100)


class ChatInput(StrictModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    top_k: int = Field(default=5, ge=1, le=8)


class NoteInput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=50_000)


class SearchArgs(StrictModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=8)


class ReadArgs(StrictModel):
    document_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=6, ge=1, le=8)


class ListArgs(StrictModel):
    limit: int = Field(default=20, ge=1, le=30)


class Citation(BaseModel):
    id: str
    document_id: str
    title: str
    content: str
    page: int | None = None
    score: float = 0


class TraceItem(BaseModel):
    step: int
    tool: str
    detail: str


class ChatOutput(BaseModel):
    session_id: str
    answer: str
    citations: list[Citation]
    trace: list[TraceItem]
    mode: str
    elapsed_ms: int
