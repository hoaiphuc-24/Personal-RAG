FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt requirements-lock.txt ./
RUN pip install -r requirements.txt -c requirements-lock.txt
RUN useradd --create-home rag && mkdir -p /app/data && chown rag:rag /app/data
COPY --chown=rag:rag app ./app
COPY --chown=rag:rag static ./static
COPY --chown=rag:rag examples ./examples
USER rag
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
