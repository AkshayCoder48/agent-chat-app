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

Robustness notes (learned the hard way from g4f.space):

* SSE separators can be ``\\n\\n`` *or* ``\\r\\n\\r\\n`` depending on the
  provider's HTTP stack. We normalize CRLF → LF before splitting so both
  shapes parse the same way.
* Chunks arrive at arbitrary byte boundaries — a single ``aiter_bytes()``
  chunk may contain half an event, two events, or no events at all. We
  buffer until we see a full event separator before transforming; the
  trailing buffer is only flushed once the upstream stream ends.
* Some providers send an event with no ``data:`` line (just comments or
  ``event:`` / ``id:`` fields). These are passed through unchanged.
* Some providers send ``choices: null`` (not ``[]``) for the usage chunk.
  Both shapes are treated as "drop this chunk".
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
        # We intercept when the response advertises SSE. We also intercept
        # when the content-type is missing/unknown because some providers
        # (and some HTTP proxies) strip the content-type. We do NOT
        # intercept when the response is explicitly application/json — that
        # means a single (non-streamed) completion, and the OpenAI SDK
        # parses it fine without us.
        if ctype and "text/event-stream" not in ctype and "application/json" not in ctype:
            # Unknown content-type — intercept defensively (we'll just pass
            # bytes through if it doesn't look like SSE).
            return self._wrap_stream_response(response)
        if "text/event-stream" in ctype:
            return self._wrap_stream_response(response)
        return response

    def _wrap_stream_response(self, response: httpx.Response) -> httpx.Response:
        # Capture the original byte iterator. We must call aiter_bytes() ONCE
        # — calling it again would create a second iterator over the same
        # underlying stream and break consumption accounting.
        original_aiter = response.aiter_bytes()
        transport = self

        class _FilteredStream(httpx.AsyncByteStream):
            async def __aiter__(self) -> AsyncIterator[bytes]:
                # We accumulate raw bytes here and split on the SSE event
                # separator. CRLF is normalized to LF on the BUFFER (not on
                # individual chunks) — this is critical because chunks can
                # arrive at any byte boundary (even 1 byte at a time), so a
                # ``\r`` and the following ``\n`` may land in different
                # chunks. Without buffer-level normalization the SSE
                # separator ``\r\n\r\n`` never matches ``\n\n`` and the
                # parser hangs forever waiting for the first event —
                # exactly the "stuck at thinking" bug we saw on g4f.space.
                buffer = b""
                try:
                    async for chunk in original_aiter:
                        if not chunk:
                            continue
                        buffer += chunk
                        # Buffer-level CRLF → LF normalization. We must do
                        # this AFTER appending (not on the chunk) because
                        # the ``\r`` and ``\n`` may have arrived in
                        # different chunks. Stray trailing ``\r`` at the
                        # end of the buffer (with no ``\n`` yet) is left
                        # alone — it'll be normalized next iteration when
                        # the matching ``\n`` arrives, or trimmed off in
                        # the trailing-flush step at the bottom.
                        if b"\r\n" in buffer:
                            buffer = buffer.replace(b"\r\n", b"\n")
                        # SSE events are separated by \n\n. Split out every
                        # complete event and yield it (possibly transformed).
                        while b"\n\n" in buffer:
                            event_bytes, buffer = buffer.split(b"\n\n", 1)
                            # Skip empty events (just whitespace between
                            # separators) — yielding them would confuse the
                            # SDK's SSE parser into thinking an event with
                            # no data arrived.
                            if not event_bytes.strip():
                                continue
                            event_text = event_bytes.decode("utf-8", errors="replace")
                            try:
                                modified = await transport._transform_event(event_text)
                            except Exception:
                                # Never let a transform bug kill the stream
                                # — fall back to passing the event through
                                # unchanged so the chat keeps working.
                                logger.warning(
                                    "ReasoningAwareTransport: _transform_event failed, "
                                    "passing event through unchanged",
                                    exc_info=True,
                                )
                                modified = event_text
                            if modified is not None:
                                yield (modified + "\n\n").encode("utf-8", errors="replace")
                    # After the upstream stream ends, flush any trailing
                    # bytes (e.g. a final ``data: [DONE]`` without a
                    # trailing newline). This MUST happen outside the
                    # for-loop so we don't yield partial events mid-stream.
                    if buffer.strip():
                        # Final CRLF normalization pass on the trailing buffer
                        # in case the last ``\r\n`` straddled a chunk
                        # boundary and didn't get normalized above.
                        buffer = buffer.replace(b"\r\n", b"\n").rstrip(b"\r")
                        final_text = buffer.decode("utf-8", errors="replace")
                        try:
                            final = await transport._transform_event(final_text)
                        except Exception:
                            logger.warning(
                                "ReasoningAwareTransport: trailing flush transform failed, "
                                "passing through unchanged",
                                exc_info=True,
                            )
                            final = final_text
                        if final is not None:
                            yield (final + "\n\n").encode("utf-8", errors="replace")
                except Exception:
                    logger.warning(
                        "ReasoningAwareTransport stream failed", exc_info=True
                    )
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
        # Use a case-insensitive MutableHeaders copy so we can safely pop
        # headers regardless of the original casing used by the upstream.
        headers = httpx.Headers(response.headers)
        # Strip content-length since the body length is now different —
        # keeping it would make httpx think the response was truncated.
        # ``headers.pop`` is silent when the key is absent.
        headers.pop("content-length", None)
        headers.pop("Content-Length", None)
        # Ensure the SDK routes this through its SSE parser, not the JSON
        # parser. Some providers set "application/json" even for streams;
        # that causes the SDK to buffer the whole body and the chat hangs
        # at "Thinking…" forever.
        existing_ct = headers.get("content-type", "")
        if "text/event-stream" not in existing_ct:
            headers["content-type"] = "text/event-stream"
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
                    # Malformed JSON — pass through unchanged. This can
                    # happen with providers that send partial JSON across
                    # multiple events (very rare, but we don't want to
                    # crash the whole turn on it).
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

        Why we drop "empty-delta" chunks after stripping reasoning:

        g4f.space (and other reasoning-capable free relays) emits a stream
        where the model thinks for ~10-20 chunks before producing any
        visible content. Each reasoning chunk looks like::

            {"choices":[{"index":0,"delta":{"reasoning_content":"...","reasoning":"..."}}]}

        After we strip ``reasoning_content`` + ``reasoning``, the delta
        becomes ``{}`` (completely empty). The openai SDK parses these
        as no-op ChatCompletionChunks. pydantic-ai's stream consumer
        sees no text content arriving for an extended period and the
        UI hangs at "Thinking…" until the SDK's read timeout fires
        (600s by default) — at which point the openai SDK raises
        ``APIConnectionError("Connection error.")``.

        Fix: after extracting reasoning, check whether the chunk still
        carries any meaningful payload (content, role, tool_calls,
        finish_reason, or usage). If not, drop it entirely. The
        reasoning callback still fires for each dropped chunk, so the
        frontend still renders the reasoning live — only the no-op
        SDK chunks are suppressed.
        """
        if not isinstance(obj, dict):
            return obj

        choices = obj.get("choices")
        # Drop chunks with empty/null choices (the usage-only chunk that
        # crashes parsers that index choices[0]). Both ``[]`` and ``None``
        # are treated as "drop".
        if not choices:
            return None

        cb = _reasoning_callback_var.get() or self._default_callback

        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                # Some providers send ``message`` instead of ``delta`` for
                # the first chunk. Don't try to extract reasoning_content
                # from it — just pass through.
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
            # Same for "reasoning" (some providers use this shorter name).
            reasoning_short = delta.pop("reasoning", None)
            if reasoning_short and not rc:
                rc = reasoning_short

            # Also handle the "thinking" field (Yet another non-standard
            # name used by some providers like某些 Anthropic-compatible
            # gateways). We don't strip ``thinking`` because pydantic-ai
            # may handle it natively for some model classes — only strip
            # the non-standard ``reasoning_content`` / ``reasoning`` /
            # ``reasoning_content`` variants.
            if rc and cb is not None and isinstance(rc, str) and rc:
                try:
                    await cb(rc)
                except Exception:
                    logger.debug("reasoning callback failed", exc_info=True)

        # After stripping reasoning_content/reasoning, check whether any
        # choice still carries a meaningful payload. If not — and there's
        # no top-level ``usage`` field — drop the chunk entirely.
        #
        # This is the critical fix for the "stuck at thinking" hang on
        # g4f.space: their reasoning stream emits ~10-20 consecutive
        # chunks with delta={"reasoning_content":"..."} and nothing else.
        # After stripping, those chunks become delta={} — passing them
        # through to the openai SDK results in a long stream of no-op
        # chunks that pydantic-ai's stream consumer can't make progress
        # on, so the UI hangs until the read timeout fires.
        #
        # We DO NOT drop chunks that carry:
        #   - ``finish_reason`` (the "stop" signal — the SDK needs this
        #     to finalize the message)
        #   - ``usage`` (the usage stats chunk — the SDK needs this for
        #     token accounting when stream_options.include_usage=true)
        #   - ``content`` / ``role`` / ``tool_calls`` / ``function_call``
        #     (actual message content)
        has_meaningful_payload = False
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            if choice.get("finish_reason") is not None:
                has_meaningful_payload = True
                break
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue
            # ``content`` can be "" (empty string) on the first "role
            # announcement" chunk — that's fine, we check ``role`` too.
            if (
                delta.get("content")
                or delta.get("role")
                or delta.get("tool_calls")
                or delta.get("tool_call")
                or delta.get("function_call")
            ):
                has_meaningful_payload = True
                break
        if not has_meaningful_payload and "usage" not in obj:
            # Pure reasoning chunk — already emitted via the callback.
            # Drop it so the SDK doesn't see a no-op chunk.
            return None

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

    Hardening notes (each addresses a real failure mode we've seen in
    production against free relays like g4f.space):

    * **User-Agent** — the openai SDK ships a default UA of
      ``"OpenAI/Python <ver>"``. Some relays (g4f.space, certain
      Cloudflare-fronted proxies) silently drop connections carrying
      that UA — surfacing in pydantic-ai as the generic
      ``"Connection error."`` with no underlying cause. Override with a
      browser-like UA.

    * **HTTP/1.1 only** — pydantic-ai's SSE stream parser doesn't
      tolerate the chunked-encoding quirks some HTTP/2 servers send.

    * **follow_redirects=True** — g4f.space and a few other relays
      redirect ``/v1/chat/completions`` to a CDN endpoint; the openai
      SDK's default client follows redirects, but if we override
      ``http_client`` we must re-enable it explicitly.

    * **keepalive_expiry=0** — g4f.space and a few other free relays
      reuse a connection for one SSE stream then drop it; sending a
      second request (e.g. when the agent calls a tool and re-prompts
      the model) on the same keep-alive socket raises
      ``RemoteProtocolError``. Forcing a fresh socket per request
      avoids this.

    * **Connect timeout 15s** — so DNS/TLS failures surface fast
      instead of hanging the whole chat turn.

    * **Authorization header** — we set it here as a defensive default
      so the request still authenticates even if some code path
      bypasses the SDK's header injection. The SDK also sets its own
      ``Authorization: Bearer <key>`` from the ``api_key`` we pass to
      ``OpenAIProvider`` — request-level header wins, so the values
      agree and there's no conflict.
    """
    inner = httpx.AsyncHTTPTransport(retries=0, http2=False)
    transport = ReasoningAwareTransport(inner, reasoning_callback=reasoning_callback)
    return httpx.AsyncClient(
        base_url=base_url,
        transport=transport,
        timeout=httpx.Timeout(timeout, connect=15.0),
        # Some relays (g4f.space, Cloudflare-fronted proxies) silently
        # drop requests carrying the openai SDK's default UA
        # "OpenAI/Python <ver>". Override with a browser-like UA.
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json, text/event-stream",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
        },
        http2=False,
        # g4f.space redirects /v1/chat/completions to a CDN — without
        # follow_redirects, the request fails with a 3xx and the openai
        # SDK wraps it as "Connection error.".
        follow_redirects=True,
        # g4f.space drops the socket after the first SSE stream —
        # a second request on the same keep-alive socket raises
        # RemoteProtocolError. Force a fresh socket per request.
        keepalive_expiry=0.0,
    )
