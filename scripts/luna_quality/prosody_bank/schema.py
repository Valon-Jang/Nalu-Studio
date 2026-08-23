"""Versioned Prosody Bank schema."""
SCHEMA_VERSION = 1
PARSER_VERSION = "luna-take-json/1"

MIGRATIONS = [(1, """
CREATE TABLE ingest_runs(id TEXT PRIMARY KEY, started_at TEXT NOT NULL, project_id TEXT NOT NULL);
CREATE TABLE sources(id INTEGER PRIMARY KEY, project_id TEXT NOT NULL, path TEXT NOT NULL, source_format TEXT NOT NULL, UNIQUE(project_id,path));
CREATE TABLE source_revisions(id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id), sha256 TEXT NOT NULL, modified_time REAL, parser_version TEXT NOT NULL, ingest_run_id TEXT NOT NULL REFERENCES ingest_runs(id), UNIQUE(source_id,sha256));
CREATE TABLE takes(id INTEGER PRIMARY KEY, revision_id INTEGER NOT NULL UNIQUE REFERENCES source_revisions(id), project_id TEXT NOT NULL, block_id TEXT NOT NULL, phrase_id TEXT NOT NULL, take_id INTEGER NOT NULL, text TEXT, sentence_class TEXT, syllable_count INTEGER, duration REAL, syllables_per_second REAL, pitch_median_hz REAL, pitch_range_st REAL, tail_delta_st REAL, relative_tail REAL, final_glide_st_per_s REAL, final_rebound_st REAL, decision TEXT NOT NULL, rejected_reason TEXT, metrics_json TEXT NOT NULL);
CREATE TABLE selection_events(id INTEGER PRIMARY KEY, project_id TEXT NOT NULL, block_id TEXT NOT NULL, phrase_id TEXT NOT NULL, take_id INTEGER NOT NULL, event_type TEXT NOT NULL, source_revision_id INTEGER NOT NULL REFERENCES source_revisions(id), UNIQUE(source_revision_id,phrase_id,take_id,event_type));
CREATE TABLE ingestion_errors(id INTEGER PRIMARY KEY, ingest_run_id TEXT NOT NULL REFERENCES ingest_runs(id), source_path TEXT NOT NULL, error_type TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE INDEX idx_takes_identity ON takes(project_id,block_id,phrase_id,take_id);
CREATE INDEX idx_takes_decision ON takes(decision);
CREATE INDEX idx_source_revision_hash ON source_revisions(sha256);
""")]
