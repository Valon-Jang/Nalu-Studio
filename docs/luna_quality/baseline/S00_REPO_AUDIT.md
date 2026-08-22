# S00 저장소 감사 및 baseline 동결

- 감사 시각: 2026-08-23T08:30:31.5007649+09:00
- 감사 대상 Git HEAD: `417774ab6b7177f723b8bd75f5fb56fd25b5a0b0`
- 단계 시작 기준 commit: `d5d2a3c669af223cbe798f48a90efa34cc88b67d`
- 감사 방식: 저장소 코드·로컬 모델 cache·기존 산출물의 읽기 전용 검사 및 모델 load smoke test
- 결론: 후속 단계가 사용할 baseline을 기록했다. production 코드, dependency, audio, cache, 규칙 파일은 변경하지 않았고 audio를 생성하지 않았다.

## 1. 실행 진입점과 런타임

현재 production 진입점은 `scripts/luna_narration_pipeline_v1.py` 하나다. SHA-256은 `1454b6ba97653a98f32253050e85f2a0a19ed0621c78bdcfc8187db6a8c446d5`이다.

실행 시 `engine/chatterbox-v3/hf-cache`를 Hugging Face cache로 지정하고 offline 환경 변수를 켠 뒤, CPU에서 다음 호출로 모델을 적재한다.

```python
ChatterboxMultilingualTTS.from_pretrained(device="cpu", t3_model="v3")
```

실제 source repository는 `engine/chatterbox-v3/chatterbox`이며 감사 시 commit은 `5de7a54aa4e5e2baadb0182dde554908b48b85c2`이고 worktree는 clean이었다. `v3` alias는 `t3_mtl23ls_v3.safetensors`로 해석된다. 로컬 snapshot revision은 `5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18`이다.

모델 load smoke test는 audio 생성 없이 통과했다. 확인된 device는 CPU, sample rate는 24,000 Hz였고 T3, S3Gen, VoiceEncoder가 모두 적재되었다. 모델 적재 구간은 약 25.5초였다. `pkg_resources`와 diffusers `LoRACompatibleLinear` deprecation warning이 있었지만 load 실패는 없었다.

### 실제 checkpoint

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `t3_mtl23ls_v3.safetensors` | 2,143,989,928 | `5abca8321ede76f8e61f1cc0d19aea6c946b28871017ce8726f8a69203f05953` |
| `s3gen.pt` | 1,057,165,844 | `9b9ff07e60b20c136e2b1b3d7563a24604e8d2c4c267888d1ee929dd0151d2a3` |
| `ve.pt` | 5,698,626 | `4b16d836bc598509860f6fa068165a8bb5e9ac84f05582dfcf278a5a372879f1` |
| `Cangjie5_TC.json` | 1,920,163 | `7073fd9de919443ae88e0bd2449917a65fe54898a4413ed1edcc4b67f28bce8c` |
| `conds.pt` | 107,374 | `6552d70568833628ba019c6b03459e77fe71ca197d5c560cef9411bee9d87f4e` |
| `grapheme_mtl_merged_expanded_v1.json` | 69,989 | `69632f47220a788a52ce2661d096453c5655e9bf25289d89a8d832c46ee07dbf` |

## 2. Luna voice 기준과 source of truth

Candidate B는 `assets/voice_ref/B_voiced_spectral_micro_smooth.wav`이며 실제 SHA-256과 기대 SHA-256이 모두 `30c6d3405f46684af467c7d26ff40a2fb57dd48cc84cd24cf7403d9aa00a2bb9`로 일치한다. 파일은 mono PCM16, 32,000 Hz, 468,800 frames, 14.65초다.

Codex가 사용하는 Luna 규칙의 source of truth는 `.agents/skills/luna-narration/SKILL.md`이며 SHA-256은 `8ec5472cbdc2336814c27b020429483842e4782de433bf257fa7445afababe39`이다. `.claude/skills/luna-narration/SKILL.md`에도 SHA-256 `9e32ef089e24a36c8a75c3b6adce709dfd755206495c5b159ff8ff040609e082`인 별도 사본이 있어 동기화 drift 위험이 있다.

`assets/voice_ref/LUNA_PROSODY_TARGET.json`은 schema version 1.0의 역사적 측정·설계 근거이며 SHA-256은 `267e79ec088933c9c43b6584e90bd04b2b4e77eaba3134a669d151c464458bae`이다. production 파이프라인이 이 JSON을 runtime에 읽지는 않는다. 현재 실행값의 source of truth는 production 진입점의 상수와 현재 `.agents` skill이다. 따라서 target JSON의 옛 rate/gap 범위와 현재 상수가 충돌하면 현재 production 상수를 baseline으로 취급한다.

Candidate B의 hash는 stage gate가 단계 시작 전에 보호하지만 production 진입점 자체는 합성 직전에 hash를 검증하지 않는다.

## 3. 고정 generation·검증 파라미터

| 분류 | 현재 값 |
|---|---|
| take | 기본 6, 질문 및 forced 10 |
| early stop | 최소 3 takes, passing 2개, quality -3 이상 |
| generation | exaggeration 0.5, cfg_weight 0.5, temperature 0.72, repetition_penalty 1.2, min_p 0.05, top_p 1.0, language `ko` |
| escalation | 6회, temperatures 0.85/0.87/0.87 |
| 발화 속도 | target 6.54 syllables/s; normal 5.6–7.2, numeric 4.4–7.2, question 5.2–7.2 |
| range/level | range 4–15 st, level anchor 235 Hz ±2 st |
| statement | end slope -35–8, final non-question upper -2, tail ≤ -1.5 st, relative tail ≤ -0.28 |
| block median | -20–-5 st/s |
| reset | -4–13 st, target 4.65 st |
| question | tail -4–-1.5 st, relative -0.40–-0.25, fallback slope -10–-5, prior -6.5 |
| final glide | glide ≥4 st, rebound ≥2.5 st |
| forced | slope -8–4, prior -2 |
| pauses | continuation 0–0.02s, final 0.38–0.60s, forced 0.05–0.10s |
| output | trim pad 30ms, fade 12ms, RMS -20 dBFS, peak guard 0.89 |

## 4. 처리 흐름

1. `JOBS.json`의 `blocks[]`에서 `id`, `text`, `seed`를 읽는다.
2. 문장부호·forced delimiter 규칙으로 block을 phrase로 분할하고 `phrases.json`을 기록한다.
3. phrase마다 deterministic seed `seed0 + phrase_index*104729 + take*7919 (mod 2^31)`로 take를 합성한다.
4. 각 `P##_tK.wav`를 측정하고 `P##_tK.json`에 지표·gate 결과를 기록한다.
5. 현재 규칙으로 cached row도 다시 gate한다. 통과 후보에 quality 점수를 부여한다.
6. pins가 있으면 지정 take를 우선하고, 없으면 beam assembly로 phrase 조합을 선택한다. 통과 후보가 없으면 측정 가능한 후보까지 fallback한다.
7. pause, trim, fade, loudness/peak 처리를 거쳐 `<block>_luna.wav`를 만들고 block report와 `pipeline_report.json`을 기록한다.

Chatterbox `Conditionals.save/load` 기능은 존재하지만 현재 pipeline은 이를 사용하지 않는다. 모든 generation call에 `audio_prompt_path`를 넘기므로 `prepare_conditionals`가 take마다 다시 계산된다.

## 5. 출력 계약

입력 최소 계약은 다음과 같다.

```json
{"blocks":[{"id":"B01","text":"...","seed":1234}]}
```

출력 경로는 다음과 같다.

- `<OUTDIR>/<id>/phrases.json`
- `<OUTDIR>/<id>/P##_tK.wav`
- `<OUTDIR>/<id>/P##_tK.json`
- `<OUTDIR>/<id>_luna.wav`
- `<OUTDIR>/<id>_report.json`
- `<OUTDIR>/pipeline_report.json`
- 선택적 `<OUTDIR>/<id>_pins.json` (`{"P02": 5}` 형식)

최종 WAV 계약은 mono PCM16, 24,000 Hz다. 감사한 1,052개 project WAV가 모두 이 형식이었고 손상된 header는 없었다.

기존 산출물은 SPIDER-001과 SUBSEA-001 두 project에 있다. 총 1,071개 JSON은 모두 parse되었다. take JSON/WAV pair는 각각 1,035개로 누락 pair가 없었다. gate 결과는 pass 233, reject 802, unmeasurable 0이었다. phrase 17개, block report 17개, pipeline report 2개, final `_luna.wav` 17개이며 pins 파일은 없다.

기존 take 중 439개는 `text`가 없고 그중 153개는 `temperature`도 없다. 229개 metrics row는 최신 tail/glide/rebound 항목이 없다. historical temperature 0.9인 take 120개도 있다. 이는 동결된 과거 산출물의 schema evolution 증거이며 재생성 대상이 아니다.

SPIDER B06의 기존 block median은 -2.2, SUBSEA B01은 -3.13으로 현재 band 밖이다. 이 또한 확정 audio와 함께 동결된 역사적 결과로 취급한다.

## 6. cache 재사용과 invalidation

- `<id>_report.json`이 있으면 block 전체를 skip한다. 입력 text/hash 또는 final WAV 존재 여부를 확인하지 않는다.
- take cache는 WAV와 JSON이 모두 있을 때만 재사용한다.
- cached JSON에 `text`가 있고 현재 phrase와 다르면 pair를 지우고 재생성한다.
- `text`가 없는 구형 row는 stale-text 여부를 판별할 수 없다.
- 구형 metrics에 tail/glide가 없으면 재측정해 JSON을 갱신한다.
- cached row도 매 실행 현재 gate 규칙을 적용한다.
- model/checkpoint, Candidate B, entry point, generation parameters의 hash는 take/report에 기록되지 않는다.
- pins는 metrics가 있으면 현재 gate가 reject여도 선택된다. 이는 명시적 human override 계약이다.

## 7. dependency와 테스트 상태

| 항목 | 버전/상태 |
|---|---|
| Python | 3.12.10 |
| torch | 2.6.0+cpu |
| torchaudio | 2.6.0+cpu |
| librosa | 0.11.0 |
| numpy | 1.26.4 |
| safetensors | 0.5.3 |
| huggingface_hub | 1.26.0 |
| chatterbox-tts | 0.1.7 |
| resemble-perth | 1.0.1 |

root에는 `tests/`, fixture, `pyproject.toml`, requirements, pytest/tox 설정이 없다. 따라서 S00 검증은 JSON parse, stage scope, Python compile, dependency/model load smoke test, 기존 산출물 schema·WAV header 검사로 구성했다.

Windows 기본 CP949 console에서 `python tools/stage_gate.py status`는 em dash 출력 중 `UnicodeEncodeError`가 발생했다. `python -X utf8 tools/stage_gate.py status`는 통과하므로 Windows에서는 `-X utf8` 또는 `PYTHONUTF8=1`이 필요하다.

## 8. 동결 자산과 보호 수준

동결 대상은 production 진입점, Luna skill, Candidate B와 prosody target, `engine/chatterbox-v3/**`, SPIDER-001/SUBSEA-001의 `audio/luna_phrase_v3/**` 확정 audio와 SUBSEA project 루트의 `NARRATION_TIMING_v3_0p1s.csv/.md`다.

주의할 점은 `.gitignore`가 runtime/cache, Candidate WAV, 모든 project WAV/log/html을 제외한다는 것이다. stage gate의 Git changed-path scope만으로는 ignored runtime과 확정 WAV 변경을 감지할 수 없다. Candidate B는 별도의 protected hash로 보호되지만 최종 WAV 17개는 stage gate hash 보호 대상이 아니다. 이 감사에서 기록한 final WAV hash가 후속 무결성 검사의 baseline이다.

## 9. 최소 침습 통합 경계

후속 단계의 통합 위치는 두 곳 이하로 제한한다.

1. S01–S09: production과 독립된 `scripts/luna_quality/` package/CLI에서 기존 JSON/WAV를 읽고 shadow 결과만 만든다.
2. S10: 필요한 경우에만 `synthesize_block`의 take 재측정 완료 후, 기존 `cands`/beam selection 직전에 default-off feature flag hook 하나를 둔다. 기존 output 계약과 fallback은 보존한다.

## 10. 미해결 항목

- `LUNA_PROSODY_TARGET.json`의 `measurement_file`이 가리키는 옛 `readiness/.../prosody_full_corpus_v2.json`은 현재 저장소에 없다.
- `CLAUDE.md`에 명시된 brand outro/video assets는 이 저장소에 의도적으로 없다.
- 재현 가능한 root dependency lock/requirements와 자동 test suite/fixture가 없다.
- 실제 project별 원본 `JOBS.json`과 `_pins.json`이 보존되어 있지 않다.
- `.agents`와 `.claude` Luna skill 사본이 동일하지 않아 source-of-truth 혼동 가능성이 있다.
- block-level cache가 text/hash/final WAV 존재를 검증하지 않으며, 구형 take row는 stale text를 판별할 수 없다.
- production이 Candidate B hash 및 model/code provenance를 runtime/output에 기록하지 않는다.
- ignored runtime 및 확정 WAV에 대한 stage gate 무결성 보호가 불완전하다.
- snapshot 내부에 중첩된 `models--ResembleAI--chatterbox/...` 중복 tree가 있으나 현재 loader는 top-level snapshot 파일을 사용하므로 관찰된 실행 영향은 없다.

이 항목들은 사실 또는 관찰된 위험이며 S00에서는 고치지 않았다.

## 11. 검증 명령

```powershell
python -m json.tool docs/luna_quality/baseline/BASELINE_MANIFEST.json
python -X utf8 -c "compile(open('scripts/luna_narration_pipeline_v1.py', encoding='utf-8').read(), 'scripts/luna_narration_pipeline_v1.py', 'exec'); print('PASS')"
python -X utf8 tools/stage_gate.py verify
python -X utf8 tools/stage_gate.py check-scope
git status --short
```
