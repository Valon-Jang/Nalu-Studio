"""Stable, read-only joins used by preference-dataset construction."""

import json


def take_history(connection, project_id):
    return connection.execute("SELECT t.*,s.path,r.sha256,r.modified_time,r.parser_version,r.ingest_run_id,s.source_format FROM takes t JOIN source_revisions r ON r.id=t.revision_id JOIN sources s ON s.id=r.source_id WHERE t.project_id=? ORDER BY t.block_id,t.phrase_id,t.take_id,r.id",(project_id,)).fetchall()


def selected_with_features(connection, project_id):
    return connection.execute("SELECT t.*,e.event_type,s.path AS selection_source_path,r.sha256 AS selection_source_sha256 FROM takes t JOIN selection_events e ON e.project_id=t.project_id AND e.block_id=t.block_id AND e.phrase_id=t.phrase_id AND e.take_id=t.take_id JOIN source_revisions r ON r.id=e.source_revision_id JOIN sources s ON s.id=r.source_id WHERE t.project_id=?",(project_id,)).fetchall()


def ranking_training_rows(connection, project_id=None):
    """Export the latest explicit pin groups without inventing gate evidence.

    Older S06 rows do not persist an explicit hard-gate pass bit. Such rows are
    returned with ``hard_gate_pass=False`` and therefore fail closed in S07.
    """
    where = "WHERE t.decision IN ('selected','not_selected')"
    params = ()
    if project_id is not None:
        where += " AND t.project_id=?"
        params = (project_id,)
    rows = connection.execute(
        "SELECT t.*,r.sha256 AS source_sha256,r.id AS revision_order,"
        "(SELECT pin_revision.sha256 FROM selection_events event "
        "JOIN source_revisions pin_revision ON pin_revision.id=event.source_revision_id "
        "WHERE event.project_id=t.project_id AND event.block_id=t.block_id "
        "AND event.phrase_id=t.phrase_id AND event.take_id=t.take_id "
        "ORDER BY event.id DESC LIMIT 1) AS selection_source_sha256 "
        "FROM takes t JOIN source_revisions r ON r.id=t.revision_id "
        f"{where} ORDER BY r.id",
        params,
    ).fetchall()
    latest = {}
    for source in rows:
        row = dict(source)
        metrics = json.loads(row.pop("metrics_json") or "{}")
        gate_status = str(metrics.get("hard_gate_status", "")).lower()
        if metrics.get("hard_gate_pass") is True or gate_status == "pass":
            gate_status = "pass"
        elif metrics.get("hard_gate_pass") is False or gate_status == "fail":
            gate_status = "fail"
        else:
            gate_status = "unknown"
        row["hard_gate_status"] = gate_status
        row["hard_gate_pass"] = gate_status == "pass"
        row["features"] = metrics
        identity = (row["project_id"], row["block_id"], row["phrase_id"], row["take_id"])
        latest[identity] = row
    return [latest[key] for key in sorted(latest)]
