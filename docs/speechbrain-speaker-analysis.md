# SpeechBrain speaker analysis for the managed studio

The managed Mancebo studio uses SpeechBrain ECAPA-TDNN speaker embeddings,
speech-activity detection and global speaker clustering. It does not use the
noncommercial Sortformer v1 weights. The existing standalone default remains
unchanged unless this backend is explicitly selected.

## Why this model

[`speechbrain/spkrec-ecapa-voxceleb`](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb)
is an Apache 2.0 pretrained model with 192-dimensional speaker embeddings.
Its publisher reports 0.80% equal-error rate on the cleaned VoxCeleb1 speaker
verification test. That is a verification benchmark, not a promise about this
application's diarization, overlapping speakers or multilingual dubbing quality.
CPU use, model size, a mature SpeechBrain implementation and commercial-use
licensing make it the selected candidate; qualify actual recordings before
announcing deployment quality.

ECAPA recognizes voice characteristics; it is not a complete diarization
pipeline by itself. The adapter scans speech activity with the installed
Silero VAD from the frozen faster-whisper dependency, extracts overlapping
SpeechBrain embeddings and clusters them across the recording. This retains a
speaker's label after silence instead of cycling labels between chunks.
The Silero project has an [MIT license](https://github.com/snakers4/silero-vad/blob/master/LICENSE).

## Install and configure

Explicitly download an immutable revision of the selected SpeechBrain model.
Retain the publisher's model card and license, revision, full file sizes and
SHA-256 hashes. Keep `embedding_model.ckpt` and `model-manifest.json` in the
operator-managed model directory, mounted read-only in each workspace worker.
The Mancebo qualification installation uses revision
`0f99f2d0ebe89ac095bcc5903c4dd8f72b367286`; its 83,316,686-byte
`embedding_model.ckpt` has SHA-256
`0575cb64845e6b9a10db9bcb74d5ac32b326b8dc90352671d345e2ee3d0126a2`.
Installation/provenance is verified; runtime and dubbing acceptance are separate.
The manifest has this shape (use the real revision, byte size and digest):

```json
{
  "repo": "speechbrain/spkrec-ecapa-voxceleb",
  "license": "apache-2.0",
  "revision": "40 lowercase hexadecimal characters",
  "files": {
    "embedding_model.ckpt": { "sha256": "64 lowercase hexadecimal characters", "bytes": 0 }
  }
}
```

Operator settings:

```sh
OMNIVOICE_DIARIZATION_BACKEND=speechbrain-ecapa
VOICESTUDIO_SPEECHBRAIN_MODEL_DIR=/installed-models/speechbrain-ecapa
VOICESTUDIO_DIARIZATION_THREADS=2
```

The engine inventory reports **SpeechBrain ECAPA (CPU)** and the actual model
ID. Runtime validates the checkpoint hash, loads its tensor weights into the
reviewed SpeechBrain architecture and does not execute remote YAML or download
models. The fork already pins SpeechBrain 1.1.0 in its Python lockfile. Customers
use Mancebo sign-in or their existing Mancebo API key; no Hugging Face token,
Google credential or separate VoiceStudio operator key is customer setup.

## Long recordings and recovery

Speech activity is scanned in overlapping 30-second windows through the end
of the recording. A silent window never terminates the scan. Overlapping
speech embeddings retain their absolute timestamps; global clustering produces
consistent speaker IDs. Spectral discovery uses bounded landmarks, then every
speech embedding participates in full-recording refinement. There is no
two-minute recording limit.

Hash-verified embedding checkpoints live in the recording's private
`.speechbrain-diarization` directory. A worker restart reuses completed windows;
a changed source/model or corrupt checkpoint requires recomputation. Include
these private files in encrypted workspace backups and remove them with the
recording's retained data. They are not public job logs or customer credentials.

When known, supply the speaker count (1–20) to improve clustering. Review
speaker assignments, short utterances, overlap and reference clips before
dubbing. Automatic labels do not identify a person by name or guarantee vocal
identity/emotion. Transcript words, speaker identity and translated voice
similarity are separately verified stages. Model boundaries, CPU/memory/disk
capacity and the worker deadline remain operational constraints; do not return
partial output as a complete recording.

Automatic discovery uses a normalized, nonnegative cosine-affinity graph and
includes the first eigenvalue gap, so one narrator is a valid result. The
conversational SpeechBrain recipe's automatic count starts at two speakers;
using it unchanged also fragmented short narration into many tiny references.
All speech windows still participate in refinement. Speaker count remains an
estimate requiring review, particularly for overlapping or very short speech.

## Managed delivery checks

`VOICESTUDIO_DUB_NATURAL_PACING=1` opts the managed worker into source-pause
preservation and at most 10% speech acceleration. Fixed-length requests retain
the original video timeline: an overlong translation needs shorter reviewed
wording, rather than clipped speech or consumption of the next pause. An explicit
`timing_strategy="stretch_video"` request allows the video to run longer while
preserving sentence gaps and natural delivery. The selected output timeline,
including its complete tail, must match the rendered narration and final video.
Standalone fitting defaults and existing default cache fingerprints are unchanged.

Install the reviewed Demucs `htdemucs` model before customer execution and set
`VOICESTUDIO_DEMUCS_MODELS_DIR` to its read-only directory. It must contain
`htdemucs.yaml` and `955717e8-8726e21a.th`; the qualification checkpoint SHA-256 is
`8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4` (84,141,911 bytes).
Record the [publisher's model manifest](https://github.com/facebookresearch/demucs/blob/main/demucs/remote/htdemucs.yaml)
and [MIT license](https://github.com/facebookresearch/demucs/blob/main/LICENSE).
Managed tasks use the local repository instead of downloading model state.

`GET /dub/quality/{project}?lang=es` checks validated, project-owned artifacts
without returning paths or transcript text: full source/stem duration, independent
dry-narration audibility and persisted actual fitting evidence. A silent music
stem is valid for speech-only sources; a loud music stem cannot satisfy the
narration check. The Mancebo gateway refuses incomplete separation, missing
policy, rushed/overflowing lines, missing narration and incomplete duration.
Its audio and video exports explicitly preserve the background bed. Listening
review and the optional second-pass ASR QC remain separate from these structural
checks; they do not certify pronunciation, emotion or clinical correctness.

Managed Qwen renders can retain finished synthesis segments in the native private
resume journal. Reuse requires the same complete synthesis input, reference
audio hash, runtime binary hash and exact model hash. A live process whose
loaded-artifact proof differs from disk cannot contribute reusable speech.
Changed models, binaries or text invalidate the affected recovery entry;
unproven engines continue to render conservatively without journal reuse.
Generated edge padding is removed before planning and again consistently at mix
time; pauses inside a spoken phrase are retained. Timing failures identify the
affected segment IDs and measured natural/available duration for review, rather
than asking the assistant to speed up the whole recording.

## Managed translation with read-only models

Set `VOICESTUDIO_ARGOS_OFFLINE=1` only after installing the selected Argos
language packs and their Stanza tokenizer resources. This mode initializes
each translation's tokenizer with `download_method=None`, CPU execution and
its existing package directory. It neither downloads on customer requests nor
patches the global Stanza module. Missing/unqualified resources fail the line;
unchanged source text with an error is not a successful translation. Standalone
desktop behavior remains unchanged when this setting is absent.
Managed mode also suppresses Argos sentence-level INFO logs, which contain
source and translated scripts, while retaining warnings and errors.

For the managed Python 3.11 image, run the existing
`core.execstack.ensure_ctranslate2_loadable` repair and import check during
the image build. Its frozen CTranslate2 4.4 wheel requests an executable stack;
attempting that repair only at runtime fails on a read-only root filesystem.
Keep deployed workers read-only rather than weakening their filesystem policy.

## Sequential model ownership

Managed Qwen workers set `VOICESTUDIO_QWEN_NATIVE_DYNAMIC_PORT=1`. Each model
launch obtains a separate loopback port and random-identity configuration/log
directory. This prevents a surviving cloning server from blocking a later design
request at the shared default port. The existing server-identity challenge is
still required before submitting text or references. Never kill a process merely
because it holds a port. The standalone configured-port behavior is unchanged
when this setting is absent.
The managed adapters also share a generation/handoff lock and reap the previous
adapter's owned model process before loading another. Separate registry and
prewarm instances must not keep multiple models resident inside an 8 GiB worker.
Handoff waits for active generation; it does not interrupt it to reclaim memory.

Managed workers also set `VOICESTUDIO_PRESERVE_FULL_VIDEO=1`. Download and
preview muxes retain the source's silent video tail instead of ending at the
shorter speech track. Managed preview cache names are separate so an old trimmed
preview cannot be reused. Standalone mux behavior is unchanged without opt-in.
