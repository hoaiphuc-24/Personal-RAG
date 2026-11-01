"""Offline lexical vectors and an async OpenAI HTTP adapter."""
import asyncio
import hashlib
import math

import httpx

from .config import Settings
from .text import tokens


class ProviderError(Exception):
    """A sanitized upstream error safe to return to the user."""


def unit_vector(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values] if norm else values


class Provider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings, self.client = settings, client

    async def request(self, endpoint: str, body: dict) -> dict:
        for attempt in range(3):
            try:
                response = await self.client.post(
                    "https://api.openai.com/v1/" + endpoint,
                    headers={"Authorization": f"Bearer {self.settings.api_key}"}, json=body)
            except httpx.RequestError:
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise ProviderError("Could not connect to OpenAI. Check your network and try again.") from None
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            if not response.is_success:
                if response.status_code in {401, 403}:
                    message = "OpenAI authentication was rejected. Check your API key and model access."
                elif response.status_code == 429:
                    message = "OpenAI rate-limited the request or the account has run out of quota."
                else:
                    message = f"OpenAI returned HTTP {response.status_code}. Check the model name and try again."
                raise ProviderError(message)
            try:
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError
                return result
            except (ValueError, TypeError):
                raise ProviderError("OpenAI returned an invalid response format.") from None
        raise ProviderError("OpenAI is not available.")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self.settings.provider == "demo":
            vectors = []
            for text in texts:
                vector = [0.0] * 256
                for term in tokens(text):
                    digest = hashlib.sha256(term.encode()).digest()
                    index = int.from_bytes(digest[:4], "little") % len(vector)
                    vector[index] += 1.0 if digest[4] & 1 else -1.0
                vectors.append(unit_vector(vector))
            return vectors
        vectors = []
        for start in range(0, len(texts), 32):
            batch = texts[start:start + 32]
            response = await self.request("embeddings", {"model": self.settings.embed_model, "input": batch})
            try:
                data = sorted(response["data"], key=lambda item: item["index"])
                if [item["index"] for item in data] != list(range(len(batch))):
                    raise ValueError
                for item in data:
                    values = [float(v) for v in item["embedding"]]
                    if not values or not all(math.isfinite(v) for v in values) or not any(values):
                        raise ValueError
                    vectors.append(unit_vector(values))
            except (KeyError, TypeError, ValueError):
                raise ProviderError("OpenAI returned invalid embeddings.") from None
        if vectors and any(len(v) != len(vectors[0]) for v in vectors):
            raise ProviderError("Embedding dimensions are inconsistent.")
        return vectors

    async def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        response = await self.request("chat/completions", {
            "model": self.settings.chat_model, "messages": messages, "tools": tools,
            "tool_choice": "auto", "max_completion_tokens": 1600,
        })
        try:
            message = response["choices"][0]["message"]
            if not isinstance(message, dict):
                raise TypeError
            return message
        except (KeyError, IndexError, TypeError):
            raise ProviderError("OpenAI returned an invalid chat response.") from None
