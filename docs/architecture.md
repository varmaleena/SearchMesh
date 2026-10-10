# Runtime architecture

SearchMesh is deterministic infrastructure, not a model that mediates agent conversation. Agent SDK tools retain schemas and formatting; a synchronous custom client submits exact retrieval parameters through the HTTP gateway.

## Ownership and transaction boundaries

One SQLite WAL store holds runs, request subscriptions, jobs, attempts, immutable responses, events and explicit finding dependencies. Every mutable ownership/budget operation uses `BEGIN IMMEDIATE`. Provider I/O occurs outside transactions. Global concurrency is four workers; the default per-initiating-run limit is two active jobs. Subscribers do not consume worker slots.

`active_keys` has a composite primary key on workspace and execution identity. An ordinary caller can share ordinary in-flight work. A force-refresh caller cannot attach to a provider operation started before its own submission. Final responses are checked per subscriber; unsuitable ordinary responses trigger one fresh operation or an explicit error. Deadlines are per subscription, so a timed-out caller does not cancel another caller's work.

Requests preserve their idempotency keys across transport retries. A completed run rejects new work while allowing recovery of an existing idempotent request. Provider-attempt units are reserved transactionally, then converted to attempted units before outbound dispatch. Retries and recovery reserve another unit. Ambiguous failures remain counted; no exactly-once or billing claim is made.

## Recovery

Each claimed job receives an owner token, increasing generation and expiring lease. Heartbeats renew only matching ownership. On expiry, an attempt becomes ambiguous, the job is requeued with a new reservation, and the next worker increments the generation. The stale worker cannot publish its response. Fixture mode uses a two-second lease to demonstrate this; live mode uses thirty seconds. The fixture injection actually abandons the response after synthetic provider dispatch.

## Freshness and evidence

Provider retrieval metadata is parsed separately from local receipt time. Unknown age is not silently treated as fresh. A cache-bypassing provider operation is recorded as an explicit execution-time boundary, not a fabricated provider timestamp. Such a refresh does not guarantee the underlying source page changed recently.

Response content hashes exclude top-level transport metadata and echoed request parameters, while preserving substantive fields and ranking. A changed response can mark a registered finding `NEEDS_REVIEW`. Dependencies must be registered explicitly. The runtime does not infer causality from prose, merge conclusions, or declare findings false.

## Local security

The CLI binds loopback only. Bearer tokens map to workspace scopes. Every object API checks ownership. Same-origin browser writes require an exact origin match; the local UI session uses an HTTP-only, SameSite=Strict cookie. The handshake requires a custom header, an allowed local host, and a same-origin Fetch Metadata value when present. There is no permissive CORS. This trusts local loopback clients; it is not remote multi-tenant auth.

Provider endpoints are fixed, caller transport parameters are rejected, echoed API credentials are recursively redacted, result text is escaped, and CSP disallows external scripts. Request sizes, query lengths and raw provider responses are bounded. No arbitrary result URL fetcher is present.

## Explicit boundaries

Automatic reuse is exact-parameter only. Semantic matching, MCP, cloud deployment, distributed workers and full-page RAG are deferred. Existing upstream SerpApi adapters and caching are reused rather than rebranded. The runtime guarantees coordination policies under its tested local deployment boundary, not the truth of retrieved content or provider exactly-once execution.
