# Contributing

Create a virtual environment with Python 3.11–3.13 and install `python -m pip install -e ".[test]"`. Run `python -m pytest tests -q` before opening a pull request. Most runtime tests use a deterministic fixture and require no credentials.

For a change to coordination, add a test that exercises the relevant concurrency, freshness, ownership or failure boundary. Keep provider I/O outside SQLite transactions. Preserve query qualifiers and workspace isolation.

Never commit `.env`, provider credentials, local databases, logs or personal research history. Live checks use your own provider quota and should be explicit. Label fixture measurements as synthetic and keep attempts distinct from billed credits.

Explain the behavior change and relevant verification in your pull request. See README.md and docs/architecture.md for the current local deployment boundary.
