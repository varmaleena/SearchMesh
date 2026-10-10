## Public-release verification

October 10, 2026: 64 tests passed against the curated public source tree. The README two-worker integration example ran successfully through a real local fixture gateway. JSON output is explicitly configured. Credentials, databases, logs and research history are excluded.

# Final verification — 10 October 2026

## Regression and browser checks

59 tests passed. Covered real tool/client integration, canonical parameters, sharing/reuse, freshness, budget reservations, idempotency, isolation, deadlines, ownership fencing, evidence dependencies, comparison replay and its failure counts. Five warnings concern upstream TestClient deprecations.

Browser acceptance passed: stale session storage ignored; previous runs hidden by default; custom question drives queries; source results and execution trace populate from that run; paired comparison completes through real tool clients; a separate injected recovery probe retains original research; New research clears current data; mobile layout has no horizontal overflow. Technical inspector remains open during polling.

## Earlier measured live comparison — legacy conformance workload

Source run: `run-bf4162c3048f4c76` (Python 3.13 migration research).

| Path | Logical calls | Provider attempts | Failed calls | Wall time |
|---|---:|---:|---:|---:|
| Direct official tools | 7 | 9 | 0 | 73,028.70 ms |
| SearchMesh adapter | 7 | 4 | 0 | 40,412.26 ms |

The direct path included two retry attempts. SearchMesh recorded two in-flight joins and one fresh reuse. Seven identical frozen call parameters were replayed in each path. First six calls required fresh provider operations; final repeat permitted reuse. Provider concurrency was capped at two. Direct ran before mesh. This is one controlled sequential trial with intentional repeats; it does not prove statistical latency superiority, typical savings, equivalent answer quality or billed-credit savings. Raw local export: `reports/live-paired-comparison.json`.

## Measured live recovery

Separate injected failure using the same approved Python research task. Completed with two provider attempts: `AMBIGUOUS_WORKER_LOSS`, then `SUCCEEDED`. `lease_reclaimed` event present. The injected loss was simulated; provider operations and lease recovery were real. Recovery may repeat upstream work. Raw local export: `reports/live-recovery-proof.json`.

## Bugs resolved

- Malformed frontend selectors prevented workflow script initialization.
- Old browser workflow storage and archived results confused the initial state.
- Worker dispatch time sampled before transaction acquisition could precede a caller's commit, causing false freshness failures. Time is now sampled inside the lock.
- Reused reports imported provider-added default parameters. They now preserve source-job canonical parameters and fingerprint.
- Tool failures lost their error code; partial completion omitted editor/shared-subscriber failures.
- Provider timeouts could leave insufficient room for bounded retries; timeout is now 30 seconds per attempt.
- Model stages did not mark interrupted planning/synthesis as failed. They do now; transient API/structured-output rejection gets bounded retries.
- Answer layout used an inline style rejected by the CSP. It now uses the stylesheet.
- Setup and recording docs described an obsolete fixed-query/Gemini workflow.

## Remaining boundaries

No unique-invention claim; exact deduplication and durable queues are established techniques. This project integrates them beneath official SerpApi tools. Local single-gateway scope, at-least-once recovery, exact matching only, snippets rather than independently verified pages. The demo has model-planned branches and deterministic orchestration. Public repository, public video and hackathon submission require participant publication and details.

## Distribution checks

Built `dist/searchmesh_runtime-0.1.0-py3-none-any.whl`. Installed it into an isolated target directory without the editable source; package import, dashboard and packaged JS/CSS asset requests passed. Final live browser checks passed for answer formatting, paired measurement rendering, CSP/console errors and mobile layout. A curated source archive excludes credentials, local databases, run history and caches; scanned against configured credential values before delivery.

## One-question automatic delegation update

62 tests pass after adding automatic plan validation, variable-size comparisons, independent plans with zero manufactured sharing, and shared dependencies whose returned evidence is actually used by delegated workers to refine queries. The user now provides one question; Groq chooses 2–4 tasks. Shared context is optional. No editor repeat is added. The comparison replays the actual query stages without adding duplicates, with fresh retrieval normalized in both paths.

A live automatic run `run-51f4b3d36ff24876` completed with three model-selected independent tasks, three requests, three provider attempts and zero failures/joins/reuses. Zero sharing was expected because the model chose no common dependency. This is separate from the earlier legacy nine-versus-four comparison. Live automatic results and any demo recording are in `reports/automatic-live-verification.json` and `reports/demo/` locally.

Latest live automatic demonstration: `run-d2e688ba18b3495b`. One question produced four independently delegated tasks, four calls, three provider attempts and one valid fresh reuse, with zero failures. Cold normalized replay made four attempts in each path with zero failures; no sharing benefit was manufactured. The separate live recovery probe completed with two attempts and a lease reclamation. Silent screen recording `reports/demo/SearchMesh-live-demo.webm` was decoded by the browser and verified at 112.84 seconds, under three minutes. A recorded frame was visually inspected. Browser acceptance includes opening returned evidence from trace nodes and avoiding stale-poll selection overwrites.
