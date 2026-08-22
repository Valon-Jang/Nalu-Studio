# 기술 검증 메모

## 확인된 사항

- 현재 공대루나 스튜디오의 runtime, Candidate B, prosody target은 각각 `engine/chatterbox-v3`, `assets/voice_ref/B_voiced_spectral_micro_smooth.wav`, `assets/voice_ref/LUNA_PROSODY_TARGET.json`에 있다. 실행팩은 이 저장소 상대경로를 기준으로 한다.
- 내장 venv의 Python 3.12.10에서 Chatterbox import를 확인했다. import 중 `perth`가 deprecated `pkg_resources` API를 쓴다는 경고가 나오지만 import 결과는 정상이다. 향후 setuptools 호환성 정리 대상으로 추적한다.
- 공식 Chatterbox Multilingual V3는 한국어를 지원하고 Candidate B 같은 reference audio에서 conditionals를 준비한다.
- 공식 구현의 `Conditionals`는 T3·S3Gen 조건값을 저장하고 불러올 수 있다.
- T3 생성은 temperature, CFG, repetition penalty, min-p, top-p를 사용하는 확률적 token generation이므로 conditionals cache만으로 prosody 전체가 고정되지는 않는다.
- WhisperX는 word-level timestamp와 forced alignment를 제공하며 한국어 default alignment model 항목이 있다.
- SpeechBrain은 speaker verification에서 두 음성 embedding의 cosine similarity를 계산한다.
- SpeechMOS는 UTMOS 계열 MOS predictor를 제공한다.
- 공개 `gokhaneraslan/chatterbox-finetuning` 코드는 확인된 시점에 일반 Chatterbox/Turbo를 선택하며 Luna의 Multilingual V3 production checkpoint와 직접 호환된다고 입증되지 않았다.
- Chatterbox 커뮤니티 이슈에는 long-context가 공식 해결 기능으로 확정되지 않았고, 단순 장문 확장은 hallucination과 음질 저하 위험이 보고되어 있다.

## 구현 시 해석 금지

- WhisperX 결과가 좋다고 억양이 자연스럽다고 보지 않는다.
- SpeechMOS 점수가 높다고 Luna답다고 보지 않는다.
- SpeechBrain 기본 threshold를 Luna threshold로 보지 않는다.
- 공개 fine-tuning 프로젝트가 존재한다고 V3 fine-tuning이 검증됐다고 보지 않는다.
- 문장 전체 합성이 항상 구절 합성보다 좋다고 가정하지 않는다.

## 주요 upstream repository

- `resemble-ai/chatterbox`
- `m-bain/whisperX`
- `speechbrain/speechbrain`
- `tarepan/SpeechMOS`
- `sarulab-speech/UTMOS22`
- `gokhaneraslan/chatterbox-finetuning` — V3 production 사용 금지, 참고만
