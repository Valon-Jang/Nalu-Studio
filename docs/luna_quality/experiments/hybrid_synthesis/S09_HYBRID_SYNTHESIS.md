# S09 Hybrid Synthesis 격리 실험

이 도구는 `existing_phrase`, `sentence`, `hybrid` 세 모드를 같은 대본·Candidate B·고정 생성 파라미터·완성 대본 후보 수·seed 파생 규칙으로 비교한다. 결과는 증거 자료일 뿐이며 production 선택이나 promotion에는 사용할 수 없다.

## 안전 경계

- 출력은 반드시 `experiments/luna_quality/<새 실험 ID>/` 아래의 새 디렉터리여야 한다.
- 동결 프로젝트 표시는 반드시 `false`여야 하며, `SPIDER-001`과 `SUBSEA-001`은 ID로도 거부한다.
- Candidate B의 경로와 SHA-256을 실제 파일에서 다시 확인한다.
- `scripts/luna_narration_pipeline_v1.py`, 기존 cache, `*_luna.wav`, `pins.json`은 읽거나 덮어쓸 대상으로 계획하지 않는다.
- 실제 Chatterbox 모델은 기본 dry-run에서 import하거나 load하지 않는다.
- 실제 생성은 `--execute-generation`과 `--acknowledge-isolated-experiment`를 함께 준 경우에만 가능하다.
- 자동 promotion은 스키마와 보고서에서 항상 금지 상태다.

현재 저장소 런타임에서 확인한 한도는 다음과 같다.

| 항목 | 값 | 적용 |
|---|---:|---|
| T3 최대 text token | 2,048 | 시작·종료 token 2개 포함 |
| 실제 generate speech token cap | 1,000 | `mtl_tts.py`의 실제 호출값 |
| S3 token rate | 25/s | 마지막 token 제거 후 최대 약 39.96초 |
| S09 보수적 예상 오디오 한도 | 32초 | 초과 문장을 억지로 생성하지 않음 |

dry-run은 UTF-8 byte 수에 framing token 2개를 더한 보수적 상한을 사용한다. 실제 integration 실행 직전에는 pinned Chatterbox tokenizer로 다시 세고 2,048을 넘으면 해당 음성을 생성하지 않는다. 한도 값과 근거 파일 SHA-256은 `segmentation_plan.json`에 남는다.

## 입력 계약

```json
{
  "schema_version": "luna-hybrid-input/1",
  "experiment_id": "s09-example",
  "frozen_project": false,
  "source_project_id": "OPTIONAL-UNFROZEN-ID",
  "scripts": [
    {
      "script_id": "script-01",
      "text": "첫 문장입니다. 두 번째 문장입니다.",
      "seed": 407,
      "existing_phrases": [
        {"text": "첫 문장입니다.", "sentence_final": true},
        {"text": "두 번째 문장입니다.", "sentence_final": true}
      ]
    }
  ]
}
```

`existing_phrases`를 합친 텍스트는 공백을 제외하고 `text`와 정확히 같아야 한다. candidate budget의 단위는 조각 수가 아니라 **모드별 완성 대본 후보 수**다. 각 완성 후보는 해당 모드의 모든 segment job을 포함한다.

## 모드와 조립

- `existing_phrase`: 입력의 현재 phrase 분할을 그대로 쓴다.
- `sentence`: 문장 전체를 생성한다. 사후 ASR와 forced alignment로 기존 phrase 경계를 추출하도록 계획과 validator 상태를 기록한다.
- `hybrid`: 80 audible character 이하의 안전한 문장은 통째로 쓰고, 긴 문장은 구두점·연결어미의 의미절로 나눈다. 안전한 의미절 분리가 불가능하면 existing phrase로 fallback한다.

여러 segment를 완성 후보로 조립할 때에는 현재 production의 12ms fade, -20 dBFS RMS, 0.89 peak guard, continuation/forced/final pause 범위를 격리 모듈에서 그대로 미러링한다. 근거 production 파일의 hash도 plan에 기록한다. production 코드는 import하거나 수정하지 않는다.

## PowerShell 명령

계획 생성:

```powershell
python -X utf8 -m scripts.luna_quality.cli hybrid-plan `
  --input experiments\luna_quality\s09_fixture_input.json `
  --output-root experiments\luna_quality\s09_my_run `
  --candidate-budget 4
```

모델을 load하지 않는 기본 dry-run:

```powershell
python -X utf8 -m scripts.luna_quality.cli hybrid-run `
  --plan experiments\luna_quality\s09_my_run\segmentation_plan.json
```

실제 음성 생성은 사용자가 명시적으로 integration 실행을 선택한 경우에만 다음 두 opt-in을 함께 쓴다.

```powershell
engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m scripts.luna_quality.cli hybrid-run `
  --plan experiments\luna_quality\s09_my_run\segmentation_plan.json `
  --execute-generation `
  --acknowledge-isolated-experiment
```

평가 자료 생성:

```powershell
python -X utf8 -m scripts.luna_quality.cli hybrid-evaluate `
  --results experiments\luna_quality\s09_my_run\generation_results.json `
  --output-root experiments\luna_quality\s09_my_run_analysis
```

## 산출물

- `segmentation_plan.json`: 세 모드 분할, 공정성, 안전 한도, source hash
- `jobs/<mode>.jobs.json`: 완성 후보와 segment generation job
- `dry_run_report.json`: 모든 job·후보 경로와 충돌 여부, 모델 미사용 확인
- `generation_results.json`: opt-in 실행의 완성 후보 및 segment 결과
- `validator_results/<mode>.json`: 모드별 구조화된 `pass/fail/unknown/not_run`
- `analysis.json`, `analysis.csv`: content, silence/repetition, speaker, prosody, transition, duration, failure rate
- `timing.json`: 모드별 generation, assembly, 전체 처리 시간
- `blind_listening_manifest.json`: 모드와 원본 candidate ID를 감춘 청취용 ID
- `blind_answer_key.json`: 청취자에게 분리 보관할 mode 매핑
- `EVIDENCE_REPORT.md`: promotion 추천이 아닌 비교 증거 보고서

사후 model validator를 실행하지 않은 항목은 성공으로 간주하지 않고 `not_run`으로 남긴다. hallucination, repetition, speaker drift 또는 hard-gate 실패는 해당 모드의 failure rate에 포함한다.
