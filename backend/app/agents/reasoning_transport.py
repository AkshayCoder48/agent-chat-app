"""httpx transport that intercepts OpenAI-compatible SSE streams.

Two purposes:

1. **Parser robustness** — some non-standard OpenAI-compatible providers
   (g4f.space, certain OpenRouter endpoints, …) emit a final chunk with an
   empty ``choices`` array alongside a ``usage`` payload. The OpenAI Python
   SDK and/or pydantic-ai's parser can index-out-of-bounds on this chunk
   (``choices[0]``) and crash the turn. We filter those chunks out here.

2. **``reasoning_content`` extraction** — DeepSeek, Moonshot/Kimi, g4f.space
   and others stream the model's chain-of-thought via a non-standard
   ``delta.reasoning_content`` field. pydantic-ai's ``OpenAIChatModel`` does
   surface this as a ``ThinkingPart``, which works fine — but we want it
   rendered in a SEPARATE "Reasoning" block on the frontend (visually
   distinct from OpenAI-native reasoning summaries that come through the
   ``Thinking`` capability). So we strip ``reasoning_content`` out of the
   SSE chunks BEFORE pydantic-ai sees them and emit it via a side-channel
   callback instead. AgentSession wires the callback to a
   ``reasoning_delta`` WebSocket event.

The previous parser (delta.content → text, native reasoning → ThinkingPart)
is untouched. Both parsers run side-by-side: this transport only adds a
third channel for the non-standard ``reasoning_content`` field.
"""

from __future__ import annotations

import contextvars
import json
import logging
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

ReasoningCallback = Callable[[str], Awaitable[None]]

#: Per-turn callback holder. AgentSession sets this before each agent run
#: (via :func:`set_reasoning_callback`) so the transport can fire
#: ``reasoning_delta`` events on the live WebSocket. Defaults to ``None``
#: when no session is active (e.g. ad-hoc agent runs from a CLI).
_reasoning_callback_var: contextvars.ContextVar[ReasoningCallback | None] = contextvars.ContextVar(
    "reasoning_callback", default=None
)


def set_reasoning_callback(cb: ReasoningCallback | None) -> contextvars.Token[ReasoningCallback | None]:
    """Bind a per-turn reasoning emitter. Returns the token to pass to :func:`reset_reasoning_callback`."""
    return _reasoning_callback_var.set(cb)


def reset_reasoning_callback(token: contextvars.Token[ReasoningCallback | None]) -> None:
    """Restore the previous callback binding when the turn ends."""
    _reasoning_callback_var.reset(token)


class ReasoningAwareTransport(httpx.AsyncBaseTransport):
    """Wraps an inner httpx transport to filter/transform OpenAI SSE chunks.

    Only touches responses to ``*/chat/completions`` whose
    ``content-type`` is ``text/event-stream``. Non-streaming responses and
    unrelated endpoints pass through unchanged.
    """

    def __init__(
        self,
        wrapped: httpx.AsyncBaseTransport,
        reasoning_callback: ReasoningCallback | None = None,
    ) -> None:
        self._wrapped = wrapped
        # Default callback when no per-turn callback is set in the contextvar.
        # AgentSession overrides this via set_reasoning_callback().
        self._default_callback = reasoning_callback

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._wrapped.handle_async_request(request)
        # Only intercept streaming chat-completions responses.
        path = request.url.path
        if not (path.endswith("/chat/completions") or path.endswith("/chat/completions/")):
            return response
        ctype = response.headers.get("content-type", "")
        if "text/event-stream" not in ctype:
            return response
        return self._wrap_stream_response(response)

    def _wrap_stream_response(self, response: httpx.Response) -> httpx.Response:
        # Use aiter_bytes — we want the raw byte stream from the network.
        # We capture the original iterator by calling aiter_bytes() once.
        original_aiter = response.aiter_bytes()
        transport = self

        class _FilteredStream(httpx.AsyncByteStream):
            async def __aiter__(self) -> AsyncIterator[bytes]:
                buffer = b""
                try:
                    async for chunk in original_aiter:
                        buffer += chunk
                        # SSE events are separated by \n\n
                        while b"\n\n" in buffer:
                            event_bytes, buffer = buffer.split(b"\n\n", 1)
                            event_text = event_bytes.decode("utf-8", errors="replace")
                            modified = await transport._transform_event(event_text)
                            if modified is not None:
                                yield (modified + "\n\n").encode("utf-8", errors="replace")
                    # Flush any trailing bytes (e.g. final "[DONE]" without trailing newline)
                    if buffer.strip():
                        final_text = buffer.decode("utf-8", errors="replace")
                        final = await transport._transform_event(final_text)
                        if final is not None:
                            yield (final + "\n\n").encode("utf-8", errors="replace")
                except Exception:
                    logger.warning("ReasoningAwareTransport stream failed", exc_info=True)
                    raise

            async def aclose(self) -> None:
                # Best-effort close of the underlying iterator.
                aclose = getattr(original_aiter, "aclose", None)
                if aclose is not None:
                    try:
                        await aclose()
                    except Exception:
                        logger.debug("original_aiter.aclose failed", exc_info=True)

        # Build a new streaming Response. We pass `stream=_FilteredStream()`
        # which httpx will iterate when the consumer reads the body.
        headers = dict(response.headers)
        # Strip content-length since the body length is now different.
        headers.pop("content-length", None)
        headers.pop("Content-Length", None)
        new_response = httpx.Response(
            status_code=response.status_code,
            headers=headers,
            stream=_FilteredStream(),
            extensions=response.extensions,
            request=response.request,
        )
        return new_response

    async def _transform_event(self, event_text: str) -> str | None:
        """Transform one SSE event. Returns None to drop the event.

        SSE event format (simplified)::

            data: {json payload}

        or::

            data: [DONE]

        Lines starting with ``:`` are comments; we pass them through.
        """
        # Split into lines, preserve empty lines/structure
        lines = event_text.split("\n")
        out_lines: list[str] = []
        for line in lines:
            stripped = line.rstrip("\r")
            if not stripped:
                out_lines.append(stripped)
                continue
            if stripped.startswith(":"):
                # SSE comment — pass through
                out_lines.append(stripped)
                continue
            if stripped.startswith("data:"):
                payload = stripped[5:].lstrip()
                if payload == "[DONE]":
                    out_lines.append("data: [DONE]")
                    continue
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    # Malformed JSON — pass through unchanged.
                    out_lines.append(stripped)
                    continue
                modified = await self._transform_chunk(obj)
                if modified is None:
                    # Drop this event entirely.
                    return None
                out_lines.append("data: " + json.dumps(modified, ensure_ascii=False))
            else:
                # Other SSE fields (event:, id:, retry:) — pass through.
                out_lines.append(stripped)
        return "\n".join(out_lines)

    async def _transform_chunk(self, obj: Any) -> Any | None:
        """Filter / transform one parsed chat-completion chunk.

        Returns ``None`` to drop the chunk, else the (possibly modified) dict.
        """
        if not isinstance(obj, dict):
            return obj

        choices = obj.get("choices")
        # Drop chunks with empty/null choices (the usage-only chunk that
        # crashes parsers that index choices[0]).
        if not choices:
            return None

        cb = _reasoning_callback_var.get() or self._default_callback

        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue
            # Extract reasoning_content (may be at top level of delta or
            # nested under model_extra for some SDK serializations).
            rc = delta.pop("reasoning_content", None)
            if rc is None:
                # OpenAI SDK stores unknown fields under model_extra — also check there.
                extra = delta.get("model_extra")
                if isinstance(extra, dict):
                    rc = extra.pop("reasoning_content", None)
                    if not extra:
                        delta.pop("model_extra", None)
            if rc:
                # Strip from delta — handled by us via callback, NOT by pydantic-ai.
                pass
            # Same for "reasoning" (some providers use this shorter name).
            reasoning_short = delta.pop("reasoning", None)
            if reasoning_short and not rc:
                rc = reasoning_short

            if rc and cb is not None and isinstance(rc, str) and rc:
                try:
                    await cb(rc)
                except Exception:
                    logger.debug("reasoning callback failed", exc_info=True)

        return obj

def build_reasoning_aware_client(
    base_url: str,
    api_key: str,
    timeout: float = 600.0,
    reasoning_callback: ReasoningCallback | None = None,
) -> httpx.AsyncClient:
    """Build an httpx.AsyncClient whose transport filters SSE chunks.

    The returned client can be passed to ``OpenAIProvider(http_client=...)``
    so the OpenAI SDK uses it for all requests to ``/chat/completions``.
    """
    inner = httpx.AsyncHTTPTransport(retries=0)
    transport = ReasoningAwareTransport(inner, reasoning_callback=reasoning_callback)
    return httpx.AsyncClient(
        base_url=base_url,
        transport=transport,
        timeout=httpx.Timeout(timeout, connect=10.0),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json, text/event-stream",
        },
    )
