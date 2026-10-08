"""Class model API clients (dobolyi.com ports 9001-9005).

Routes verified by probe_services.py / connectivity_report.md:
  - 9001 Vision LLM:      POST {base}/chat/completions   (emits `reasoning`; read `content`,
                                                          give generous max_tokens ~1200)
  - 9002 Text embeddings: POST {base}/v1/embeddings      (dim 2048)
  - 9003 Visual embeddings:POST {base}/embeddings        (NOTE: no /v1 prefix on this route!)
  - 9004 Multimodal rerank:POST {base}/v1/rerank         ({model, query, documents[]})
  - 9005 Document parsing: POST {base}/chat/completions  (dots.mocr - page image in, markdown out)

All clients raise ServiceError with scrubbed messages (never echo the API key).
"""
import base64
import json
import os
import urllib.error
import urllib.request

from config import (CLASS_API_KEY, LLM_BASE, TEXT_EMBED_BASE,
                    VISUAL_EMBED_BASE, RERANK_BASE, PARSE_BASE)


class ServiceError(Exception):
    """Scrubbed service error: generic message + optional request id; no secrets."""


def _post_json(url: str, payload: dict, timeout: int = 240) -> dict:
    req = urllib.request.Request(url, method="POST")
    req.add_header("Authorization", f"Bearer {CLASS_API_KEY}")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    data = json.dumps(payload).encode("utf-8")
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body = json.loads(e.read().decode("utf-8"))
            detail = str(body)[:300]
        except Exception:
            detail = str(e)[:200]
        raise ServiceError(f"service error {e.code} on {url} (details scrubbed)" + (f": {detail}" if detail else "")) from None
    except urllib.error.URLError as e:
        raise ServiceError(f"cannot reach {url}: {type(e.reason).__name__}") from None


def _get_json(url: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {CLASS_API_KEY}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ServiceError(f"service error {e.code} on {url}") from None


def _image_data_uri(path: str) -> str:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
    return f"data:image/{ext};base64,{b64}"


class _ModelsMixin:
    model_id: str
    _models_url: str

    def _resolve_model_id(self) -> str:
        try:
            models = _get_json(self._models_url).get("data", [])
            if models:
                return models[0]["id"]
        except ServiceError:
            pass
        return self.model_id


class ChatClient(_ModelsMixin):
    """Vision LLM (9001): chat completions; images as data-URI content parts."""

    model_id = "cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit"

    def __init__(self, base: str = LLM_BASE, max_tokens: int = 1400):
        self._base = base.rstrip("/")
        self._models_url = f"{self._base}/models"
        self.max_tokens = max_tokens

    def complete(self, messages: list[dict], max_tokens: int | None = None,
                 temperature: float = 0.0) -> str:
        """messages: OpenAI-style list. Returns the final `content` (reasoning skipped)."""
        model = self._resolve_model_id()
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature,
        }
        resp = _post_json(f"{self._base}/chat/completions", payload)
        msg = resp["choices"][0]["message"]
        content = msg.get("content")
        if not content:
            # Reasoning consumed the whole budget - retry once with more room.
            payload["max_tokens"] = (max_tokens or self.max_tokens) * 3
            resp = _post_json(f"{self._base}/chat/completions", payload)
            content = resp["choices"][0]["message"].get("content")
        return content or ""

    @staticmethod
    def image_part(path: str) -> dict:
        return {"type": "image_url", "image_url": {"url": _image_data_uri(path)}}

    @staticmethod
    def text_part(text: str) -> dict:
        return {"type": "text", "text": text}


class TextEmbedder(_ModelsMixin):
    """Text embeddings (9002): POST /v1/embeddings, dim 2048."""

    model_id = "nvidia/Nemotron-3-Embed-1B-BF16"

    def __init__(self, base: str = TEXT_EMBED_BASE):
        self._base = base.rstrip("/")
        self._models_url = f"{self._base}/v1/models"

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._resolve_model_id()
        resp = _post_json(f"{self._base}/v1/embeddings",
                          {"model": model, "input": texts if len(texts) > 1 else texts[0]})
        data = resp["data"]
        if isinstance(data, dict):  # single-input responses sometimes nest
            data = [data]
        return [d["embedding"] for d in data]


class VisualEmbedder(_ModelsMixin):
    """Visual/text embeddings (9003): POST /embeddings (NO /v1 prefix - verified 404 on /v1).

    Accepts text and/or images (multimodal). Image input: OpenAI-style content parts
    with data-URI image_url, matching Qwen3-VL-Embedding's vLLM format.
    """

    model_id = "Qwen/Qwen3-VL-Embedding-2B"

    def __init__(self, base: str = VISUAL_EMBED_BASE):
        self._base = base.rstrip("/")
        self._models_url = f"{self._base}/v1/models"

    def embed(self, texts: list[str] | None = None,
              images: list[str] | None = None) -> list[list[float]]:
        """Embed text and/or images into a shared space (dim 2048).

        Text-only: OpenAI-style `input` string/list (verified working).
        With images: vLLM EmbeddingChatInputRequest form - `input` is a chat
        message whose content carries Qwen-style image parts (data URIs).
        NOTE: the image path could not be re-verified end-to-end during the
        skeleton smoke test because the 9003 server went down mid-probe;
        the schema is confirmed from the server's own openapi.json.
        """
        model = self._resolve_model_id()
        images = images or []
        if images:
            content = [{"type": "image", "image": _image_data_uri(p)} for p in images]
            for t in (texts or []):
                content.append({"type": "text", "text": t})
            payload = {"model": model,
                       "input": [{"role": "user", "content": content}],
                       "encoding_format": "float"}
        else:
            inputs = texts or []
            if not inputs:
                raise ValueError("provide at least one text or image")
            payload = {"model": model,
                       "input": inputs[0] if len(inputs) == 1 else inputs,
                       "encoding_format": "float"}
        resp = _post_json(f"{self._base}/embeddings", payload)
        data = resp["data"]
        if isinstance(data, dict):
            data = [data]
        return [d["embedding"] for d in data]


class Reranker(_ModelsMixin):
    """Multimodal rerank (9004): POST /v1/rerank -> results sorted by score desc."""

    model_id = "Qwen/Qwen3-VL-Reranker-2B"

    def __init__(self, base: str = RERANK_BASE):
        self._base = base.rstrip("/")
        self._models_url = f"{self._base}/v1/models"

    def rerank(self, query: str, documents: list[str | dict]) -> list[dict]:
        """documents: plain strings (verified); dicts like {"text": ...} are
        reduced to their text. Image candidates: pass the page's text for now
        (image-carrying candidates to be wired when visual retrieval lands)."""
        model = self._resolve_model_id()
        docs = [d["text"] if isinstance(d, dict) else d for d in documents]
        resp = _post_json(f"{self._base}/v1/rerank",
                          {"model": model, "query": query, "documents": docs})
        results = resp.get("results", [])
        results.sort(key=lambda r: r.get("relevance_score", 0.0), reverse=True)
        return results


class Parser(_ModelsMixin):
    """Document parsing (9005, dots.mocr): page image -> structured markdown.

    Sends the page image with a layout-parsing prompt; expects the model's
    content field in response (which may include JSON layout blocks).
    """

    model_id = "dots.mocr"
    LAYOUT_PROMPT = (
        "Please output the layout information from the PDF image, including each "
        "layout element's bbox, its category, and the corresponding text content "
        "within the bbox. Categories: Caption, Footnote, Formula, List-item, "
        "Page-footer, Page-header, Picture, Section-header, Table, Text, Title. "
        "Format: formulas as LaTeX, tables as HTML, all other text as Markdown. "
        "Keep the original text (no translation); order elements in human reading "
        "order. Output a single JSON object."
    )

    def __init__(self, base: str = PARSE_BASE, max_tokens: int = 4000):
        self._base = base.rstrip("/")
        self._models_url = f"{self._base}/models"
        self.max_tokens = max_tokens

    def parse_page(self, image_path: str) -> str:
        model = self._resolve_model_id()
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": _image_data_uri(image_path)}},
                {"type": "text", "text": self.LAYOUT_PROMPT},
            ],
        }]
        payload = {"model": model, "messages": messages, "max_tokens": self.max_tokens}
        resp = _post_json(f"{self._base}/chat/completions", payload,
                          timeout=300)
        return resp["choices"][0]["message"].get("content") or ""
