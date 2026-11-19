# Local lip-sync rendering and dubbing quality tools

VoiceStudio owns the rendering and evidence contract. A caller such as Mancebo's
Eddie chooses the shot, prepares the dialogue, selects repairs, and reviews or
delivers the result under its own permissions. These are opt-in local commands.

## Render one prepared speaking shot

Use Python 3.11+, FFmpeg and FFprobe on `PATH`, and an isolated CUDA environment.
The Windows qualification used PyTorch 2.10 CUDA 12.8, Diffusers 0.36.0,
Transformers 5.15.1, OpenCV headless 4.12.0.88, NumPy and SciPy. The tool reads
explicit local input and installed model files. It uses the pinned file hashes
in `scripts/dub_lip_sync.py` and performs no model downloads.

| Installed path under `--models` | Pinned source |
| --- | --- |
| `musetalk/musetalk.json`, `musetalk/unet.pth` | [MuseTalk 1.5 checkpoint](https://huggingface.co/TMElyralab/MuseTalk/tree/c9ac4cdcedcae22c186fbbf67261961e246c4760/musetalkV15) |
| `whisper/config.json`, `whisper/model.safetensors`, `whisper/preprocessor_config.json` | [Whisper Tiny](https://huggingface.co/openai/whisper-tiny/tree/169d4a4341b33bc18d8881c4b69c2e104e1cc0af) |
| `vae/config.json`, `vae/diffusion_pytorch_model.safetensors` | [Stable Diffusion MSE VAE](https://huggingface.co/stabilityai/sd-vae-ft-mse/tree/31f26fdeee1355a5c34592e401dd41e45d25a493) |
| `yunet.onnx` | [OpenCV YuNet March 2023](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) |

Provide one MP4 shot with one visible, trackable speaker. Prepare a zero-based
25 fps timeline at up to 1920×1080 and up to 30 seconds. Supply two WAVs on that
same timeline. `--dialogue` contains the timed speech that drives the mouth.
`--mix` contains the finished speech, music and effects to put in the MP4.
Keep originals and pass a new output path in an existing directory.

```sh
python scripts/dub_lip_sync.py --video shot.mp4 --dialogue timed.wav --mix final.wav --models /path/to/models --output review.mp4
```

The renderer checks the presentation timeline and both audio lengths, then
stabilizes the face crop and composites a feathered lower-face patch. Its
receipt identifies the new file by SHA-256 and reports changed frames. The
receipt leaves mouth quality and perceptual sync unverified. Review motion
around closures, pauses and shot boundaries. Keep off-screen and multi-face
shots in the editing workflow until they have the right speaker selection.

## Check evidence before delivery

Collect measurements on the final timeline. A positive audio-to-mouth offset
means audio is late. Compare speech and pauses with the intended scene beats.
Report observed mouth artifacts from motion review. A valid file or clean
transcript alone does not assess lip motion.

```json
{
  "artifact_sha256": "<sha256 of the rendered file>",
  "duration_ms": 5200,
  "expected_cue_ids": ["first", "second"],
  "cues": [{"id":"first", "expected_ms":[180,2900], "observed_ms":[246,1740], "render_speed":1},
           {"id":"second", "expected_ms":[3180,5160], "observed_ms":[1740,3980], "render_speed":1}],
  "shots": [{"id":"shot-1", "range_ms":[0,5200], "visible_speech":true, "av_offset_ms":null,
             "sync_review":"unverified", "mouth_review":"warping"}],
  "mix": {"wording":"pass", "voice":"unverified", "background":"unverified", "peaks":"pass"}
}
```

```sh
python scripts/check_dub_evidence.py evidence.json --artifact review.mp4
```

The checker verifies the local file digest and duration and decodes the video
and audio. Exit 3 (`repair_required`) identifies affected spans and suggested
actions. Exit 2 (`review_required`) identifies missing or invalid evidence.
Exit 0 (`checks_passed`) applies to the supplied measurements and exact
artifact. Cover the full shot timeline and approved cue inventory. Off-screen
shots explicitly use `visible_speech: false`. The caller can set the tolerances,
which default to 200 ms for scene beats, 80 ms for measured lip offset, and a
maximum acceleration of 1.10×. The caller owns regeneration and review decisions.

The local Windows qualification rendered a 130-frame, single-speaker shot.
Hosted worker availability and perceptual acceptance require separate checks.
