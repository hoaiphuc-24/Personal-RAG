# Validation — 2026-10-07

- Windows, Python 3.12.0, dependencies from `requirements-lock.txt`.
- `python -m pytest`: **15 passed**, no real API key used.
- `python -m pip check`: no dependency conflicts.
- `python -m compileall -q app`: successful.
- `node --check static/app.js`: successful.
- `docker compose config --quiet`: valid configuration.
- Uvicorn ran locally at `127.0.0.1:8000`.
- Browser check: loaded 3 demo documents; asked about onboarding;
  opened a verbatim citation; saved and viewed a demo note.
- Reviewed and fixed an upload occurring while an embedding query was pending;
  added a regression test for the retrieval snapshot.
- Starlette TestClient emitted an httpx adapter deprecation warning.
  Tests still passed; the warning does not affect the runtime HTTP adapter.

## Not Verified

- Live OpenAI: the adapter was tested with mocked HTTP and the agent with a mock provider.
  The user's API key is required to verify answer quality and model permissions.
- Docker build/run: Docker CLI is available, but the Docker Engine was not running on the machine.
- GitHub Actions: a workflow was created but has not run on GitHub because the project was created locally.
- Retrieval has not been benchmarked on real work documents.

## Handoff Data

The local demo workspace contains 3 fictional documents, an onboarding test conversation, and a
`DEMO — Onboarding Checklist` note. Everything is under `data/`, which is gitignored. Automated
tests use temporary directories and do not read personal data from the parent directory.
