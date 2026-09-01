# Nalu Studio

An offline Korean narration workspace for building and repeatedly generating a distinct, consistent voice.

## Why I built this

I wanted to start a YouTube channel. There are many AI-made explainer videos now, and their voices can sound very polished.

But most of them use similar voices with a similar feel. Rather than reuse a voice that already appears everywhere, I wanted a voice that could grow with my videos and feel like my own.

So I spent a lot of tokens and time listening to generations, revising them, and generating them again. Eventually, I made the voice I wanted: **half air, half sound**.

Making the videos themselves was harder. This is an ordinary laptop, not a high-end production machine. Blender was not reliably usable, and tools such as Flow felt premature without a stronger visual foundation. Video production stalled more than once, but I did not want to give up on the voice.

I also could not keep spending nearly all of a video's credits, then spending a week just chatting and iterating. I needed something more repeatable: a system that could take new dialogue and recreate the same voice without rebuilding the process from scratch.

Nalu Studio is that system.

## What it does

- Generates Korean narration from dialogue text with a fixed voice condition.
- Uses **Chatterbox Multilingual V3** for the production voice path.
- Provides `FAST` mode for one-take previews and `PRODUCTION` mode for best-of-N generation with local quality evaluation.
- Reuses the resident model and prepared voice condition across requests.
- Connects optional local quality validators through WAV/JSON contracts: transcription alignment, speaker similarity, MOS, preference data, and a prosody bank.

## Quick start

The production runtime and a locally authorized voice reference must be prepared first. They are intentionally not distributed with this repository.

```powershell
.\engine\chatterbox-v3\venv\Scripts\python.exe .\scripts\luna_voice.py `
  --mode fast `
  --text "아이언맨 슈트에 반드시 필요했을 기술은 냉각입니다." `
  --output .\outputs\nalu.wav
```

The first request loads the model. Later requests reuse the resident worker and prepared voice condition. Each new line is still synthesized; Nalu Studio does not retrieve a prerecorded sentence.

## Modes

| Mode | Use | Result |
| --- | --- | --- |
| `FAST` | Fast review and everyday generation | One WAV take |
| `PRODUCTION` | Final delivery review | Best-of-N plus local quality evaluation |

## Privacy and redistribution

This repository does not distribute private voice-reference audio, generated personal-voice WAV files, model checkpoints, or local model caches. Run it only with audio and models that you are authorized to use.

Audio remains local. The quality runtime uses WAV/JSON file contracts and does not upload voice audio to an external service.

## Status

The FAST/PRODUCTION integration is implemented. The production default remains subject to the creator's listening and approval.
