# S02 Candidate B conditionals cache

`ConditionalsCache` is a production-off, local-only wrapper around the official
Chatterbox Multilingual V3 `Conditionals.save(Path)` and
`Conditionals.load(Path, map_location="cpu")` API.  It does not import or load
Chatterbox itself, and S02 does not connect it to the narration pipeline.

The cache accepts only the fixed Candidate B repository path.  Its manifest
records the Chatterbox source version; T3, S3Gen, Voice Encoder, and tokenizer
filenames plus SHA-256 values; Candidate B's repository-relative path and hash;
`language_id`; `exaggeration`; cache key; artifact SHA-256; schema version; and
creation timestamp.  Candidate B WAV bytes and model checkpoint bytes are never
placed in the JSON manifest or copied into a new source artifact.

Every load recomputes the requested input identity and verifies the persisted
manifest and artifact checksum before deserializing.  Cache misses are explicit:
missing/invalid manifest, source mismatch, missing artifact, artifact hash
mismatch, or deserialization error.  A miss is safe to regenerate through the
existing reference-analysis path when future integration is approved; S02 does
not make a cache miss fatal.

Writes use a same-directory temporary file and `os.replace`, so interrupted
writes cannot leave a partial named artifact or manifest.  The cached
conditionals contain model-derived tensors, not the Candidate B source WAV;
this cache does not claim to make the stochastic T3 token generation or Luna
prosody deterministic.

The fast unit suite uses a fake object with the same `save`/`load` signature.
`tests/luna_quality/integration/test_conditionals_cache_integration.py` is the
separate, opt-in real-model verification; run it with
`RUN_LUNA_CONDITIONALS_INTEGRATION=1` and a pre-populated `PKUSEG_HOME` using
the bundled V3 Python runtime.  It never falls back to writing the user-profile
default cache.
