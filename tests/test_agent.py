import asyncio
from dataclasses import replace
import json

import httpx
import pytest

from app.agent import Agent
from app.config import Settings
from app.database import Store
from app.providers import Provider, ProviderError
from app.retrieval import Retrieval


def tool(call_id, name, arguments):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def test_multiple_tool_calls_and_verified_citations(tmp_path):
    async def scenario():
        settings = Settings(data_dir=tmp_path)
        store = Store(settings.db_path)
        async with httpx.AsyncClient() as client:
            provider = Provider(settings, client)
            retrieval = Retrieval(settings, store, provider)
            doc = await retrieval.ingest("Release", "release.txt", [{"text": "Release requires a review in staging.", "page": 7}])
            chunk_id = store.document(doc["id"])["chunks"][0]["id"]
            live_settings = replace(settings, provider="openai", api_key="test")
            agent = Agent(live_settings, store, provider, retrieval)
            rounds = []

            async def fake_chat(messages, tools):
                rounds.append(messages.copy())
                if len(rounds) == 1:
                    return {"content": None, "tool_calls": [tool("a", "list_documents", {}), tool("b", "read_document", {"document_id": doc["id"]})]}
                assert messages[-3]["role"] == "assistant"
                assert len(messages[-3]["tool_calls"]) == 2
                assert [m["tool_call_id"] for m in messages[-2:]] == ["a", "b"]
                return {"content": f"Review is required [{chunk_id}] [c_fabricated]"}

            provider.chat = fake_chat
            result = await agent.run("What is the release process?", [], 5)
            assert len(rounds) == 2
            assert "c_fabricated" not in result["answer"]
            assert [c["id"] for c in result["citations"]] == [chunk_id]
            assert [t["tool"] for t in result["trace"]] == ["search_documents", "list_documents", "read_document"]
    asyncio.run(scenario())


def test_invalid_tool_arguments_bounded_loop_and_no_automatic_writes(tmp_path):
    async def scenario():
        settings = Settings(data_dir=tmp_path)
        store = Store(settings.db_path)
        async with httpx.AsyncClient() as client:
            provider = Provider(settings, client)
            retrieval = Retrieval(settings, store, provider)
            agent = Agent(replace(settings, provider="openai", api_key="test", max_agent_steps=2), store, provider, retrieval)
            response, _ = await agent.execute("search_documents", {"query": "hello", "top_k": -1})
            assert "error" in response
            response, _ = await agent.execute("send_email", {"to": "anyone@example.com"})
            assert "error" in response
            response, _ = await agent.execute("draft_note", {"title": "Draft", "content": "Content"})
            assert response["saved"] is False
            assert store.notes() == []
            calls = 0

            async def repeat(messages, tools):
                nonlocal calls
                calls += 1
                return {"tool_calls": [tool(str(calls), "search_documents", {"query": "hello"})]}

            provider.chat = repeat
            result = await agent.run("hello", [], 5)
            assert calls == 2
            assert "limit" in result["answer"]
            assert result["trace"][-1]["tool"] == "limit"
    asyncio.run(scenario())


def test_openai_adapter_embedding_order_and_tool_message():
    async def scenario():
        requests = []

        def handle(request):
            requests.append(request)
            assert request.headers["authorization"] == "Bearer secret-test-key"
            if request.url.path.endswith("embeddings"):
                return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0, 2]}, {"index": 0, "embedding": [3, 0]}]})
            body = json.loads(request.content)
            assert body["tool_choice"] == "auto"
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "Hello"}}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = Provider(Settings(provider="openai", api_key="secret-test-key"), client)
            assert await provider.embed(["a", "b"]) == [[1, 0], [0, 1]]
            assert (await provider.chat([{"role": "user", "content": "hi"}], []))["content"] == "Hello"
        assert len(requests) == 2
    asyncio.run(scenario())


def test_openai_error_is_sanitized():
    async def scenario():
        def handle(request):
            return httpx.Response(401, json={"error": "secret-test-key upstream sensitive details"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = Provider(Settings(provider="openai", api_key="secret-test-key"), client)
            with pytest.raises(ProviderError) as error:
                await provider.embed(["hello"])
            assert "secret-test-key" not in str(error.value)
            assert "authentication" in str(error.value)
    asyncio.run(scenario())


def test_upload_during_search_keeps_consistent_snapshot(tmp_path):
    async def scenario():
        settings = Settings(data_dir=tmp_path)
        store = Store(settings.db_path)
        async with httpx.AsyncClient() as client:
            provider = Provider(settings, client)
            retrieval = Retrieval(settings, store, provider)
            original = await retrieval.ingest("Original", "old.txt", [{"text": "release staging", "page": None}])
            embed = provider.embed

            async def upload_while_embedding(texts):
                provider.embed = embed
                await retrieval.ingest("New release", "new.txt", [{"text": "release release release", "page": None}])
                return await embed(texts)

            provider.embed = upload_while_embedding
            result = await retrieval.search("release", 5)
            assert store.counts()["document_count"] == 2
            assert result and all(row["document_id"] == original["id"] for row in result)
    asyncio.run(scenario())
