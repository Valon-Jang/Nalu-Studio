#!/usr/bin/env python3
"""Luna narration pipeline v1 — THE single entry point for 공대루나 narration.

CEO-validated 2026-08-05 on SUBSEA B04 A/B (B > A), pause ladder -> B4:
  - phrase split ~10 syllables (신비한건축사전 rhythm, LUNA_PROSODY_TARGET.json)
  - per-phrase best-of-N Chatterbox takes, gated on rate/end-slope/range
  - numeral-heavy phrases get a relaxed rate floor (years ARE read slowly)
  - beam-search assembly for pitch continuity (reset gate -4..+13 st, tgt +4.65)
  - continuation pause 0-0.02s (CEO: '바로 연결이 너무 좋다'), final 0.38-0.60s
  - block end-slope median must land in [-20,-5] st/s
  - checkpointed per take: kill/rerun resumes

Usage:
  python luna_narration_pipeline_v1.py JOBS.json OUTDIR
  JOBS.json = {"blocks":[{"id":"B01","text":"...","seed":123}, ...]}

Output per block: OUTDIR/<id>/P*.wav takes, OUTDIR/<id>_luna.wav final,
OUTDIR/<id>_report.json, plus OUTDIR/pipeline_report.json overall.
"""
from __future__ import annotations
import json, math, os, random, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "engine" / "chatterbox-v3"
REF = ROOT / "assets" / "voice_ref" / "B_voiced_spectral_micro_smooth.wav"

QUALITY_FEATURE_DEFAULTS = {
    "LUNA_QUALITY_MODE": "off",
    "LUNA_CONDITIONALS_CACHE": "off",
    "LUNA_ASR_VALIDATOR": "off",
    "LUNA_SPEAKER_VALIDATOR": "off",
    "LUNA_MOS_VALIDATOR": "off",
    "LUNA_PREFERENCE_RANKER": "off",
    "LUNA_HYBRID_SYNTHESIS": "off",
}
QUALITY_SETTING_NAMES = (
    "LUNA_QUALITY_REPORT_DIR",
    "LUNA_CONDITIONALS_CACHE_DIR",
    "LUNA_RANKER_ARTIFACT",
    "LUNA_SPEAKER_CALIBRATION_ARTIFACT",
    "LUNA_SELECT_APPROVAL_MANIFEST",
)


def quality_integration_requested(environ=None):
    source = os.environ if environ is None else environ
    return any(
        str(source.get(name, default)).strip().lower() != default
        for name, default in QUALITY_FEATURE_DEFAULTS.items()
    ) or any(str(source.get(name, "")).strip() for name in QUALITY_SETTING_NAMES)


def write_quality_import_fallback(outdir, error, environ=None):
    """Best-effort diagnostic when the optional integration cannot import."""
    temporary = None
    try:
        source = os.environ if environ is None else environ
        output = Path(outdir).resolve()
        configured = str(source.get("LUNA_QUALITY_REPORT_DIR", "")).strip()
        report_root = Path(configured) if configured else output.parent / f"{output.name}.luna_quality_reports"
        if not report_root.is_absolute():
            report_root = ROOT / report_root
        report_root = report_root.resolve()
        try:
            report_root.relative_to(output)
            report_root = output.parent / f"{output.name}.luna_quality_reports"
        except ValueError:
            pass
        report_root.mkdir(parents=True, exist_ok=True)
        destination = report_root / "startup_fallback.json"
        temporary = report_root / f".startup_fallback.json.tmp-{os.getpid()}"
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": "luna-production-integration/1",
                    "status": "fallback",
                    "reason": f"integration_import_exception:{type(error).__name__}",
                    "production_selection_changed": False,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
        return destination
    except Exception:
        return None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

# ---- CEO-validated parameters (see LUNA_PROSODY_TARGET.json) ----
N_TAKES = 6
EARLY_STOP_MIN_TAKES = 3
EARLY_STOP_MIN_PASSING = 2
EARLY_STOP_QUALITY = -3.0
EXAG, CFG, TEMP = 0.5, 0.5, 0.72
# escalation: if the whole pool yields ZERO gate-passing takes, add takes at
# higher temperature (more contour variety). Evidence: B02 케이블일까요 —
# 10 deterministic takes all missed the question band (2026-08-06). A second
# round exists because 8/38 SUBSEA phrases still missed after round 1
# (mostly the high-register attack that the level gate rejects).
ESCALATION_TAKES = 6
# r2+ capped at 0.87: a 0.90-temp take produced a consonant distortion
# (긴 구간 -> '킨 구간', SUBSEA B03 P03, CEO caught it 2026-08-06).
# Third round = 6 more NOVEL seeds for stubborn phrases (seeds are k-derived,
# so re-running an exhausted pool can never produce new audio).
ESCALATION_TEMPS = (0.85, 0.87, 0.87)
RATE_TGT = 6.54
RATE_BAND = (5.6, 7.2)
RATE_BAND_NUMERIC = (4.4, 7.2)     # 천팔백오십팔년 etc. read slowly — that's natural
END_SLOPE_HARD = (-35.0, 8.0)
END_SLOPE_PRIOR = -12.0
BLOCK_MEDIAN_BAND = (-20.0, -5.0)
RESET_GATE = (-4.0, 13.0)
RESET_TGT = 4.65
PAUSE_CONT = (0.00, 0.02)          # CEO pick: B4, 사실상 바로 연결
PAUSE_FINAL = (0.38, 0.60)
# forced-piece joins need a hair more room: instant cut after a sustained
# ending reads as a sudden mute (CEO: '부분과 다음에 순간 음소거가 되는데??')
PAUSE_FORCED = (0.05, 0.10)
RANGE_SANITY = (4.0, 15.0)
MIN_SYL, MAX_SYL, JOIN_TGT = 7, 22, 14
NUMERAL_CHARS = set("영일이삼사오육칠팔구십백천만조")

# Question phrases (-까요 etc.): CEO-validated contour = GENTLE fall.
# Evidence (SUBSEA 2026-08-05): 건널까요 -6.63 GOOD; 갈까요 -1.0 flat BAD;
# 케이블일까요 -11.43 steep BAD. Statement prior (-12) must NOT apply.
QUESTION_ENDINGS = ("까요", "나요", "가요")
# CEO round 2 (2026-08-06): -4.33 still "덜 떨어짐" -> tighten shallow edge to
# -5 (건널까요 -6.63 GOOD center; 케이블일까요 -11.43 too steep keeps -10 edge)
QUESTION_SLOPE_BAND = (-10.0, -5.0)
QUESTION_SLOPE_PRIOR = -6.5

# Absolute pitch-level gate. CEO round 2: year phrases 오십팔년(264Hz)/
# 육십육년(307Hz) sounded off vs 육십오년(237Hz GOOD) — same slopes, the bad
# takes FLOAT above Luna's normal register the whole phrase. Anchor = median
# of CEO-good picks (234.9-237Hz).
LEVEL_ANCHOR_HZ = 235.0
LEVEL_BAND_ST = 2.0

# Tail gates (SPIDER CEO feedback 2026-08-06, refined by CEO: "그냥 떨어지고
# 안떨어지고보다 상대 낙폭이 필요해"). Two conditions, sentence-final only —
# continuations legitimately sustain (돕지만 -0.85 GOOD):
#  1) absolute: last-0.25s vs prev-0.35s (st) <= -1.5
#  2) RELATIVE fall: tail_delta / phrase range (p90-p10 st) <= -0.28.
# Calibration — REL separates all labels where absolute alone missed 이에요:
# BAD  낮아요 +0.16 / 넘어서죠 -0.04 / 만들어질까요 -0.02 / 밀리지 +0.03 / 이에요 -0.26
# GOOD 건널까요 -0.30 / 되죠 -0.43 / 가라앉았습니다 -0.45
# (넘어서죠 lands LOW (-3.7st) yet was rejected — landing point doesn't matter,
#  fall depth relative to the phrase's own span does.)
TAIL_DELTA_MAX = -1.5
TAIL_REL_MAX = -0.28
# Question finals under the SAME 직전-대비 principle (CEO audit 2026-08-06:
# '가능할까요도 직전 음절 대비 낙폭으로 설정된 게 아닌데?'). Questions need a
# LOWER bound too — falling like a statement was rejected. Calibration:
# GOOD 건널까요 tail -2.1 rel -0.30 / REJ steep 케이블일까요 -4.8 rel -0.42 /
# REJ weak 갈까요 -0.95 rel -0.11 / REJ rise 가능할까요 +0.45 rel +0.05.
# Window slope band kept only as fallback when tail is unmeasurable.
QUESTION_TAIL_BAND = (-4.0, -1.5)
QUESTION_REL_BAND = (-0.40, -0.25)
# Final RELEASE CURL (CEO round 3, 2026-08-06: '요는 마침이니까 확실히
# 떨어뜨려버려'). Measured discovery: what reads as a decisive close is a
# STEP DOWN into the final syllable PLUS a small natural release curl —
# the last 0.2s glides gently UP (~+9..+13 st/s, rebound ~3-3.7st).
# Rejected takes either plunge late (-15..-18, swallowed) or stay flat
# (glide +3, rebound <=1, floating). Gate: glide >= +4 AND rebound >= 2.5.
FINAL_GLIDE_MIN = 4.0
FINAL_REBOUND_MIN = 2.5
N_TAKES_QUESTION = 10
# questions stretch their endings naturally; hard 5.6 floor rejected the ONLY
# correct-contour take (t8 -4.33 @ 5.47 syl/s, B01 2026-08-06) — relax floor
RATE_BAND_QUESTION = (5.2, 7.2)

# Forced-split continuation pieces (no comma/connective at the cut) must NOT
# sound sentence-final. Evidence (SUBSEA B02 2026-08-05): '섬유에' (particle
# ending) all takes fell -25..-35 -> read as sentence end, CEO rejected;
# '돕지만' +1.05/-2.62 level sustain, CEO approved.
FORCED_SLOPE_BAND = (-8.0, 4.0)
FORCED_SLOPE_PRIOR = -2.0
N_TAKES_FORCED = 10
# preferred left-word endings when choosing a forced cut point (converb-like,
# model sustains these naturally; 과/와 = coordination boundary); worth up to
# 6 syllables of imbalance
GOOD_CUT_ENDINGS = ("어", "아", "고", "서", "며", "면", "지", "게", "다", "과", "와",
                    "처럼")
# NEVER cut after an adnominal modifier — it binds to the following noun.
# Evidence: '...유연한 | 부분이...' split, CEO: '유연한 다음 끊기니까 이상한데'
# 에서(locative) binds to its verb phrase: '손목에서 | 거미줄을' rejected,
# CEO: '손목에서 쉬지말고 거미줄을이랑 이어버리자'
BAD_CUT_ENDINGS = ("한", "된", "진", "인", "에서")

RESPELL = {
    "굳힌다는": "구친다는", "굳힌다": "구친다",
    "끊깁니다": "끈킵니다", "끊기는": "끈키는", "끊어져": "끄너져",
    "끊어진": "끄너진", "끊깁": "끈킵",
}
CONNECTIVES = ("고", "서", "며", "면", "데", "만", "져", "쳐", "라", "니", "다")


def is_question(text):
    return text.rstrip(". ").endswith(QUESTION_ENDINGS)


def syl(t):
    return sum(1 for c in t if "가" <= c <= "힣")


def numeral_heavy(t):
    return sum(1 for c in t if c in NUMERAL_CHARS) >= 3


def respell(t):
    for a, b in RESPELL.items():
        t = t.replace(a, b)
    return t.replace("?", ".")


def split_sentences(text):
    out, cur = [], ""
    for ch in text:
        cur += ch
        if ch == "." and syl(cur) > 0:
            out.append(cur.strip())
            cur = ""
    if cur.strip():
        out.append(cur.strip())
    return out


def split_phrases(sentence):
    toks = []
    for part in sentence.split(","):
        part = part.strip()
        if not part:
            continue
        words = part.split(" ")
        cur = ""
        for i, w in enumerate(words):
            cur = (cur + " " + w).strip()
            is_last = i == len(words) - 1
            # 에서(locative)의 '서'는 연결어미가 아님 — 동사구에 붙는다
            if (not is_last and any(w.endswith(c) for c in CONNECTIVES)
                    and not w.endswith("에서") and syl(cur) >= 4):
                toks.append(cur)
                cur = ""
        if cur:
            toks.append(cur)
    phrases = []
    for tk in toks:
        if phrases and syl(phrases[-1]) + syl(tk) <= JOIN_TGT:
            phrases[-1] = phrases[-1] + " " + tk
        else:
            phrases.append(tk)
    merged = []
    for p in phrases:
        if merged and (syl(p) < MIN_SYL or syl(merged[-1]) < MIN_SYL) \
                and syl(merged[-1]) + syl(p) <= MAX_SYL:
            merged[-1] = merged[-1] + " " + p
        else:
            merged.append(p)
    out = []
    for p in merged:
        out.extend(force_split(p))
    return out


def force_split(text):
    """Split text over MAX_SYL at scored word boundaries. Prefer a cut whose
    left word ends converb-like (model sustains those); a good ending is worth
    up to 6 syllables of imbalance. Left pieces are forced=True so the sustain
    gate applies (they must not sound sentence-final)."""
    out = []  # (text, forced)
    stack = [text]
    while stack:
        q = stack.pop(0)
        if syl(q) <= MAX_SYL or " " not in q:
            out.append((q, False))
            continue
        words = q.split(" ")
        best, bests = 1, -1e9
        for cut in range(1, len(words)):
            score = -abs(syl(" ".join(words[:cut])) - syl(q) / 2)
            if words[cut - 1].endswith(GOOD_CUT_ENDINGS):
                score += 6.0
            if words[cut - 1].endswith(BAD_CUT_ENDINGS):
                score -= 8.0
            if score > bests:
                best, bests = cut, score
        left, right = " ".join(words[:best]), " ".join(words[best:])
        out.append((left, True))
        stack = [right] + stack
    return out


def build_phrase_list(text):
    items = []
    for s in split_sentences(text):
        ps = split_phrases(s)
        for j, (ptxt, forced) in enumerate(ps):
            items.append({"text": ptxt, "sentence_final": j == len(ps) - 1,
                          "forced": forced})
    # a lone tiny final phrase merges backward even across the sentence edge
    for i in range(1, len(items)):
        if syl(items[i]["text"]) < 4 and not items[i - 1]["sentence_final"]:
            items[i - 1]["text"] += " " + items[i]["text"]
            items[i - 1]["sentence_final"] = items[i]["sentence_final"]
            items[i - 1]["forced"] = items[i]["forced"]
            items[i]["text"] = ""
    items = [it for it in items if it["text"]]
    # safety net: the backward merge may re-create an over-long phrase
    # (SPIDER B08 '정리하면...줍니다.' 25 syl, 2026-08-06) — force-split it
    final = []
    for it in items:
        pieces = force_split(it["text"])
        for j, (ptxt, forced) in enumerate(pieces):
            last = j == len(pieces) - 1
            final.append({"text": ptxt,
                          "sentence_final": it["sentence_final"] and last,
                          "forced": forced or (it["forced"] and last)})
    return final


def measure_take(arr, sr):
    import librosa
    import numpy as np
    y = arr.astype("float64")
    y = y / (np.max(np.abs(y)) + 1e-9)
    yt, idx = librosa.effects.trim(y, top_db=35)
    dur = len(yt) / sr
    if dur < 0.25:
        return None
    f0, _, _ = librosa.pyin(yt, fmin=80, fmax=400, sr=sr,
                            frame_length=2048, hop_length=256, fill_na=np.nan)
    tt = librosa.frames_to_time(np.arange(len(f0)), sr=sr, hop_length=256)
    v = np.isfinite(f0)
    if v.sum() < 10:
        return None
    vhz = f0[v]
    med = float(np.median(vhz))
    st = 12 * np.log2(np.where(v, f0, med) / med)
    st[~v] = np.nan
    rng = float(np.nanpercentile(st, 90) - np.nanpercentile(st, 10))
    em = v & (tt > dur - 0.55)
    slope = 0.0
    if em.sum() >= 5:
        x = tt[em] - tt[em][0]
        f = st[em]
        A = np.vstack([x, np.ones_like(x)]).T
        slope = float(np.linalg.lstsq(A, f, rcond=None)[0][0])
    # tail delta: last 0.25s of voiced pitch vs the 0.35s before it (st) —
    # catches the final-syllable uptick the window slope averages away
    vt = tt[v]
    vf = f0[v]
    end = float(vt[-1])
    tail = vf[vt > end - 0.25]
    prev = vf[(vt > end - 0.60) & (vt <= end - 0.25)]
    tail_delta = None
    if len(tail) >= 3 and len(prev) >= 3:
        tail_delta = round(float(12 * np.log2(np.median(tail) / np.median(prev))), 2)
    # final release curl: slope + rebound within the last 0.20s of voicing
    final_glide = final_rebound = None
    gm = vt > end - 0.20
    if gm.sum() >= 4:
        gt = vt[gm] - vt[gm][0]
        gf = 12 * np.log2(vf[gm] / med)
        A2 = np.vstack([gt, np.ones_like(gt)]).T
        final_glide = round(float(np.linalg.lstsq(A2, gf, rcond=None)[0][0]), 1)
        final_rebound = round(float(gf[-1] - np.min(gf)), 2)
    return {"dur": round(dur, 3), "median_hz": round(med, 1),
            "range_st": round(rng, 2), "end_slope": round(slope, 2),
            "first_hz": round(float(np.median(vhz[:5])), 1),
            "last_hz": round(float(np.median(vhz[-5:])), 1),
            "tail_delta": tail_delta,
            "final_glide": final_glide, "final_rebound": final_rebound,
            "trim": (int(idx[0]), int(idx[1]))}


def slope_profile(question=False, forced=False):
    """(gate_band, prior, bonus_band) for a phrase's end-slope class."""
    if question:
        return QUESTION_SLOPE_BAND, QUESTION_SLOPE_PRIOR, QUESTION_SLOPE_BAND
    if forced:
        return FORCED_SLOPE_BAND, FORCED_SLOPE_PRIOR, FORCED_SLOPE_BAND
    return END_SLOPE_HARD, END_SLOPE_PRIOR, (END_SLOPE_HARD[0], 0.0)


def gate_take(m, n_syl, numeric, question=False, forced=False, final=False):
    r = []
    if m is None:
        return False, ["unmeasurable"]
    band = RATE_BAND_QUESTION if question else (RATE_BAND_NUMERIC if numeric else RATE_BAND)
    rate = n_syl / m["dur"] if m["dur"] > 0 else 0
    if not (band[0] <= rate <= band[1]):
        r.append(f"rate {rate:.2f}")
    td = m.get("tail_delta")
    if question and final and td is not None:
        # questions: PRIMARY gate is the 직전-대비 tail band (both sides);
        # window slope band skipped (it averages away the final syllable)
        rel = td / m["range_st"] if m["range_st"] > 0 else 0.0
        if not (QUESTION_TAIL_BAND[0] <= td <= QUESTION_TAIL_BAND[1]):
            r.append(f"q_tail {td:+.1f}")
        if not (QUESTION_REL_BAND[0] <= rel <= QUESTION_REL_BAND[1]):
            r.append(f"q_rel {rel:+.2f}")
    else:
        slo, _, _ = slope_profile(question, forced)
        hi = min(slo[1], -2.0) if (final and not question) else slo[1]
        if not (slo[0] <= m["end_slope"] <= hi):
            r.append(f"end_slope {m['end_slope']}")
        if final and not question and td is not None:
            if td > TAIL_DELTA_MAX:
                r.append(f"tail {td:+.1f}")
            rel = td / m["range_st"] if m["range_st"] > 0 else 0.0
            if rel > TAIL_REL_MAX:
                r.append(f"rel_fall {rel:+.2f}")
    if final:
        g = m.get("final_glide")
        rb = m.get("final_rebound")
        if g is not None and g < FINAL_GLIDE_MIN:
            r.append(f"glide {g:+.1f}")
        if rb is not None and rb < FINAL_REBOUND_MIN:
            r.append(f"rebound {rb:+.1f}")
    if not (RANGE_SANITY[0] <= m["range_st"] <= RANGE_SANITY[1]):
        r.append(f"range {m['range_st']}")
    lvl = 12 * math.log2(m["median_hz"] / LEVEL_ANCHOR_HZ)
    if abs(lvl) > LEVEL_BAND_ST:
        r.append(f"level {lvl:+.1f}st")
    return len(r) == 0, r


def quality(m, n_syl, question=False, forced=False, final=False):
    rate = n_syl / m["dur"]
    q = -abs(rate - RATE_TGT) * 8.0
    _, prior, bonus = slope_profile(question, forced)
    q -= min(abs(m["end_slope"] - prior), 25.0) * 0.5
    if bonus[0] <= m["end_slope"] <= bonus[1]:
        q += 5.0
    # level dominates marginal rate misses: a +3.7st float is far more audible
    # than a 2%-slow take (B06 '케이블을 찾습니다' priority inversion, 2026-08-06)
    q -= abs(12 * math.log2(m["median_hz"] / LEVEL_ANCHOR_HZ)) * 6.0
    if final:
        # fallback ranking must prefer curl-closest takes (release-curl gate)
        rb = m.get("final_rebound")
        g = m.get("final_glide")
        if rb is not None and rb < FINAL_REBOUND_MIN:
            q -= (FINAL_REBOUND_MIN - rb) * 4.0
        if g is not None and g < FINAL_GLIDE_MIN:
            q -= (FINAL_GLIDE_MIN - g) * 0.3
    return q


def _take_by_id(rows, take_id):
    return next((row for row in rows if row.get("take") == take_id), None)


def apply_quality_selection(baseline_picks, proposals, takes, pins):
    """Apply an already-approved proposal behind the immutable Luna gates.

    The integration module owns artifact/calibration/approval checks.  This
    final production-side guard preserves pins and rejects the entire proposal
    if any selected take or block continuity constraint is invalid.
    """
    baseline = list(baseline_picks)
    if not proposals:
        return baseline, {"status": "not_requested", "reasons": []}

    candidate = list(baseline)
    reasons = []
    for phrase_index, take_id in sorted(proposals.items()):
        if not isinstance(phrase_index, int) or not 0 <= phrase_index < len(takes):
            reasons.append(f"invalid_phrase_index:{phrase_index}")
            continue
        if f"P{phrase_index:02d}" in pins:
            continue
        row = _take_by_id(takes[phrase_index], take_id)
        if row is None or not row.get("ok") or not row.get("metrics"):
            reasons.append(f"invalid_or_failed_take:P{phrase_index:02d}_t{take_id}")
            continue
        candidate[phrase_index] = take_id

    selected_rows = [_take_by_id(takes[i], take_id) for i, take_id in enumerate(candidate)]
    if any(row is None or not row.get("metrics") for row in selected_rows):
        reasons.append("selected_take_metrics_missing")
    if reasons:
        return baseline, {"status": "fallback", "reasons": reasons}

    slopes = sorted(row["metrics"]["end_slope"] for row in selected_rows)
    n_slopes = len(slopes)
    median = slopes[n_slopes // 2] if n_slopes % 2 else (
        slopes[n_slopes // 2 - 1] + slopes[n_slopes // 2]) / 2
    if not (BLOCK_MEDIAN_BAND[0] <= median <= BLOCK_MEDIAN_BAND[1]):
        reasons.append(f"block_median_outside_gate:{median:.2f}")

    for index in range(1, len(selected_rows)):
        before = selected_rows[index - 1]["metrics"]
        after = selected_rows[index]["metrics"]
        reset = 12 * math.log2(after["first_hz"] / before["last_hz"])
        if not (RESET_GATE[0] <= reset <= RESET_GATE[1]):
            reasons.append(f"reset_outside_gate:P{index:02d}:{reset:.2f}")
    if reasons:
        return baseline, {"status": "fallback", "reasons": reasons}
    if candidate == baseline:
        return baseline, {"status": "unchanged", "reasons": []}
    return candidate, {"status": "applied", "reasons": []}


def synthesize_block(model, sr, block, outdir, np, torch, ta, quality_session=None):
    bid = block["id"]
    text = respell(block["text"])
    seed0 = int(block["seed"])
    bdir = outdir / bid
    bdir.mkdir(parents=True, exist_ok=True)
    phrases = build_phrase_list(text)
    (bdir / "phrases.json").write_text(
        json.dumps(phrases, ensure_ascii=False, indent=2), encoding="utf-8")

    takes = []
    for i, p in enumerate(phrases):
        n_syl = syl(p["text"])
        numeric = numeral_heavy(p["text"])
        question = is_question(p["text"])
        forced = p.get("forced", False)
        final = p.get("sentence_final", False)
        n_pool = N_TAKES_QUESTION if question else (N_TAKES_FORCED if forced else N_TAKES)
        rows = []
        k = 0
        pool = n_pool
        esc_round = 0
        while k < pool:
            wp = bdir / f"P{i:02d}_t{k}.wav"
            mp = bdir / f"P{i:02d}_t{k}.json"
            if wp.exists() and mp.exists():
                row = json.loads(mp.read_text(encoding="utf-8"))
                # stale-cache guard: if the phrase TEXT changed (splitter or
                # respell update), the cached take is audio of the OLD text —
                # discard and regenerate instead of reusing by index
                if row.get("text") is not None and row["text"] != p["text"]:
                    wp.unlink()
                    mp.unlink()
                    continue
                # upgrade cached metrics that predate tail_delta (re-measure
                # from the cached wav once, then persist)
                if row["metrics"] is not None and (
                        "tail_delta" not in row["metrics"]
                        or "final_glide" not in row["metrics"]):
                    w2, wsr2 = ta.load(str(wp))
                    m2 = measure_take(w2.mean(dim=0).numpy(), wsr2)
                    if m2 is not None:
                        m2.pop("trim", None)
                        row["metrics"].update(m2)
                        mp.write_text(json.dumps(row, ensure_ascii=False),
                                      encoding="utf-8")
                # re-gate cached takes under CURRENT rules so rule changes
                # apply retroactively without regeneration
                row["ok"], row["why"] = gate_take(
                    row["metrics"], row["n_syl"], row.get("numeric", numeric),
                    question, forced, final)
                rows.append(row)
                k += 1
                if k == pool and esc_round < len(ESCALATION_TEMPS) \
                        and not any(r["ok"] for r in rows if r["metrics"]):
                    esc_round += 1
                    pool += ESCALATION_TAKES
                    print(f"[{bid}] P{i:02d} ESCALATE r{esc_round} "
                          f"temp={ESCALATION_TEMPS[esc_round-1]} "
                          f"(0 passing in {k} takes)", flush=True)
                continue
            temp_k = ESCALATION_TEMPS[esc_round - 1] if esc_round else TEMP
            sd = (seed0 + i * 104729 + k * 7919) % 2**31
            random.seed(sd)
            np.random.seed(sd % (2**32 - 1))
            torch.manual_seed(sd)
            tg = time.time()
            audio_prompt_path = (
                quality_session.audio_prompt_path(REF) if quality_session is not None
                else str(REF)
            )
            wav = model.generate(p["text"], language_id="ko",
                                 audio_prompt_path=audio_prompt_path,
                                 exaggeration=EXAG, cfg_weight=CFG,
                                 temperature=temp_k, repetition_penalty=1.2,
                                 min_p=0.05, top_p=1.0)
            arr = wav.cpu().numpy().flatten()
            m = measure_take(arr, sr)
            ok, why = gate_take(m, n_syl, numeric, question, forced, final)
            if m is not None:
                a, b = m.pop("trim")
                pad = int(0.03 * sr)
                a = max(0, a - pad)
                b = min(len(arr), b + pad)
                seg = torch.tensor(arr[a:b], dtype=wav.dtype).unsqueeze(0)
                ta.save(str(wp), seg, sr, encoding="PCM_S", bits_per_sample=16)
            row = {"take": k, "seed": sd, "ok": ok, "why": why,
                   "metrics": m, "n_syl": n_syl, "numeric": numeric,
                   "text": p["text"], "temp": temp_k,
                   "gen_s": round(time.time() - tg, 1)}
            mp.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
            rows.append(row)
            print(f"[{bid}] P{i:02d} t{k} {'OK ' if ok else 'REJ'} {why} gen={row['gen_s']}s",
                  flush=True)
            k += 1
            passing = [r for r in rows if r["ok"] and r["metrics"]]
            if (len(rows) >= EARLY_STOP_MIN_TAKES
                    and len(passing) >= EARLY_STOP_MIN_PASSING
                    and max(quality(r["metrics"], r["n_syl"], question, forced, final) for r in passing) >= EARLY_STOP_QUALITY):
                break
            if k == pool and esc_round < len(ESCALATION_TEMPS) and not passing:
                esc_round += 1
                pool += ESCALATION_TAKES
                print(f"[{bid}] P{i:02d} ESCALATE r{esc_round} "
                      f"temp={ESCALATION_TEMPS[esc_round-1]} "
                      f"(0 passing in {k} takes)", flush=True)
        takes.append(rows)

    quality_proposals = (
        quality_session.evaluate_block(bid) if quality_session is not None else {}
    )

    # ---- beam assembly ----
    q_flags = [(is_question(p["text"]), p.get("forced", False),
                p.get("sentence_final", False)) for p in phrases]
    # CEO taste pins: OUTDIR/<bid>_pins.json {"P02": 5} forces that take
    pins_path = outdir / f"{bid}_pins.json"
    pins = json.loads(pins_path.read_text(encoding="utf-8")) if pins_path.exists() else {}

    def cands(i):
        pin = pins.get(f"P{i:02d}")
        if pin is not None:
            pinned = [r for r in takes[i] if r["take"] == pin and r["metrics"]]
            if pinned:
                return pinned
        ok = [r for r in takes[i] if r["ok"] and r["metrics"]]
        if not ok:
            ok = [r for r in takes[i] if r["metrics"]]
        return sorted(ok, key=lambda r: -quality(r["metrics"], r["n_syl"], *q_flags[i]))[:4]

    beams = [{"picks": [], "score": 0.0, "last_hz": None}]
    for i in range(len(phrases)):
        nxt = []
        for b in beams:
            for c in cands(i):
                m = c["metrics"]
                s = b["score"] + quality(m, c["n_syl"], *q_flags[i])
                if b["last_hz"]:
                    reset = 12 * math.log2(m["first_hz"] / b["last_hz"])
                    if not (RESET_GATE[0] <= reset <= RESET_GATE[1]):
                        s -= 30.0
                    s -= abs(reset - RESET_TGT) * 1.2
                nxt.append({"picks": b["picks"] + [c["take"]], "score": s,
                            "last_hz": m["last_hz"]})
        beams = sorted(nxt, key=lambda x: -x["score"])[:3]
    picks = beams[0]["picks"]

    def block_med(pk):
        sl = sorted(takes[i][p]["metrics"]["end_slope"] for i, p in enumerate(pk))
        n = len(sl)
        return sl[n // 2] if n % 2 else (sl[n // 2 - 1] + sl[n // 2]) / 2

    bm = block_med(picks)
    if not (BLOCK_MEDIAN_BAND[0] <= bm <= BLOCK_MEDIAN_BAND[1]):
        mid = sum(BLOCK_MEDIAN_BAND) / 2
        for i in range(len(picks)):
            if q_flags[i][0] or q_flags[i][1]:
                continue  # never let block repair distort question/forced contours
            for a in sorted((r for r in takes[i] if r["ok"] and r["metrics"]),
                            key=lambda r: r["metrics"]["end_slope"]):
                trial = picks[:i] + [a["take"]] + picks[i + 1:]
                if abs(block_med(trial) - mid) < abs(bm - mid):
                    picks, bm = trial, block_med(trial)
                    break
            if BLOCK_MEDIAN_BAND[0] <= bm <= BLOCK_MEDIAN_BAND[1]:
                break

    baseline_picks = list(picks)
    picks, quality_guard = apply_quality_selection(
        baseline_picks, quality_proposals, takes, pins)
    if quality_session is not None:
        quality_session.finalize_block(
            bid,
            baseline_picks=baseline_picks,
            final_picks=picks,
            guard=quality_guard,
        )
    bm = block_med(picks)

    # ---- concatenate ----
    rng = random.Random(seed0)
    segs = []
    total = 0.0
    timeline = []
    for i, p in enumerate(phrases):
        w, wsr = ta.load(str(bdir / f"P{i:02d}_t{picks[i]}.wav"))
        w = w.mean(dim=0, keepdim=True)
        nf = int(0.012 * wsr)
        env = torch.ones(w.shape[1])
        env[:nf] = torch.linspace(0, 1, nf)
        env[-nf:] = torch.linspace(1, 0, nf)
        w = w * env
        rms = float(torch.sqrt(torch.mean(w ** 2)))
        w = w * (10 ** (-20 / 20) / max(rms, 1e-9))
        timeline.append({"phrase": i, "text": p["text"], "start": round(total, 3),
                         "dur": round(w.shape[1] / wsr, 3), "take": picks[i],
                         "sentence_final": p["sentence_final"]})
        segs.append(w)
        total += w.shape[1] / wsr
        if i < len(phrases) - 1:
            if p["sentence_final"]:
                lo, hi = PAUSE_FINAL
            elif p.get("forced", False):
                lo, hi = PAUSE_FORCED
            else:
                lo, hi = PAUSE_CONT
            ps = rng.uniform(lo, hi)
            segs.append(torch.zeros(1, int(ps * wsr)))
            total += ps
    out = torch.cat(segs, dim=1)
    peak = float(out.abs().max())
    if peak > 0.89:
        out = out * (0.89 / peak)
    final = outdir / f"{bid}_luna.wav"
    ta.save(str(final), out, sr, encoding="PCM_S", bits_per_sample=16)

    report = {"id": bid, "picks": picks, "block_end_slope_median": round(bm, 2),
              "total_dur": round(total, 2), "n_phrases": len(phrases),
              "timeline": timeline}
    (outdir / f"{bid}_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{bid}] DONE dur={total:.2f}s slope_med={bm:.2f}", flush=True)
    return report


def main():
    jobs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    outdir = Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)

    cache = RUNTIME / "hf-cache"
    os.environ.update({
        "HF_HOME": str(cache), "HF_HUB_CACHE": str(cache / "hub"),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false",
        "PYTHONUTF8": "1"})
    import numpy as np
    import torch
    import torchaudio as ta
    sys.path.insert(0, str(RUNTIME / "chatterbox" / "src"))
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    t0 = time.time()
    model = ChatterboxMultilingualTTS.from_pretrained(device="cpu", t3_model="v3")
    sr = model.sr
    print(f"[load] {time.time()-t0:.1f}s", flush=True)

    quality_session = None
    if quality_integration_requested():
        try:
            from luna_quality.production_integration import (
                ProductionQualitySession,
                write_startup_fallback_report,
            )
            try:
                quality_session = ProductionQualitySession.from_environment(
                    ROOT, outdir, model)
            except Exception as exc:
                write_startup_fallback_report(ROOT, outdir, exc)
                print("[quality] integration unavailable; existing selector retained",
                      flush=True)
        except Exception as exc:
            # Optional integration imports can never stop the production pipeline.
            write_quality_import_fallback(outdir, exc)
            print(f"[quality] integration import unavailable ({type(exc).__name__}); "
                  "existing selector retained", flush=True)

    reports = []
    for block in jobs["blocks"]:
        rp = outdir / f"{block['id']}_report.json"
        if rp.exists():
            print(f"[{block['id']}] already done, skip", flush=True)
            reports.append(json.loads(rp.read_text(encoding="utf-8")))
            continue
        reports.append(synthesize_block(
            model, sr, block, outdir, np, torch, ta, quality_session))
    (outdir / "pipeline_report.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[pipeline done] {len(reports)} blocks", flush=True)


if __name__ == "__main__":
    main()
