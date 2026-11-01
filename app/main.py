import asyncio
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .agent import Agent
from .api import router
from .config import ROOT, Settings, load_settings
from .database import Store
from .providers import Provider, ProviderError
from .retrieval import DocumentError, Retrieval


class LocalRequestGuard:
    """Bound request bodies including chunked uploads before multipart parsing."""
    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        origin = headers.get(b"origin")
        if origin:
            try:
                source = urlsplit(origin.decode("ascii"))
                allowed = source.scheme in {"http", "https"} and source.netloc == headers.get(b"host", b"").decode("ascii")
            except (ValueError, UnicodeError):
                allowed = False
            if not allowed:
                return await JSONResponse({"detail": "This origin is not allowed to access the workspace."}, status_code=403)(scope, receive, send)
        if scope["method"] in {"POST", "PUT", "PATCH"}:
            try:
                length = int(headers.get(b"content-length", b"0"))
            except ValueError:
                return await JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)(scope, receive, send)
            if length > self.limit:
                return await JSONResponse({"detail": "Request exceeds the size limit."}, status_code=413)(scope, receive, send)
            body = bytearray()
            while True:
                event = await receive()
                if event["type"] == "http.disconnect":
                    return
                body.extend(event.get("body", b""))
                if len(body) > self.limit:
                    return await JSONResponse({"detail": "Request exceeds the size limit."}, status_code=413)(scope, receive, send)
                if not event.get("more_body", False):
                    break
            sent = False

            async def replay():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            return await self.app(scope, replay, send)
        return await self.app(scope, receive, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        state = application.state
        state.settings = settings
        state.store = Store(settings.db_path)
        state.chat_lock, state.ingest_lock = asyncio.Lock(), asyncio.Lock()
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10)) as client:
            state.provider = Provider(settings, client)
            state.retrieval = Retrieval(settings, state.store, state.provider)
            state.agent = Agent(settings, state.store, state.provider, state.retrieval)
            yield

    application = FastAPI(title=settings.project_name, version="1.0.0", lifespan=lifespan,
                          description="A personal work-document assistant. Runs locally and supports demo and OpenAI modes.")
    application.add_middleware(LocalRequestGuard, limit=settings.max_upload_mb * 1024 * 1024 + 65536)
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @application.exception_handler(DocumentError)
    async def document_error(request: Request, exc: DocumentError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @application.exception_handler(ProviderError)
    async def provider_error(request: Request, exc: ProviderError):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @application.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    application.include_router(router)
    application.mount("/static", StaticFiles(directory=ROOT / "static", check_dir=False), name="static")

    @application.get("/", include_in_schema=False)
    async def index():
        return FileResponse(ROOT / "static" / "index.html")

    return application


app = create_app()
