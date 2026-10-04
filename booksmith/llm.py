"""Pluggable language-model backend.

The point of this file is that *agent design* and *language generation* are kept
apart. Every agent has an offline path that needs no network and no API key, so
the pipeline always runs end to end. When a model is reachable the same agents
get it for the generative steps instead.

Providers: anthropic, openai (also openai-compatible gateways such as groq and
openrouter via base_url), gemini, ollama (free and local), offline.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Protocol

from .http import BROWSER_UA

# A model that cannot answer inside this many seconds is not going to answer the
# next agent either, and six agents each waiting three minutes is a very long
# silence for a user watching a run.
REQUEST_TIMEOUT = 180

# A backend that just failed is set aside briefly rather than retried by every
# agent in the same run. The cooldown is short so a server that is restarted
# mid-session comes back on its own.
UNREACHABLE_COOLDOWN = 600.0
_UNREACHABLE: dict[str, tuple[float, str]] = {}


def _base_key(base_url: str) -> str:
    """One spelling per server, whether it is named with or without /v1."""
    return (base_url or "").rstrip("/").removesuffix("/v1")


def note_unreachable(base_url: str, reason: str) -> None:
    _UNREACHABLE[_base_key(base_url)] = (time.monotonic(), reason)


def recently_unreachable(base_url: str) -> str | None:
    """Why this backend was set aside recently, or None if it is worth trying."""
    key = _base_key(base_url)
    entry = _UNREACHABLE.get(key)
    if entry is None:
        return None
    when, reason = entry
    if time.monotonic() - when > UNREACHABLE_COOLDOWN:
        _UNREACHABLE.pop(key, None)
        return None
    return reason


def clear_unreachable() -> None:
    """Forget set-aside backends. Used by the self-test between cases."""
    _UNREACHABLE.clear()


class LLMError(RuntimeError):
    pass


class Backend(Protocol):
    name: str
    model: str

    def complete(self, system: str, prompt: str, max_tokens: int = 4096,
                 temperature: float = 0.3, json_mode: bool = False) -> str:
        ...


class OfflineBackend:
    """No network, no key. Agents fall back to their deterministic reasoning."""

    name = "offline"

    def __init__(self, model: str = "deterministic-composer"):
        self.model = model

    @property
    def available(self) -> bool:
        return True

    def complete(self, system: str, prompt: str, max_tokens: int = 4096,
                 temperature: float = 0.3, json_mode: bool = False) -> str:
        raise LLMError("offline backend cannot generate text")


class _HTTPBackend:
    def __init__(self, name: str, model: str, api_key: str, base_url: str):
        self.name = name
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _post(self, url: str, payload: dict, headers: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:400]
            raise LLMError(f"{self.name} HTTP {exc.code}: {detail}") from exc
        except Exception as exc:  # noqa: BLE001
            note_unreachable(self.base_url, f"{type(exc).__name__}: {exc}")
            raise LLMError(f"{self.name} request failed: {exc}") from exc

    def complete(self, system: str, prompt: str, max_tokens: int = 4096,
                 temperature: float = 0.3, json_mode: bool = False) -> str:
        raise NotImplementedError


class AnthropicBackend(_HTTPBackend):
    def complete(self, system: str, prompt: str, max_tokens: int = 4096,
                 temperature: float = 0.3, json_mode: bool = False) -> str:
        data = self._post(
            f"{self.base_url}/v1/messages",
            {
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
            {
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "user-agent": BROWSER_UA,
            },
        )
        parts = [b.get("text", "") for b in data.get("content", [])]
        return "".join(parts).strip()


class OpenAIBackend(_HTTPBackend):
    """OpenAI chat-completions shape, which Ollama and most gateways also speak."""

    def complete(self, system: str, prompt: str, max_tokens: int = 4096,
                 temperature: float = 0.3, json_mode: bool = False) -> str:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.api_key}",
            "user-agent": BROWSER_UA,
        }
        if json_mode:
            try:
                return self._chat({**payload, "response_format": {"type": "json_object"}},
                                  headers)
            except LLMError as exc:
                # Not every OpenAI-compatible server implements JSON mode. Losing
                # the hint is better than losing the run; `try_json` copes.
                if not _looks_like_json_mode_rejection(exc):
                    raise
        return self._chat(payload, headers)

    def _chat(self, payload: dict, headers: dict) -> str:
        data = self._post(f"{self.base_url}/chat/completions", payload, headers)
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"{self.name}: empty response")
        return (choices[0].get("message", {}).get("content") or "").strip()


class OllamaBackend(OpenAIBackend):
    """Ollama on your own machine. No key, no cost, no data leaving the box.

    Ollama serves an OpenAI-compatible API at `<base>/v1`, so this is the same
    wire format as the OpenAI backend with a placeholder key. The one thing worth
    knowing: Ollama's default context window is 4096 tokens unless the model was
    built with more, and the Architect's prompt is long. Start the server with
    `OLLAMA_CONTEXT_LENGTH=16384` if a plan comes back truncated.
    """


class GeminiBackend(_HTTPBackend):
    def complete(self, system: str, prompt: str, max_tokens: int = 4096,
                 temperature: float = 0.3, json_mode: bool = False) -> str:
        url = (
            f"{self.base_url}/v1beta/models/{self.model}:generateContent"
            f"?key={self.api_key}"
        )
        data = self._post(
            url,
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": temperature,
                },
            },
            {"content-type": "application/json", "user-agent": BROWSER_UA},
        )
        parts = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        return "".join(p.get("text", "") for p in parts).strip()


PROVIDERS = {
    "anthropic": {
        "env": "ANTHROPIC_API_KEY",
        "base_env": "ANTHROPIC_BASE_URL",
        "default_base": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-20250514",
        "cls": AnthropicBackend,
    },
    "openai": {
        "env": "OPENAI_API_KEY",
        "base_env": "OPENAI_BASE_URL",
        "default_base": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "cls": OpenAIBackend,
    },
    "gemini": {
        "env": "GEMINI_API_KEY",
        "base_env": "GEMINI_BASE_URL",
        "default_base": "https://generativelanguage.googleapis.com",
        "default_model": "gemini-2.0-flash",
        "cls": GeminiBackend,
    },
    # Last in line: free and local, but never preferred over a key that is present.
    "ollama": {
        "env": "OLLAMA_API_KEY",
        "base_env": "OLLAMA_BASE_URL",
        "default_base": "http://127.0.0.1:11434/v1",
        "default_model": "llama3.1",
        "placeholder_key": "ollama",
        "cls": OllamaBackend,
        "probe": "ollama_reachable",
    },
}

AUTO_ORDER = ["anthropic", "openai", "gemini", "ollama"]

_REACHABLE: dict[str, tuple[bool, tuple[str, ...]]] = {}

# Models that have proved they can hold a whole JSON plan in one reply, best
# first. Anything else installed is used as a last resort rather than refused.
OLLAMA_PREFERENCE = (
    "qwen3", "qwen2.5", "qwen2", "llama3.2", "llama3.1", "llama3", "mistral",
    "gemma3", "gemma2", "deepseek-r1", "phi4", "command-r", "llama2",
)


def ollama_installed(base: str) -> tuple[bool, tuple[str, ...]]:
    """Is an Ollama server answering, and which models has it?

    Availability is not just "is a key set" for a local server: the point is
    whether something is actually listening and can serve the model we intend to
    use. Asked once per base URL, then remembered.
    """
    if base in _REACHABLE:
        return _REACHABLE[base]
    url = base.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    names: tuple[str, ...] = ()
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=3) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8", "replace"))
                names = tuple(
                    str(entry.get("name") or entry.get("model") or "")
                    for entry in (data.get("models") or [])
                )
                names = tuple(n for n in names if n)
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        names = ()
    result = (bool(names), names)
    _REACHABLE[base] = result
    return result


def ollama_reachable(base: str) -> bool:
    return ollama_installed(base)[0]


def pick_ollama_model(requested: str | None, installed: tuple[str, ...],
                      default: str) -> str:
    """Choose a model that is actually installed.

    `llama3.1` is the sensible default for a fresh install, but most machines
    have something else, and a missing model fails on every single call. So the
    model's own list is consulted: an explicit request wins, then the default if
    it is there, then the best-known family that is there, then anything.
    """
    if requested:
        return requested
    if not installed:
        return default
    have = {name.split(":")[0] for name in installed}
    if default.split(":")[0] in have or default in installed:
        return default
    for family in OLLAMA_PREFERENCE:
        for name in installed:
            if name.split(":")[0] == family or name.startswith(f"{family}:"):
                return name
    return installed[0]


def _looks_like_json_mode_rejection(exc: Exception) -> bool:
    text = str(exc).lower()
    return "json" in text or "response_format" in text


def resolve_backend(preference: str = "auto", model: str | None = None) -> Backend:
    """Pick a backend. `auto` takes the first provider that is really usable."""
    if preference == "offline":
        return OfflineBackend()
    if preference != "auto" and preference not in PROVIDERS:
        raise LLMError(
            f"unknown backend {preference!r}; choose 'auto', 'offline' or one of: "
            + ", ".join(sorted(PROVIDERS))
        )
    order = AUTO_ORDER if preference == "auto" else [preference]
    spec_missing: list[str] = []

    for name in order:
        spec = PROVIDERS.get(name)
        if not spec:
            continue
        key = os.environ.get(spec["env"], "").strip() or spec.get("placeholder_key", "")
        base = os.environ.get(spec["base_env"], "").strip() or spec["default_base"]
        if not key:
            spec_missing.append(f"{spec['env']} is not set")
            continue
        setback = recently_unreachable(base)
        if setback:
            spec_missing.append(
                f"{name} stopped answering ({setback}); it will be tried again "
                f"in {int(UNREACHABLE_COOLDOWN // 60)} minute(s)"
            )
            continue
        probe_name = spec.get("probe")
        chosen = model or spec["default_model"]
        if probe_name == "ollama_reachable":
            up, installed = ollama_installed(base)
            if not up:
                spec_missing.append(
                    "no Ollama server answered at "
                    + base.rstrip("/").removesuffix("/v1")
                    + "; start one with `ollama serve`"
                )
                continue
            chosen = pick_ollama_model(model, installed, spec["default_model"])
        elif probe_name and not globals()[probe_name](base):
            spec_missing.append(f"{name} did not answer at {base}")
            continue
        return spec["cls"](name, chosen, key, base)

    if preference != "auto":
        raise LLMError(
            f"backend {preference!r} is not usable: " + "; ".join(spec_missing)
        )
    return OfflineBackend()


def try_json(text: str):
    """Parse JSON from a model reply that may be wrapped in prose or fences."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start = min(
        [i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1] or [-1]
    )
    if start == -1:
        return None
    for end in range(len(cleaned), start, -1):
        chunk = cleaned[start:end]
        if not chunk.endswith(("}", "]")):
            continue
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            continue
    return None