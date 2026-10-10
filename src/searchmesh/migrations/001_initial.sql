CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY, credential_scope_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), title TEXT NOT NULL,
 budget_limit INTEGER NOT NULL CHECK(budget_limit >= 0), reserved_units INTEGER NOT NULL DEFAULT 0 CHECK(reserved_units >= 0),
 attempted_units INTEGER NOT NULL DEFAULT 0 CHECK(attempted_units >= 0), status TEXT NOT NULL DEFAULT 'ACTIVE',
 created_at REAL NOT NULL, CHECK(reserved_units + attempted_units <= budget_limit));
CREATE TABLE IF NOT EXISTS searches(
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), run_id TEXT NOT NULL REFERENCES runs(id),
 fingerprint TEXT NOT NULL, execution_key TEXT NOT NULL, params_json TEXT NOT NULL, refresh INTEGER NOT NULL,
 state TEXT NOT NULL, owner_token TEXT, generation INTEGER NOT NULL DEFAULT 0, lease_until REAL,
 attempt_count INTEGER NOT NULL DEFAULT 0, response_id TEXT, not_before REAL NOT NULL DEFAULT 0,
 created_at REAL NOT NULL, started_at REAL, finished_at REAL, error_code TEXT, error_message TEXT);
CREATE TABLE IF NOT EXISTS active_keys(
 workspace_id TEXT NOT NULL, execution_key TEXT NOT NULL, search_id TEXT NOT NULL REFERENCES searches(id),
 PRIMARY KEY(workspace_id, execution_key));
CREATE TABLE IF NOT EXISTS responses(
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), fingerprint TEXT NOT NULL,
 raw_json TEXT NOT NULL, content_hash TEXT NOT NULL, received_at REAL NOT NULL,
 upstream_created_at REAL, age_basis TEXT NOT NULL, effective_at REAL, source_kind TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requests(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), workspace_id TEXT NOT NULL REFERENCES workspaces(id),
 agent_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, policy_json TEXT NOT NULL,
 search_id TEXT REFERENCES searches(id), response_id TEXT REFERENCES responses(id), status TEXT NOT NULL,
 decision TEXT NOT NULL, reason TEXT NOT NULL, created_at REAL NOT NULL, deadline_at REAL NOT NULL,
 finished_at REAL, error_code TEXT, error_message TEXT, refresh_count INTEGER NOT NULL DEFAULT 0,
 UNIQUE(run_id, idempotency_key));
CREATE TABLE IF NOT EXISTS attempts(
 id TEXT PRIMARY KEY, search_id TEXT NOT NULL REFERENCES searches(id), run_id TEXT NOT NULL REFERENCES runs(id),
 generation INTEGER NOT NULL, started_at REAL NOT NULL, finished_at REAL, outcome TEXT NOT NULL,
 provider_search_id TEXT, cost_status TEXT NOT NULL DEFAULT 'UNKNOWN');
CREATE TABLE IF NOT EXISTS events(
 id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(id),
 search_id TEXT, request_id TEXT, kind TEXT NOT NULL, data_json TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS findings(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), text TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'CURRENT', created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS dependencies(
 finding_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
 response_id TEXT NOT NULL REFERENCES responses(id), PRIMARY KEY(finding_id,response_id));
CREATE INDEX IF NOT EXISTS response_lookup ON responses(workspace_id,fingerprint,received_at DESC);
CREATE INDEX IF NOT EXISTS request_run ON requests(run_id,status);
CREATE INDEX IF NOT EXISTS job_schedule ON searches(state,not_before,lease_until);
CREATE INDEX IF NOT EXISTS event_run ON events(run_id,id);
CREATE INDEX IF NOT EXISTS dependency_response ON dependencies(response_id);

