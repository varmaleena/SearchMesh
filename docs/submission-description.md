# Submission draft

## Project name
SearchMesh

## Track
Open-Source Integrations

## Project description
SearchMesh is an open-source Python extension that makes SerpApi retrieval shared, recoverable and inspectable across AI agent workers.

Agent teams can independently request the same information, accept different evidence ages, or lose a worker while a search is in progress. SearchMesh gives developers a local coordination layer for those situations. It connects through the existing client interface in serpapi-search-tools, so developers keep their models, agent frameworks and official SerpApi tools.

The runtime shares compatible in-flight searches, reuses responses only when they meet each caller's freshness policy, enforces attempt budgets and persists requests, jobs, attempts and immutable response IDs in SQLite. Heartbeat leases and ownership generations let abandoned retrieval jobs recover while preventing a stale worker from overwriting the recovered result. An execution inspector exposes what actually happened.

The included application demonstrates the integration through a practical scenario: researching a café business in Bengaluru. A user enters one question about competitors, published prices and customer complaints. Groq creates 2–4 research tasks and can choose a shared discovery step. Dependent workers use returned evidence to refine their searches. SerpApi supplies live results, and the application produces a source-linked answer with evidence gaps.

Judges can inspect the actual task plan, tool calls, retrieval jobs and response IDs; replay the same generated query stages through direct tools and SearchMesh; and run a separate worker-loss recovery probe. Sharing is reported only when it occurs. Different queries remain separate, and plans without overlap can correctly show equal provider-attempt counts.

The deliverable is an MIT-licensed installable Python package, persistent local gateway, working demonstration UI, integration example and automated tests. Its contribution is the retrieval runtime beneath existing tools.

## How the project uses SerpApi
Live workers invoke the official serpapi-search-tools Python package's web_search tool, using Google Light in the demonstrated workflow. SearchMeshClient implements its documented synchronous search(params) -> dict contract. The official tool translates and validates inputs, then passes retrieval parameters to SearchMesh. The gateway coordinates the request and calls SerpApi's /search.json endpoint when a provider operation is needed.

SerpApi supplies the titles, links, snippets and retrieval metadata used by research workers and final synthesis. Actual responses drive freshness decisions, provenance, trace inspection and paired replay. Without SerpApi, the live application cannot gather current evidence or demonstrate real provider execution. Fixture mode is explicitly synthetic and used separately for deterministic tests.

## AI tools used
OpenAI Codex assisted project design, implementation, UI development, documentation, debugging and verification. Groq-hosted model inference powers planning, dependent-query refinement and synthesis. Google Gemini was used during earlier model integration and testing. Add any other tools personally used before submitting.

## Remaining form fields
- Public GitHub repository: https://github.com/varmaleena/SearchMesh
- Demo video: pending public Google Drive link; under three minutes.
- Lead name, email, mobile, occupation and experience: participant supplied.
- Additional team members: actual contributors only.
- Community source: participant's actual answer.
- Existed before hackathon: participant must confirm relative to September 1, 2026.
- Rules and Terms: participant must read and accept personally.
- Accessibility checkbox: confirm only after testing both public links logged out.

Drafts are not submitted automatically. Deadline: October 10, 2026 at 23:59 IST. See [official Rules](https://serpapi.github.io/serpapi-india-hackathon-2026/rules.html).
