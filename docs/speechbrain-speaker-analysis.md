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

## Managed translation with read-only models

Set `VOICESTUDIO_ARGOS_OFFLINE=1` only after installing the selected Argos
language packs and their Stanza tokenizer resources. This mode initializes
each translation's tokenizer with `download_method=None`, CPU execution and
its existing package directory. It neither downloads on customer requests nor
patches the global Stanza module. Missing/unqualified resources fail the line;
unchanged source text with an error is not a successful translation. Standalone
desktop behavior remains unchanged when this setting is absent.

For the managed Python 3.11 image, run the existing
`core.execstack.ensure_ctranslate2_loadable` repair and import check during
the image build. Its frozen CTranslate2 4.4 wheel requests an executable stack;
attempting that repair only at runtime fails on a read-only root filesystem.
Keep deployed workers read-only rather than weakening their filesystem policy.
