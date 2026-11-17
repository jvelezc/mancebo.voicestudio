# Keep a recognizable speaker when dubbing

Speaker Similarity uses a speaker's own reference recording when generating the
translated speech. Set it separately for each speaker in **Dub → Cast**. Start
with **Consistent voice**, then preview before generating the full recording.

## Choose a match that fits the recording

| Choice | What changes | When to use it |
| --- | --- | --- |
| **Consistent voice** | Reuses one clean source reference for the same speaker across their lines. | Start here for a recognizable, stable identity. New source voices use this default. |
| **Expressive delivery** | Uses the original line's clean reference when available. Short lines reuse that speaker's reference. | Try this when a line's calmness, energy or expression matters more than maximum consistency. |
| **Off** | Stops using the automatic source voice reference. | Use a different voice or a deliberately generic dub. A separately assigned library voice remains authoritative. |

The controls appear when a source-extracted voice is selected. To change a cast
voice back, select **Auto** for that speaker. Saved voices and designed voices
are deliberate replacements, so they do not pretend to match the original.
Settings apply to that speaker's lines, including retained merge/split attribution.
They are saved with the transcript, undoable, sent to previews and full renders,
and included in changed-audio detection.

These are reference-selection controls. **85% is not a measured or guaranteed
similarity score.** The current engines do not expose a calibrated independent
voice-similarity percentage. A guidance/quality knob also affects text and speech
generation, so it is not relabelled as a voice-match percentage.

## A practical review

1. Upload the original audio/video, transcribe it and check who speaks each line.
   Set the speaker count when you know it. Gap-based estimates are not reliable
   speaker identification; correct the cast before rendering.
2. Choose a supported target language and review the translation. Preserve meaning
   and natural pronunciation rather than forcing the source accent onto another
   language.
3. In **Cast**, select the speaker's **Auto** voice and keep **Speaker Similarity**
   enabled. Choose **Consistent voice** for the first preview.
4. Preview a neutral line and an expressive line for every speaker. Compare them
   with the original. Check recognizable tone/timbre, words, pitch, pauses,
   emotional intent and whether two speakers remain distinct.
5. Try **Expressive delivery** if a line loses its expression. **More → Mirror
   source delivery** can suggest measured delivery directions without changing
   directions already entered. It does not infer emotion; add emotion yourself.
6. Generate, inspect failed/missing lines and timing overflow, then export the
   finished audio/video. Return the authenticated download/file to the user.

Prefer intelligible, natural speech over exact acoustic matching. Reference
quality, separation, diarization, language and installed engine affect results;
neither identity nor emotion is guaranteed by a successful render. Use voices
you have permission to reproduce. Original media stays separate from the dub.

If a requested source match has no local reference file, generation fails with
instructions to re-analyze, assign a saved voice or switch matching off. It does
not silently claim to have preserved that speaker using a generic voice.

## REST API

Use the running instance's normal authentication and discovered project/profile
IDs. After preparation and transcription, send translated lines to
`POST /dub/generate/{job_id}`:

```json
{
  "language": "es",
  "language_code": "es",
  "segment_ids": ["alice-1", "bob-1"],
  "voice_match": "consistent",
  "timing_strategy": "smart_fit",
  "segments": [
    {"start": 0, "end": 4, "text": "Bienvenidos.", "profile_id": "auto:alice", "speaker_similarity": "consistent"},
    {"start": 4, "end": 8, "text": "¡Empecemos!", "profile_id": "auto:bob", "speaker_similarity": "per_line"}
  ]
}
```

`speaker_similarity` accepts `consistent`, `per_line` or `off`. Omit it to preserve
older clients' job-wide `voice_match` behavior. A numeric percentage is rejected.
Preview the same policy through `POST /dub/preview-segment/{job_id}`, supplying
`segment_id`, `profile_id`, `speaker_similarity`, `voice_match`, translated `text`
and target `language`.

The generation response returns `task_id`. Read persisted status from
`GET /jobs/{task_id}` and resume its event stream through
`GET /tasks/stream/{task_id}`; submission is not completion. Stable segment IDs and
the incremental operation identify changed lines. Include every changed line in
`regen_only`, or omit that field for a full render. A disconnected client must
inspect the existing task before submitting again.

## MCP / Hermes

Discover `generate_dub` and `get_dubbing_task` on the fork's `/mcp/` connection.
`generate_dub` accepts the same translated segment objects and speaker policy,
defaults to `voice_match="consistent"`, and returns the task ID immediately.
Call `get_dubbing_task(task_id=...)` until the persisted state is terminal, then
use the authenticated project export action. Do not invent an output URL.

Agent instruction: “Preserve each source speaker, begin with a consistent match,
preview neutral and emotional lines, prioritize intelligibility, and report
unavailable models/references explicitly. Never describe a setting as an achieved
percentage or report translation as completed dubbing.”

These fork tools are not proof that the managed Mancebo deployment exposes them.
For a managed customer, discover the authorized workspace tools first and use
the existing Mancebo connection; do not request the infrastructure operator key.
