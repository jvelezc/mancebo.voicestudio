"""Installed-only SpeechBrain ECAPA speaker embeddings and global clustering.

Speech activity is scanned through the entire recording. Silence never ends
analysis. Finished embedding windows are checked and reused after interruption.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from uuid import uuid4

BACKEND_ID = "speechbrain-ecapa"
MODEL_ID = "speechbrain/spkrec-ecapa-voxceleb"
MODEL_ENV = "VOICESTUDIO_SPEECHBRAIN_MODEL_DIR"
RATE = 16000


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def installed_model() -> tuple[Path, dict]:
    configured = os.environ.get(MODEL_ENV, "").strip()
    root = Path(configured).expanduser()
    if not configured or not root.is_absolute() or not root.is_dir():
        raise FileNotFoundError(
            "Install and configure the local SpeechBrain ECAPA model"
        )
    manifest = root / "model-manifest.json"
    checkpoint = root / "embedding_model.ckpt"
    if (
        not manifest.is_file()
        or manifest.stat().st_size > 65536
        or not checkpoint.is_file()
    ):
        raise FileNotFoundError(
            "Install the ECAPA checkpoint and its provenance manifest"
        )
    data = json.loads(manifest.read_text(encoding="utf-8"))
    entry = data.get("files", {}).get("embedding_model.ckpt", {})
    if (
        data.get("repo") != MODEL_ID
        or data.get("license") != "apache-2.0"
        or re.fullmatch(r"[a-f0-9]{40}", str(data.get("revision", ""))) is None
        or re.fullmatch(r"[a-f0-9]{64}", str(entry.get("sha256", ""))) is None
        or entry.get("bytes") != checkpoint.stat().st_size
    ):
        raise ValueError("The installed ECAPA model provenance could not be verified")
    return root.resolve(), data


def status() -> dict:
    result = {
        "model": MODEL_ID,
        "model_installed": False,
        "runtime_installed": importlib.util.find_spec("speechbrain") is not None,
        "installed": False,
        "reason": "Install and configure the local SpeechBrain ECAPA model",
    }
    try:
        installed_model()
    except (OSError, ValueError, TypeError, KeyError):
        return result
    result["model_installed"] = True
    result["installed"] = result["runtime_installed"]
    result["reason"] = (
        None if result["installed"] else "Install the SpeechBrain runtime"
    )
    return result


def speech_regions(source, check):
    """Bounded overlapping scans include both ends and every middle window."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    import soundfile as sf

    regions = []
    window, overlap = 30 * RATE, RATE
    with sf.SoundFile(str(source)) as recording:
        if recording.samplerate != RATE or recording.channels != 1:
            raise ValueError("Speaker analysis requires normalized 16 kHz mono audio")
        offset = 0
        while offset < len(recording):
            check()
            recording.seek(offset)
            samples = recording.read(window, dtype="float32")
            for region in get_speech_timestamps(
                samples,
                VadOptions(
                    min_speech_duration_ms=100,
                    min_silence_duration_ms=300,
                    speech_pad_ms=80,
                ),
                sampling_rate=RATE,
            ):
                start, end = (
                    offset + region["start"],
                    min(offset + region["end"], len(recording)),
                )
                if not 0 <= start < end <= len(recording):
                    raise ValueError("Speech activity returned invalid boundaries")
                regions.append((start, end))
            if offset + window >= len(recording):
                break
            offset += window - overlap
    merged = []
    for start, end in sorted(regions):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def embedding_windows(regions):
    result = []
    width, hop = 2 * RATE, RATE
    for group, (start, end) in enumerate(regions):
        positions = list(range(start, max(start + 1, end - width + 1), hop))
        tail = max(start, end - width)
        if positions[-1] != tail:
            positions.append(tail)
        result.extend(
            (position, min(position + width, end), group) for position in positions
        )
    return result


def cluster_embeddings(features, count=None):
    import numpy as np
    from speechbrain.integrations.alignment.diarization import Spec_Clust_unorm
    from sklearn.cluster import KMeans

    if len(features) == 1:
        if count not in (None, 1):
            raise ValueError(
                "The recording has too little speech for the requested speaker count"
            )
        return np.zeros(1, dtype=int)
    if count is not None and count > len(features):
        raise ValueError(
            "The recording has too little speech for the requested speaker count"
        )
    if count == 1:
        return np.zeros(len(features), dtype=int)
    # Spectral discovery has bounded quadratic memory. Every speech embedding
    # still participates in the final refinement; the tail is not discarded.
    selected = np.linspace(0, len(features) - 1, min(1024, len(features)), dtype=int)
    cluster = Spec_Clust_unorm(min_num_spkrs=1, max_num_spkrs=min(20, len(selected)))
    cluster.do_spec_clust(features[selected], k_oracle=count, p_val=0.3)
    labels = np.asarray(cluster.labels_, dtype=int)
    centers = np.stack(
        [
            features[selected][labels == label].mean(axis=0)
            for label in sorted(set(labels))
        ]
    )
    refined = KMeans(
        n_clusters=len(centers), init=centers, n_init=1, random_state=0
    ).fit_predict(features)
    if count is not None and len(set(refined)) != count:
        raise ValueError(
            "Speaker analysis could not distinguish the requested speaker count"
        )
    # Stable public labels follow first appearance, not random cluster numbers.
    mapping = {}
    return np.asarray(
        [mapping.setdefault(int(label), len(mapping)) for label in refined], dtype=int
    )


class SpeechBrainDiarization:
    backend_id = BACKEND_ID

    def __init__(self):
        self.root, self.manifest = installed_model()
        self.checkpoint = self.root / "embedding_model.ckpt"
        if (
            sha256(self.checkpoint)
            != self.manifest["files"]["embedding_model.ckpt"]["sha256"]
        ):
            raise ValueError("The installed ECAPA checkpoint checksum does not match")
        value = os.environ.get("VOICESTUDIO_DIARIZATION_THREADS", "2")
        if not value.isdecimal() or not 1 <= int(value) <= 16:
            raise ValueError(
                "Speaker analysis requires between one and sixteen CPU threads"
            )
        self.threads = int(value)
        self.encoder = None

    def _encoder(self):
        if self.encoder is not None:
            return self.encoder
        import torch
        from speechbrain.inference.classifiers import EncoderClassifier
        from speechbrain.lobes.features import Fbank
        from speechbrain.lobes.models.ECAPA_TDNN import ECAPA_TDNN
        from speechbrain.processing.features import InputNormalization

        class EmbeddingOnly(EncoderClassifier):
            MODULES_NEEDED = ["compute_features", "mean_var_norm", "embedding_model"]

        torch.set_num_threads(self.threads)
        model = ECAPA_TDNN(
            input_size=80,
            channels=[1024, 1024, 1024, 1024, 3072],
            kernel_sizes=[5, 3, 3, 3, 1],
            dilations=[1, 2, 3, 4, 1],
            attention_channels=128,
            lin_neurons=192,
        )
        # The reviewed architecture is code, not an executable remote YAML.
        # Runtime loads only a hash-verified tensor checkpoint, without network.
        model.load_state_dict(
            torch.load(self.checkpoint, map_location="cpu", weights_only=True)
        )
        self.encoder = EmbeddingOnly(
            modules={
                "compute_features": Fbank(n_mels=80),
                "mean_var_norm": InputNormalization(
                    norm_type="sentence", std_norm=False
                ),
                "embedding_model": model,
            },
            hparams={"sample_rate": RATE},
            run_opts={"device": "cpu"},
        )
        self.encoder.eval()
        return self.encoder

    def _embedding(self, recording, start, end, cache):
        import numpy as np
        import torch

        path = cache / f"embedding-{start}-{end}.npy"
        metadata = path.with_suffix(".json")
        if (
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size <= 8192
            and metadata.is_file()
            and not metadata.is_symlink()
            and metadata.stat().st_size <= 1024
        ):
            try:
                saved = json.loads(metadata.read_text())
                if saved["sha256"] == sha256(path):
                    vector = np.load(path, allow_pickle=False)
                    if vector.shape == (192,) and np.isfinite(vector).all():
                        return vector
            except (OSError, ValueError, KeyError, EOFError):
                # A missing/corrupt checkpoint is recomputed from the recording;
                # never treat it as successful evidence or log recording content.
                pass
        recording.seek(start)
        samples = recording.read(end - start, dtype="float32")
        if len(samples) != end - start:
            raise ValueError("Speaker analysis could not read a complete speech window")
        samples = np.pad(samples, (0, max(0, RATE - len(samples))))
        with torch.inference_mode():
            vector = (
                self._encoder()
                .encode_batch(torch.from_numpy(samples).unsqueeze(0))
                .squeeze()
                .cpu()
                .numpy()
            )
        if (
            vector.shape != (192,)
            or not np.isfinite(vector).all()
            or np.linalg.norm(vector) <= 0
        ):
            raise ValueError("SpeechBrain returned an invalid speaker embedding")
        vector = vector / np.linalg.norm(vector)
        temporary = cache / (uuid4().hex + ".npy")
        with os.fdopen(
            os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"
        ) as output:
            np.save(output, vector, allow_pickle=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = cache / (uuid4().hex + ".json")
        with os.fdopen(
            os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600),
            "w",
            encoding="utf-8",
        ) as output:
            json.dump({"sha256": sha256(path)}, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, metadata)
        return vector

    def __call__(
        self, audio_path, *, num_speakers=None, job_id=None, cancel_check=None
    ):
        if num_speakers is not None and (
            type(num_speakers) is not int or not 1 <= num_speakers <= 20
        ):
            raise ValueError(
                "Choose between one and twenty speakers, or automatic detection"
            )
        import numpy as np
        import soundfile as sf
        from pyannote.core import Annotation, Segment

        def check():
            if cancel_check is not None and cancel_check():
                raise RuntimeError("Speaker analysis cancelled")

        check()
        original = Path(audio_path).resolve()
        fingerprint = hashlib.sha256(
            (
                sha256(original)
                + ":"
                + self.manifest["files"]["embedding_model.ckpt"]["sha256"]
                + ":speechbrain-ecapa-v1"
            ).encode()
        ).hexdigest()
        parent = original.parent / ".speechbrain-diarization"
        if parent.is_symlink():
            raise ValueError("Speaker analysis checkpoint storage is unsafe")
        parent.mkdir(mode=0o700, exist_ok=True)
        cache = parent / fingerprint
        if cache.is_symlink():
            raise ValueError("Speaker analysis checkpoint storage is unsafe")
        cache.mkdir(mode=0o700, exist_ok=True)
        with TemporaryDirectory(prefix="voicestudio-speechbrain-") as directory:
            source = original
            try:
                info = sf.info(str(source))
            except sf.LibsndfileError:
                info = None
            if info is None or info.samplerate != RATE or info.channels != 1:
                from services.ffmpeg_utils import find_ffmpeg, local_inputs_only

                source = Path(directory) / "input.wav"
                subprocess.run(
                    local_inputs_only(
                        [
                            find_ffmpeg(),
                            "-nostdin",
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-y",
                            "-i",
                            str(original),
                            "-vn",
                            "-ac",
                            "1",
                            "-ar",
                            str(RATE),
                            "-c:a",
                            "pcm_s16le",
                            str(source),
                        ],
                        tool="ffmpeg",
                    ),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=600,
                    check=True,
                )
            regions = speech_regions(source, check)
            windows = embedding_windows(regions)
            annotation = Annotation()
            if not windows:
                return annotation
            vectors = []
            with sf.SoundFile(str(source)) as recording:
                for start, end, group in windows:
                    check()
                    vectors.append(self._embedding(recording, start, end, cache))
            check()
            labels = cluster_embeddings(np.asarray(vectors), num_speakers)
            if len(labels) != len(windows):
                raise ValueError("Speaker clustering did not cover the full recording")
            for index, ((start, end, group), label) in enumerate(zip(windows, labels)):
                if index and windows[index - 1][2] == group:
                    previous = windows[index - 1]
                    start = (previous[0] + previous[1] + start + end) // 4
                if index + 1 < len(windows) and windows[index + 1][2] == group:
                    following = windows[index + 1]
                    end = (
                        windows[index][0]
                        + windows[index][1]
                        + following[0]
                        + following[1]
                    ) // 4
                if (
                    type(label) not in (int, np.int32, np.int64)
                    or not 0 <= label < 20
                    or not start < end
                ):
                    raise ValueError(
                        "Speaker clustering returned invalid turn boundaries"
                    )
                annotation[Segment(start / RATE, end / RATE), index] = (
                    f"SPEAKER_{int(label):02d}"
                )
            return annotation
