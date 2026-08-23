"""Stable joins used by later preference-dataset construction."""
def take_history(connection, project_id):
    return connection.execute("SELECT t.*,s.path,r.sha256,r.modified_time,r.parser_version,r.ingest_run_id,s.source_format FROM takes t JOIN source_revisions r ON r.id=t.revision_id JOIN sources s ON s.id=r.source_id WHERE t.project_id=? ORDER BY t.block_id,t.phrase_id,t.take_id,r.id",(project_id,)).fetchall()
def selected_with_features(connection, project_id):
    return connection.execute("SELECT t.*,e.event_type,s.path AS selection_source_path,r.sha256 AS selection_source_sha256 FROM takes t JOIN selection_events e ON e.project_id=t.project_id AND e.block_id=t.block_id AND e.phrase_id=t.phrase_id AND e.take_id=t.take_id JOIN source_revisions r ON r.id=e.source_revision_id JOIN sources s ON s.id=r.source_id WHERE t.project_id=?",(project_id,)).fetchall()
