# S01 공통 계약

`scripts.luna_quality`는 production 기본값이 `off`인 독립 패키지다. S01은 validator, database, ranker, production 연결을 구현하지 않는다.

모든 public record는 `schema_version`을 포함하며 JSON-compatible `to_dict`/`from_dict` round-trip을 제공한다. 경로는 repository-relative POSIX 형태로 정규화한다. `ValidationStatus`는 `pass`, `fail`, `unknown`, `not_run`만 허용한다.

optional package 검사는 `find_spec`만 사용한다. 실제 모델 import·load는 하지 않으며, 미설치는 `not_run`으로 기록한다. 예외를 성공으로 바꾸지 않는다.
