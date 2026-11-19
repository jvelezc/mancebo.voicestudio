"""Bounded-memory measurements for managed dubbing delivery checks.

Music is measured independently from the dry generated speech: a loud music bed
must never hide an empty or inaudible voice track.
"""
from __future__ import annotations

import math

import numpy as np
import soundfile as sf


def measure_audio(path: str) -> dict:
    count = 0
    energy = 0.0
    peak = 0.0
    with sf.SoundFile(path) as recording:
        duration = len(recording) / recording.samplerate
        channels = recording.channels
        sample_rate = recording.samplerate
        for block in recording.blocks(blocksize=65536, dtype="float32", always_2d=True):
            if not np.isfinite(block).all():
                raise ValueError("Nonfinite audio")
            count += block.size
            energy += float(np.sum(np.square(block, dtype=np.float64)))
            peak = max(peak, float(np.max(np.abs(block), initial=0)))
    rms = math.sqrt(energy / count) if count else 0.0
    return {
        "duration_seconds": duration,
        "sample_rate": sample_rate,
        "channels": channels,
        "peak": peak,
        "rms_dbfs": max(-160.0, 20 * math.log10(rms)) if rms else -160.0,
        "audible": bool(count and peak >= 0.001 and rms >= 0.0001),
    }


def background_ready(source_duration: float, background: dict | None, separation: str | None) -> bool:
    return bool(
        source_duration > 0
        and separation != "failed"
        and background
        and abs(background["duration_seconds"] - source_duration) <= 0.1
    )


def natural_pacing_ready(parameters: dict, fitted_segments: list[dict]) -> bool:
    allow_retime = parameters.get("allow_video_retime") is True
    valid = bool(
        parameters.get("preserve_pauses") is True
        and type(parameters.get("allow_video_retime")) is bool
        and 1 <= parameters.get("audio_only_rate_cap", 99) <= 1.1
        and fitted_segments
        and all(
            1 <= line.get("audio_rate", 1) <= 1.100001
            and 1 <= line.get("video_ratio", 1) <= (parameters.get("video_slow_cap", 1) if allow_retime else 1)
            and line.get("overflow_s", 0) <= 0.000001
            and line.get("start", -1) >= line.get("source_start", 1e9) - 0.0001
            and line.get("end", -1) >= line.get("start", 1e9)
            for line in fitted_segments
        )
    )
    if not valid:
        return False
    previous = None
    for line in fitted_segments:
        if previous is None:
            if abs(line["start"] - line["source_start"]) > .0001:
                return False
        elif line["source_start"] >= previous["source_end"]:
            source_gap = line["source_start"] - previous["source_end"]
            output_gap = line["start"] - previous["end"]
            if abs(output_gap - source_gap) > .0002:
                return False
        if not allow_retime and (abs(line["start"] - line["source_start"]) > .0001 or line["end"] > line["source_end"] + .0001):
            return False
        previous = line
    return True
