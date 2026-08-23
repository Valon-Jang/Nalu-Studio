# S06 Prosody Bank

The bank is a local SQLite database containing `ingest_runs`, `sources`,
`source_revisions`, `takes`, `selection_events`, `ingestion_errors`, and
`schema_migrations`. Foreign keys are enabled and ingest runs use one explicit
transaction. Audio remains outside the database.

Every source revision records repository-relative path when possible, SHA-256,
modified time, parser version, ingest run, and source format. Re-ingesting the
same source hash is idempotent; a changed hash creates a revision.

Decision meanings are strict:

- `selected`: the take is explicitly named by a pins file.
- `not_selected`: that phrase has an explicit pin naming another take.
- `rejected`: the take row has `ok=false` and explicit rejection reasons.
- `unknown`: no supported evidence establishes the selection meaning.

Automatic block-report picks never become human selections. Selection events
reference the pins-file revision so their source path and hash remain queryable.
