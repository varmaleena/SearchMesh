# Final recording: under three minutes

Audience: developers operating concurrent agent teams. Track: Open-Source Integrations.

## Before recording

Use the live server on port 8001. Open a fresh page. Research, execution and benchmark results should be empty; archived history is hidden. Prepare one question with a concrete goal and constraints. The planner chooses its own tasks. Have credentials and provider quota configured. A comparison makes additional provider requests; counts depend on the generated plan and retries. Do not record credentials or terminal tokens.

## Script

0:00–0:15 — Say: “SearchMesh is an open-source client adapter for developers running agent teams. It shares compatible retrieval work and keeps search jobs durable and inspectable.”

0:15–0:45 — Enter one question. Start live research. Show Groq creating task assignments and objectives, then worker states and SerpApi source cards arriving. If real processing is slow, disclose an edit rather than substituting fixture results.

0:45–1:10 — Open How SearchMesh works. Point to existing agents/Groq, our adapter, and existing SerpApi. Read actual joins, reuse, completed jobs and failures. If the planner selected shared context, show its reason and how workers adapted queries from the evidence. If there is no overlap, show zero joins honestly.

1:10–1:50 — Start Compare direct vs SearchMesh. Both paths replay the same frozen queries through the official tools. Show actual attempts, failures and wall time. State this is one sequential trial of this plan, with fresh retrieval normalized in both replay paths; do not claim typical savings or guaranteed faster execution.

1:50–2:25 — Expand implementation. Inspect the shared job and response. Start the separate injected-worker-failure probe only if time permits; live lease recovery takes at least 30 seconds. Show an ambiguous abandoned attempt, lease reclamation, new ownership generation and returned evidence. Explain recovery may repeat upstream work.

2:25–2:45 — Developer integration: show `web_search(client=mesh)` and the public repository/setup. The official package still owns tool schema and validation; our package owns shared transport and execution.

2:45–2:55 — Export a trace/comparison. Close with: “Keep your agents and SerpApi tools. Add durable, inspectable retrieval coordination beneath them.”

## Avoid

Do not describe deterministic workers as autonomous reasoning agents. Do not claim search deduplication was invented here. Do not confuse attempts with billed credits. Do not conceal failed branches or compare paths that used different query manifests. Do not claim public distribution until repository and video links are verified.

## Local preview recording

A silent live recording is available at `reports/demo/SearchMesh-live-demo.webm` (112.84 seconds). It shows one-question planning, four workers, actual search evidence, a comparison with equal attempts, recovery and integration. It is a technical developer example. Record your chosen real-world question for the final submission if preferred. Public/unlisted hosting is still required.
