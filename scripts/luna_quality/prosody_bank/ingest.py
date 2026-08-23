"""Idempotent parser for S00-observed Luna take JSON and explicit pins."""
from __future__ import annotations
import datetime as dt, json, re, uuid
from pathlib import Path
from ..hashing import sha256_file
from .schema import PARSER_VERSION

TAKE_RE=re.compile(r"P(?P<phrase>\d+)_t(?P<take>\d+)\.json$")
def ingest_directory(store, source_root: str|Path, project_id: str, repo_root: str|Path|None=None):
    root=Path(source_root); repository=Path(repo_root or root); run_id=str(uuid.uuid4()); stats={"inserted":0,"unchanged":0,"errors":0,"run_id":run_id}
    pin_paths=list(root.glob("*_pins.json")); pins={}; pin_revisions={}
    with store.transaction() as db:
        db.execute("INSERT INTO ingest_runs VALUES (?,?,?)",(run_id,dt.datetime.now(dt.timezone.utc).isoformat(),project_id))
        for path in pin_paths:
            try:
                block=path.stem[:-5]; pins[block]=json.loads(path.read_text(encoding="utf-8"))
                pin_revisions[block]=_revision(db,project_id,_relative(path,repository),sha256_file(path),path.stat().st_mtime,run_id,"luna_pins_json")[0]
            except Exception as exc:
                stats["errors"]+=1; db.execute("INSERT INTO ingestion_errors(ingest_run_id,source_path,error_type,detail) VALUES (?,?,?,?)",(run_id,_relative(path,repository),type(exc).__name__,str(exc)))
        for path in sorted(root.glob("*/P*_t*.json")):
            match=TAKE_RE.match(path.name)
            if not match: continue
            try:
                row=json.loads(path.read_text(encoding="utf-8")); block=path.parent.name; phrase=f"P{int(match.group('phrase')):02d}"; take=int(match.group("take")); digest=sha256_file(path)
                rel=_relative(path,repository); revision,is_new=_revision(db,project_id,rel,digest,path.stat().st_mtime,run_id,"luna_take_json")
                if not is_new: stats["unchanged"]+=1; continue
                pin=pins.get(block,{}).get(phrase); why=row.get("why") or []
                decision="selected" if pin==take else ("not_selected" if pin is not None else ("rejected" if row.get("ok") is False and why else "unknown"))
                metrics=row.get("metrics") or {}; duration=metrics.get("dur"); syllables=row.get("n_syl")
                values=(revision,project_id,block,phrase,take,row.get("text"),None,syllables,duration,(syllables/duration if syllables is not None and duration else None),metrics.get("median_hz"),metrics.get("range_st"),metrics.get("tail_delta"),_relative_tail(metrics),metrics.get("final_glide"),metrics.get("final_rebound"),decision,json.dumps(why,ensure_ascii=False) if decision=="rejected" else None,json.dumps(metrics,ensure_ascii=False,sort_keys=True))
                db.execute("INSERT INTO takes(revision_id,project_id,block_id,phrase_id,take_id,text,sentence_class,syllable_count,duration,syllables_per_second,pitch_median_hz,pitch_range_st,tail_delta_st,relative_tail,final_glide_st_per_s,final_rebound_st,decision,rejected_reason,metrics_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",values)
                if pin==take: db.execute("INSERT OR IGNORE INTO selection_events(project_id,block_id,phrase_id,take_id,event_type,source_revision_id) VALUES (?,?,?,?,?,?)",(project_id,block,phrase,take,"selected",pin_revisions[block]))
                stats["inserted"]+=1
            except Exception as exc:
                stats["errors"]+=1; db.execute("INSERT INTO ingestion_errors(ingest_run_id,source_path,error_type,detail) VALUES (?,?,?,?)",(run_id,_relative(path,repository),type(exc).__name__,str(exc)))
    return stats
def _revision(db,project,path,digest,mtime,run_id,fmt):
    db.execute("INSERT OR IGNORE INTO sources(project_id,path,source_format) VALUES (?,?,?)",(project,path,fmt)); source=db.execute("SELECT id FROM sources WHERE project_id=? AND path=?",(project,path)).fetchone()[0]
    existing=db.execute("SELECT id FROM source_revisions WHERE source_id=? AND sha256=?",(source,digest)).fetchone()
    if existing: return existing[0],False
    cur=db.execute("INSERT INTO source_revisions(source_id,sha256,modified_time,parser_version,ingest_run_id) VALUES (?,?,?,?,?)",(source,digest,mtime,PARSER_VERSION,run_id)); return cur.lastrowid,True
def _relative(path,root):
    try:return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:return path.resolve().as_posix()
def _relative_tail(metrics):
    tail,rng=metrics.get("tail_delta"),metrics.get("range_st"); return tail/rng if tail is not None and rng else None
