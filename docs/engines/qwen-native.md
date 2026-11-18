# Qwen native: CPU cloning and voice design

Select **Qwen3 TTS native** after explicitly installing the matching audio.cpp
runtime and the **Qwen3 TTS native (Base cloning + VoiceDesign, Q8_0)** bundle.
It needs about 4.48 GiB of model downloads. Standalone use remains local-first;
availability checks never download weights.

The same engine uses Base 0.6B when a reference recording is supplied and
VoiceDesign 1.7B otherwise. It stops its owned native server before changing
packages, so both models are not resident together. Both must be installed.
No Python Qwen stack, old transformers pin or GPU is required.

## Clone a permitted voice

Provide a clean, authorized reference and its accurate transcript. Enter the
new script, choose a supported language, preview it and review the result before
saving or exporting. The Base model follows its reference; an instruction does
not provide a separate emotion-strength control for a cloned speaker.

## Design a new voice

Use Voice Design with a description and a representative script. Generate a
sample, review it, then save the result as a voice for later scripts. The actual
engine supports English, Chinese, Japanese, Korean, German, French, Russian,
Portuguese, Spanish and Italian. Unsupported explicit languages are rejected.
Description-based generation is not a calibrated identity or emotion guarantee.

The runtime divides longer text into 240-character chunks and joins their
output. Its 2,048-token synthesis budget applies to each chunk. Keep the normal
studio job/project identifiers for recovery; this adapter does not make an
in-memory caller queue durable.

## Operator configuration

- `VOICESTUDIO_QWEN_NATIVE_THREADS`: integer 1–16, default **2** on all platforms.
- `VOICESTUDIO_QWEN_NATIVE_CLONE_MODEL`: explicit Base GGUF path, if using an
  operator-managed installation instead of the pinned model cache.
- `VOICESTUDIO_QWEN_NATIVE_DESIGN_MODEL`: explicit VoiceDesign GGUF path.
- `VOICESTUDIO_QWEN_NATIVE_PORT`: loopback port; default 17870.
- `OMNIVOICE_AUDIOCPP_DIR` / `OMNIVOICE_AUDIOCPP_BIN`: existing audio.cpp runtime
  selection. Do not bypass its self-check.

The v0.9.4 Linux prebuilt requires newer system libraries than Debian bookworm.
A matching source build can run on that image; never upgrade a shared host's
system C library to force an incompatible binary to start. Runtime, model and
source checksums belong in deployment provenance.

The GGUF repository is pinned by `engines/audiocpp/bootstrap.py`. The bundle
contains only the two Qwen files; it does not install OmniVoice or Breeze weights.
See the [Base model card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base),
[VoiceDesign model card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign)
and [native runtime guide](https://github.com/0xShug0/audio.cpp/blob/v0.9.4/docs/models/qwen3_tts.md).
Model-card license labels do not establish all input, reference or output rights;
the local license inventory retains its separate review state.

CPU qualification produced English design and English/Portuguese cloning in
about 25–36 seconds for short samples on a two-CPU worker. Native HTTP and CLI
returned identical short-sample bytes for the same seeds. These observations
are not a throughput guarantee or listening-based voice-identity acceptance.
