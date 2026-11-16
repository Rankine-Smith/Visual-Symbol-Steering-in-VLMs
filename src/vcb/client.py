"""Async OpenAI Chat Completions client with disk cache and retries.

Cache key = sha256 of (model, prompt version, image sha256, params, repeat index), so re-runs are free
and interrupted runs resume. Each cache file holds the full raw record.
"""
import asyncio
import base64
import hashlib
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError

from .config import CACHE_DIR, ROOT

MAX_RETRIES = 12


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cache_key(**parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def cache_path(*, model: str, prompt_version: str, image_sha256: str, params: dict, detail: str,
               repeat: int = 0) -> Path:
    """Where the record for this exact call lives (exists only if the call was already made)."""
    key = cache_key(model=model, prompt_version=prompt_version, image_sha256=image_sha256,
                    params={**params, "detail": detail}, repeat=repeat)
    return CACHE_DIR / key[:2] / f"{key}.json"


class VLMClient:
    def __init__(self, max_concurrency: int = 8):
        load_dotenv(ROOT / ".env")
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit("OPENAI_API_KEY not set (expected in .env)")
        self.client = AsyncOpenAI(max_retries=0, timeout=120)
        # xAI (Grok) speaks the same Chat Completions API; key GROK_API_KEY in .env (never printed or logged).
        self.xai = (AsyncOpenAI(base_url="https://api.x.ai/v1", api_key=os.environ["GROK_API_KEY"], max_retries=0,
                                timeout=180) if os.environ.get("GROK_API_KEY") else None)
        self.sem = asyncio.Semaphore(max_concurrency)
        self.calls_made = 0
        self.cache_hits = 0

    def for_model(self, model: str) -> AsyncOpenAI:
        if model.startswith("grok"):
            if self.xai is None:
                raise SystemExit("GROK_API_KEY not set (expected in .env)")
            return self.xai
        return self.client

    async def complete(self, *, model: str, prompt_text: str, prompt_version: str, image_path: Path,
                       detail: str, params: dict, repeat: int = 0) -> dict:
        """One user message: image part first, then text part. No system message.

        Returns the raw record (from cache if available).
        """
        image_bytes = Path(image_path).read_bytes()
        image_sha = hashlib.sha256(image_bytes).hexdigest()
        cache_file = cache_path(model=model, prompt_version=prompt_version, image_sha256=image_sha,
                                params=params, detail=detail, repeat=repeat)
        key = cache_file.stem
        if cache_file.exists():
            self.cache_hits += 1
            rec = json.loads(cache_file.read_text())
            rec["cached"] = True
            return rec

        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode()
        messages = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url, "detail": detail}},
            {"type": "text", "text": prompt_text},
        ]}]

        async with self.sem:
            for attempt in range(MAX_RETRIES):
                try:
                    resp = await self.for_model(model).chat.completions.create(model=model, messages=messages,
                                                                               **params)
                    break
                except (RateLimitError, APIConnectionError, APITimeoutError) as e:
                    err = e
                except APIStatusError as e:
                    if e.status_code < 500:
                        raise
                    err = e
                if attempt == MAX_RETRIES - 1:
                    raise err
                await asyncio.sleep(min(60, 2 ** attempt) + random.random())
        self.calls_made += 1

        choice = resp.choices[0]
        rec = {
            "cache_key": key,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "response_id": resp.id,
            "model_requested": model,
            "model_returned": resp.model,
            "provider": "xai" if model.startswith("grok") else "openai",
            "system_fingerprint": resp.system_fingerprint,
            "prompt_version": prompt_version,
            "prompt_text": prompt_text,
            "image_path": str(Path(image_path).resolve().relative_to(ROOT)),
            "image_sha256": image_sha,
            "detail": detail,
            "params": params,
            "repeat": repeat,
            "content": choice.message.content,
            # Reasoning text, if the provider returns it (xAI reasoning models may); not used in scoring.
            "reasoning_content": getattr(choice.message, "reasoning_content", None),
            "finish_reason": choice.finish_reason,
            "logprobs": choice.logprobs.model_dump() if choice.logprobs else None,
            "usage": resp.usage.model_dump() if resp.usage else None,
        }
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec))
        tmp.replace(cache_file)
        rec["cached"] = False
        return rec


def cached_prompt_tokens(rec: dict) -> int:
    """Input tokens OpenAI served from its own prompt cache (billed at a discount)."""
    usage = rec.get("usage") or {}
    return int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)


def first_top_logprobs(rec: dict) -> list[dict]:
    """[{token, logprob}, ...] at the first output position, or [] if absent."""
    lp = rec.get("logprobs") or {}
    content = lp.get("content") or []
    if not content:
        return []
    return [{"token": t["token"], "logprob": t["logprob"]} for t in content[0].get("top_logprobs") or []]


# ---------------------------------------------------------------- generic cached calls (awareness phase)
# These are used by the awareness / reasoning modules. They do not change `complete()` or its cache keys.

def image_part(image_path: Path, detail: str) -> tuple[str, str]:
    """(data URL, sha256) for an image file."""
    image_bytes = Path(image_path).read_bytes()
    return ("data:image/png;base64," + base64.b64encode(image_bytes).decode(),
            hashlib.sha256(image_bytes).hexdigest())


def keyed_cache_path(key_parts: dict) -> Path:
    key = cache_key(**key_parts)
    return CACHE_DIR / key[:2] / f"{key}.json"


async def _with_retries(sem, fn):
    async with sem:
        for attempt in range(MAX_RETRIES):
            try:
                return await fn()
            except (RateLimitError, APIConnectionError, APITimeoutError) as e:
                err = e
            except APIStatusError as e:
                if e.status_code < 500:
                    raise
                err = e
            if attempt == MAX_RETRIES - 1:
                raise err
            await asyncio.sleep(min(60, 2 ** attempt) + random.random())


def _save_rec(cache_file: Path, rec: dict):
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec))
    tmp.replace(cache_file)


async def cached_chat(vc: "VLMClient", *, model: str, messages: list, params: dict, key_parts: dict,
                      meta: dict) -> dict:
    """Chat Completions call with an arbitrary message list. `key_parts` must identify the call fully
    (model, every prompt version, image sha256, params, any prior assistant turn, repeat)."""
    cache_file = keyed_cache_path(key_parts)
    if cache_file.exists():
        vc.cache_hits += 1
        return {**json.loads(cache_file.read_text()), "cached": True}
    resp = await _with_retries(vc.sem, lambda: vc.client.chat.completions.create(
        model=model, messages=messages, **params))
    vc.calls_made += 1
    choice = resp.choices[0]
    rec = {"cache_key": cache_file.stem, "key_parts": key_parts, **meta,
           "timestamp": datetime.now(timezone.utc).isoformat(), "response_id": resp.id,
           "model_requested": model, "model_returned": resp.model, "system_fingerprint": resp.system_fingerprint,
           "params": params, "content": choice.message.content, "finish_reason": choice.finish_reason,
           "logprobs": choice.logprobs.model_dump() if choice.logprobs else None,
           "usage": resp.usage.model_dump() if resp.usage else None}
    _save_rec(cache_file, rec)
    return {**rec, "cached": False}


async def cached_response(vc: "VLMClient", *, model: str, input: list, params: dict, key_parts: dict,
                          meta: dict) -> dict:
    """Responses API call (reasoning models). Stores the final text and the reasoning summary.
    store=False: OpenAI does not keep the response server-side."""
    cache_file = keyed_cache_path(key_parts)
    if cache_file.exists():
        vc.cache_hits += 1
        return {**json.loads(cache_file.read_text()), "cached": True}
    resp = await _with_retries(vc.sem, lambda: vc.client.responses.create(
        model=model, input=input, store=False, **params))
    vc.calls_made += 1
    summaries = [s.text for item in resp.output if item.type == "reasoning" for s in (item.summary or [])]
    rec = {"cache_key": cache_file.stem, "key_parts": key_parts, **meta,
           "timestamp": datetime.now(timezone.utc).isoformat(), "response_id": resp.id,
           "model_requested": model, "model_returned": resp.model, "params": params,
           "status": resp.status,
           "incomplete_details": resp.incomplete_details.model_dump() if resp.incomplete_details else None,
           "content": resp.output_text, "reasoning_summary": "\n\n".join(summaries),
           "n_summary_parts": len(summaries),
           "usage": resp.usage.model_dump() if resp.usage else None}
    _save_rec(cache_file, rec)
    return {**rec, "cached": False}
