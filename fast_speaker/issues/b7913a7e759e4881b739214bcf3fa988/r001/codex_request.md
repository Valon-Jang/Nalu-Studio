# Luna FAST Speaker issue request

Issue: b7913a7e759e4881b739214bcf3fa988 revision 1
Status: OPEN
Category: OTHER
Source mode/session: manual / luna_fast_20260826_064626
Exact source sentence: I have a lot of works today.
Selected phrase: I have a lot of works today.
Phrase ID/class: P00 / sentence_final
Recent phrase context: ['나원참.', '오늘은 이이무라가 마무리를 맡습니다.', 'I have a lot of works today.']
Seed: 20260826
Listening note: 
Engine/config snapshot: Chatterbox Multilingual V3; Candidate B SHA-256 30C6D3405F46684AF467C7D26FF40A2FB57DD48CC84CD24CF7403D9AA00A2BB9; language_id=ko; exaggeration=0.5; cfg=0.5; temperature=0.72; repetition_penalty=1.2; min_p=0.05; top_p=1.0.
Code/rule revision: 8d3e1fe6782468d47b25670664601fe8db5d944d / built-in-noop
Timing metrics: {'schema_version': 'luna-fast-speaker-metrics/1', 'worker_ready_seconds': 20.98182490002364, 'synthesis_started_monotonic': 1131458.2079832, 'synthesis_finished_monotonic': 1131476.2763267, 'pcm_ready_monotonic': 1131476.2763314, 'audio_duration_seconds': 1.92, 'generation_seconds': 18.049832500051707, 'rtf': 9.400954427110264, 'playback_ttfa': 'not_run', 'warm_ttfa_seconds': 18.071587200043723}
Issue WAV: C:\Users\tequi\Gongdaeluna-Studio\fast_speaker\issues\b7913a7e759e4881b739214bcf3fa988\r001\original_phrase.wav

Reproduction: Launch scripts/luna_fast_speaker.py, use seed 20260826, submit the exact source sentence, and retest the selected phrase.

Requested fix scope: change only the approved FAST-test rule/module needed for this defect. Distinguish a deterministic lexical defect, a context-sensitive split/phonetic defect, and one-off synthesis instability. Do not add a global respell without repeated evidence.

Required regression: reproduce with the recorded text and seed; add a focused deterministic test for any lexical/split correction; run FAST Speaker unit/regression checks and a real Luna retest. Report changed files and exact test results.

Invariants: use only Chatterbox Multilingual V3 + Candidate B. Do not change the reference, fixed parameters, production pipeline, frozen audio/cache, pins, or normal FAST behavior. Do not auto-promote experimental overlay rules to production.

Complete only this issue fix, write the changed-files and verification report, then stop for user review.
