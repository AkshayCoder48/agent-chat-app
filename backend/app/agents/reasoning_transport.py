"""Custom httpx transport that normalizes non-standard OpenAI-compatible streams.

Some third-party OpenAI-compatible providers — notably `g4f.space` (vLLM-based
relays), DeepSeek, and certain Together AI endpoints — stream chunks that
include **non-standard** fields in `delta`:

* `reasoning_content` — the model's chain-of-thought, duplicated by `reasoning`
* `reasoning` — same payload as `reasoning_content` (vendor-specific alias)

pydantic-ai ≥ 1.4 already maps `reasoning_content` to :class:`ThinkingPart`
events, but a number of failure modes still hit us in production:

1. **Older pydantic-ai releases** (e.g. the 1.80 floor in ``pyproject.toml``
   on staging) crash or emit empty ``TextPart`` events when the field is
   present alongside ``content`` in the same chunk.
2. **Pure-reasoning chunks** — `delta: {"reasoning_content": "..."}` with no
   ``content`` / ``role`` / ``tool_calls`` / ``finish_reason`` — are no-ops for
   our consumer but some providers (vLLM) still emit a ``usage`` block on
   every chunk, trickying pydantic-ai into thinking the chunk carries data.
3. **Mixed chunks** like ``{"reasoning_content": "...", "content": "Hello!"}``
   cause duplicate text output when an older parser double-counts the delta.
4. The trailing ``{"delta": {}, "usage": {...}}`` chunk is sometimes sent
   before ``finish_reason``, which can confuse token accounting.

This module provides :class:`ReasoningAwareTransport` — an
:class:`httpx.AsyncBaseTransport` that wraps the default HTTP transport and
rewrites the SSE byte stream on the way back to the OpenAI SDK. The SDK
therefore only ever sees clean, spec-compliant chunks.

Public surface:
    * :func:`build_reasoning_aware_client` — returns an ``httpx.AsyncClient``
      with hardened defaults (HTTP/1.1 only, ``identity`` encoding, no
      keepalive, real browser ``User-Agent``) suitable for use with the
      ``openai.AsyncOpenAI`` client.
    * :func:`transform_chunk` — pure helper that takes a parsed chunk dict and
      returns either the rewritten dict or ``None`` to drop the chunk. Exposed
      for testing.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def transform_chunk(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Rewrite a single streamed ``chat.completion.chunk`` payload.

    Returns ``None`` to drop the chunk entirely, or a (possibly modified) dict
    to keep it. The input is the parsed JSON object from a ``data: {...}`` SSE
    line — *not* the raw bytes.

    Transformation rules (derived from real ``g4f.space`` captures):

    1. Strip ``reasoning_content`` and ``reasoning`` from every
       ``choices[i].delta``. These are non-standard; pydantic-ai already maps
       them to :class:`ThinkingPart` via the OpenAI SDK's own
       ``delta.reasoning_content`` field on ``ChoiceDelta``.
    2. After stripping, if a delta has no meaningful payload — i.e. no
       ``content``, ``role``, ``tool_calls``, ``function_call``, or
       ``finish_reason`` — drop the chunk. ``usage`` is NOT considered a
       meaningful payload on its own because vLLM sends it on EVERY chunk;
       keeping it would create phantom "data" events.
    3. The final ``{"delta": {}, "usage": {...}}`` chunk (no ``finish_reason``
       in any choice) is preserved only when there is no ``finish_reason`` on
       the same chunk. We keep ``usage`` so the SDK can report token counts.
    4. Empty-content chunks like ``{"delta": {"role": "assistant", "content": ""}}``
       are kept (they signal the start of the assistant turn).
    """
    if not isinstance(obj, dict):
        return None

    # Make a shallow copy so we don't mutate the caller's dict.
    obj = dict(obj)

    choices = obj.get("choices")
    if not isinstance(choices, list) or not choices:
        # No choices array (e.g. an isolated ``usage`` chunk). Keep as-is —
        # the SDK tolerates this and we want the usage data.
        return obj

    keep_any = False
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            # A choice without a delta (rare) — keep if it has finish_reason.
            if choice.get("finish_reason") is not None:
                keep_any = True
            continue

        # 1. Strip non-standard reasoning fields.
        delta = dict(delta)
        delta.pop("reasoning_content", None)
        delta.pop("reasoning", None)

        # 2. Decide whether the remaining payload is meaningful.
        has_meaningful_payload = (
            delta.get("content") is not None           # includes empty string ""
            or delta.get("role") is not None
            or delta.get("tool_calls") is not None
            or delta.get("function_call") is not None
            or choice.get("finish_reason") is not None
        )

        if not has_meaningful_payload:
            # Drop the choice entirely (it was a pure-reasoning chunk).
            # We'll prune the choice from the array below.
            choice = dict(choice)
            choice["__drop__"] = True
            choices[choices.index(choice) if choice in choices else 0] = choice
            continue

        choice["delta"] = delta
        keep_any = True

    # Prune dropped choices.
    pruned = [c for c in choices if not (isinstance(c, dict) and c.pop("__drop__", False))]
    obj["choices"] = pruned

    if not keep_any and not obj.get("usage"):
        # Every choice was dropped and there's no usage to keep → drop chunk.
        return None
    return obj


class _WrappedByteStream(httpx.AsyncByteStream):
    """Adapter that wraps an async-iterator-of-bytes in the AsyncByteStream
    interface that httpx 0.28+ requires on ``Response.stream``.

    Directly assigning a bare async generator to ``response.stream`` trips
    ``assert isinstance(response.stream, AsyncByteStream)`` inside
    ``httpx._client._send_single_request`` — which the OpenAI SDK then
    surfaces as the dreaded ``APIConnectionError: Connection error.``.
    """

    def __init__(self, source: AsyncIterator[bytes]) -> None:
        self._source = source

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._source

    async def aclose(self) -> None:
        # Best-effort: close the underlying iterator if it has aclose().
        aclose = getattr(self._source, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:
                logger.debug("Wrapped stream aclose() failed", exc_info=True)


class ReasoningAwareTransport(httpx.AsyncBaseTransport):
    """Async HTTP transport that rewrites SSE streams on the way back.

    Wraps an inner transport (default: :class:`httpx.AsyncHTTPTransport` with
    HTTP/1.1 only). For non-SSE responses it forwards unchanged. For SSE
    responses it parses each ``data: ...`` line, applies :func:`transform_chunk`,
    and re-emits cleaned ``data: ...\\n\\n`` lines.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self._inner = inner or httpx.AsyncHTTPTransport(http2=False)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        ctype = response.headers.get("content-type", "").lower()
        if "text/event-stream" not in ctype:
            return response
        # Wrap the stream. httpx 0.28+ asserts that ``response.stream`` is an
        # ``AsyncByteStream`` (NOT a bare async generator) — assigning a
        # generator here trips an AssertionError inside ``_send_single_request``
        # which the openai SDK surfaces as ``APIConnectionError: Connection
        # error.``. So we MUST wrap the generator in an AsyncByteStream.
        response.stream = _WrappedByteStream(self._wrap_stream(response.stream))
        return response

    async def _wrap_stream(
        self, inner_stream: AsyncIterator[bytes]
    ) -> AsyncIterator[bytes]:
        """Yield cleaned SSE bytes.

        SSE framing: events are separated by ``\n\n``; each event is a series
        of ``field: value`` lines. We only care about ``data:`` lines. A
        ``data: [DONE]`` marker is forwarded unchanged.
        """
        buffer = b""
        async for chunk in inner_stream:
            buffer += chunk
            # Process complete events (separated by \n\n).
            while b"\n\n" in buffer:
                event_bytes, buffer = buffer.split(b"\n\n", 1)
                async for out_bytes in self._process_event(event_bytes):
                    yield out_bytes
        # Flush any trailing event (no trailing \n\n).
        if buffer.strip():
            async for out_bytes in self._process_event(buffer):
                yield out_bytes

    async def _process_event(self, event_bytes: bytes) -> AsyncIterator[bytes]:
        """Parse one SSE event, transform if it's a chunk, re-emit as bytes."""
        try:
            event_text = event_bytes.decode("utf-8", errors="replace")
        except Exception:
            yield event_bytes + b"\n\n"
            return

        # Each line is "field: value" — we keep non-data lines as-is and
        # transform data: lines.
        out_lines: list[str] = []
        for line in event_text.splitlines():
            if not line or line.startswith(":"):
                # Comment or empty line — preserve.
                out_lines.append(line)
                continue
            if ":" in line:
                field, _, value = line.partition(":")
                value = value.lstrip(" ")
            else:
                field, value = line, ""
            if field != "data":
                out_lines.append(line)
                continue
            # data line
            if value.strip() == "[DONE]":
                out_lines.append(f"data: [DONE]")
                continue
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                # Not JSON — pass through unchanged.
                out_lines.append(line)
                continue
            transformed = transform_chunk(parsed)
            if transformed is None:
                # Drop the event entirely — don't emit anything.
                return
            out_lines.append(f"data: {json.dumps(transformed, ensure_ascii=False)}")
        # Re-emit with proper SSE framing.
        yield ("\n".join(out_lines) + "\n\n").encode("utf-8")


# --------------------------------------------------------------------------- #
# Client factory
# --------------------------------------------------------------------------- #
def build_reasoning_aware_client(
    *,
    timeout: float = 120.0,
    verify: bool = True,
) -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` with the reasoning-aware transport.

    Hardened defaults that fix observed g4f.space / vLLM flakiness:

    * HTTP/1.1 only (``http2=False``) — g4f's edge returns chunked
      ``Content-Length`` responses that confuse HTTP/2 multiplexing.
    * ``Accept-Encoding: identity`` — disables gzip/brotli so the SSE parser
      sees raw bytes (compressed SSE breaks incremental parsing).
    * ``keepalive_expiry=0.0`` on the inner transport — disables connection
      pooling so each request gets a fresh socket (g4f's edge sometimes
      returns stale 502s on reused connections).
    * A real browser ``User-Agent`` — g4f's edge 403s requests with the
      default ``python-httpx/0.28`` UA.
    * ``follow_redirects=True`` — some providers redirect /v1/chat/completions
      to a regional shard.
    """
    inner_transport = httpx.AsyncHTTPTransport(
        http2=False,
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=0,  # disable keepalive pooling
            keepalive_expiry=0.0,
        ),
        verify=verify,
    )
    transport = ReasoningAwareTransport(inner=inner_transport)
    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(timeout, connect=10.0),
        follow_redirects=True,
        http2=False,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
