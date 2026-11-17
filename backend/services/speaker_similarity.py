"""Per-speaker source-reference policy for dubbing.

The controls choose an actual reference strategy, not a percentage of acoustic
identity. Engines currently have no independent, calibrated similarity strength.
An omitted mode preserves older clients' job-wide ``voice_match`` setting.
"""
from __future__ import annotations

from typing import Literal
from pathlib import Path

SpeakerSimilarity = Literal["consistent", "per_line", "off"]


class SourceReferenceMissingError(ValueError):
    """Expected source-input failure with fixed, safe recovery guidance."""

    code = "dub_source_reference_missing"
    public_message = (
        "No usable source voice reference for this speaker. Re-analyze the source "
        "with speaker detection, assign a saved voice, or turn off Speaker Similarity."
    )

    def __init__(self):
        super().__init__(self.public_message)


def source_voice_policy(
    profile_id: str | None,
    similarity: SpeakerSimilarity | None,
    voice_match: str | None = None,
) -> tuple[str | None, str]:
    """Resolve source cloning without changing a deliberately cast saved voice.

    ``off`` removes only an automatic source binding; it never removes an
    explicitly assigned library voice. ``consistent`` reuses a single reference
    per speaker. ``per_line`` prefers the line's own clean reference, retaining
    the existing same-speaker fallback when that line is too short.
    """
    mode = similarity or voice_match or "per_line"
    if mode not in ("consistent", "per_line", "off"):
        raise ValueError("Unknown speaker similarity mode")
    if mode == "off" and profile_id and profile_id.startswith(("auto:", "auto-seg:")):
        return None, "per_line"
    return profile_id, "per_line" if mode == "off" else mode


def require_source_reference(reference_path: str | None) -> None:
    """An explicit source match must not quietly become a generic voice.

    Automatic references are extracted into the local job folder before any
    sidecar receives them. This checks their source file, not an engine's own
    namespace or a user-assigned library voice.
    """
    if not reference_path or not Path(reference_path).is_file():
        raise SourceReferenceMissingError()
