# Integrating SearchMesh

SearchMesh uses the existing `client=` interface in `serpapi-search-tools`. Install SearchMesh from this checkout, start the gateway, create a run, and pass the client into the official tool. Full installation steps and code are in the [README](../README.md).

## Complete runnable example

Start the live gateway, export its local access token as `SEARCHMESH_GATEWAY_TOKEN` in your agent shell, then run:

```sh
python examples/shared_search.py
```

For a fixture gateway, set `SEARCHMESH_GATEWAY_URL` to `http://127.0.0.1:8000`. The example deliberately sends two identical requests to demonstrate the contract. Real application queries are generated from the user's question.

## Configuration

| Setting | Meaning |
| --- | --- |
| gateway_url | Running local gateway address. |
| token | Gateway token, separate from the SerpApi key. |
| workspace_id | Authorized scope; dashboard uses demo. |
| run_id | Investigation identity shared by workers, obtained from create_run(). |
| agent_id | Calling worker identity; use one client per worker. |
| max_age_seconds | Oldest acceptable retrieved response; default 300. |
| deadline_seconds | Caller wait deadline; live examples use 120. |
| force_refresh | Requires a fresh-operation boundary; can reduce sharing. |
| budget_limit | Run provider-attempt units, including retries and recovery; not a billing estimate. |

The official library retains schemas, SDK adapters and formatting. SearchMesh handles translated retrieval parameters. Engine, locale, query qualifiers and filters remain part of identity; different searches are not semantically merged.

## Your existing agent framework

Install your chosen SDK and construct its normal official search tool with `client=mesh` and the explicit provider name. Attach that tool through your framework's documented API. The synchronous function-provider contract is directly tested. Other SDK/model combinations need their own integration checks. The optional Google ADK example requires `.[demo]` and Gemini; it is not required by the core runtime.

Groq is needed by the included model-planned research application, not by the retrieval adapter. The gateway alone can serve agent clients with just a SerpApi credential.

## Evidence and reports

`client.search(params)` returns the SerpApi dictionary the upstream tools expect. `client.search_with_metadata(params)` returns the gateway envelope, including provenance identifiers. Compact official tool output may omit transport metadata.

Generic client-created runs can be inspected through the authenticated `/v1/runs/{run_id}/report` endpoint. They do not automatically become model-planned application workflows.

## Troubleshooting

- Invalid gateway token: export the token from the current server in the agent process; it is not your SerpApi key.
- Connection refused: start the gateway and match its port.
- No run ID: create a run once and pass its ID to other workers.
- Zero joins: queries/policies may differ, response reuse may already be available, or calls may not overlap. This is valid.
- Fixture results: port 8000 is synthetic by default; live mode needs SerpApi.
- Model error: check Groq model availability and quota for the included application.

See [architecture](architecture.md) for local deployment and recovery boundaries.

## Supported output and engines

Set `response_format=SearchResultFormat.JSON` when constructing the official tool. SearchMesh returns dictionaries; upstream Markdown transport requires strings and is not supported by this client contract. The current gateway accepts google_light, google and google_news; other engines are rejected.
