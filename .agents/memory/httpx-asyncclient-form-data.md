---
name: httpx AsyncClient + list-of-tuples form data
description: Misleading "Attempted to send a sync request with an AsyncClient instance" RuntimeError when posting form data as list[tuple] on httpx AsyncClient.
---

# Rule
On `httpx.AsyncClient` (at least up to 0.26.x), do NOT pass `data=list[tuple[str, str]]` to `post()`. Pre-urlencode the body yourself with `urllib.parse.urlencode(...).encode("utf-8")` and pass it as `content=` (with `Content-Type: application/x-www-form-urlencoded` in headers).

# Why
httpx encodes `data=list[tuple]` into an `IteratorByteStream` that implements only `SyncByteStream`. The AsyncClient's `_send_single_request` does `isinstance(request.stream, AsyncByteStream)` and raises `RuntimeError("Attempted to send an sync request with an AsyncClient instance.")` — the error message blames the client, but the real culprit is the body stream type.

A plain `dict` data also produces the sync-only stream; the safe path is `content=bytes` (yields a dual `ByteStream`). `dict` may also reorder keys, which matters for backends that are positionally sensitive (e.g. DataTables-style `d[i][name]/d[i][value]` pairs).

# How to apply
- Any new async httpx caller posting form data: build the body as `urlencode(pairs).encode("utf-8")` and send via `content=`.
- If you see this RuntimeError elsewhere, the stack trace will point at `_send_single_request`; check the request body construction first, not the client/transport. Don't waste time on proxy / transport / event-loop hypotheses.
- If we upgrade httpx, re-verify: later versions may make `IteratorByteStream` dual-conforming and the workaround would become unnecessary (but harmless).
