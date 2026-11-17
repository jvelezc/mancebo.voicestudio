import { describe, expect, it } from 'vitest';
import { assignSpeakerSimilarity, applySpeakerCloneDefaults, segmentGenInputs } from './segments';
import { attributionAt, mergedParts } from './segmentParts';

describe('per-speaker similarity', () => {
  it('changes one speaker and their merged attribution without changing another voice', () => {
    const alice = { id: 'a', text: 'Hello', speaker_id: 'Alice', profile_id: 'auto:alice' };
    const bob = { id: 'b', text: 'Hi', speaker_id: 'Bob', profile_id: 'saved-bob' };
    const combined = {
      ...alice,
      id: 'merged',
      merge_parts: mergedParts(alice, bob),
      merge_parts_original: mergedParts(alice, bob),
    };
    const result = assignSpeakerSimilarity([alice, bob, combined], 'Bob', 'off');
    expect(result[0]).toBe(alice);
    expect(result[1]).toEqual({ ...bob, speaker_similarity: 'off' });
    expect(result[2].speaker_similarity).toBeUndefined();
    expect(attributionAt(result[2].merge_parts, 6)).toEqual({
      speaker_id: 'Bob',
      profile_id: 'saved-bob',
      speaker_similarity: 'off',
    });
    expect(result[2].merge_parts_original[1].speaker_similarity).toBe('off');
    expect(combined.merge_parts[1].speaker_similarity).toBeUndefined();
  });

  it('includes the actual mode in generation and incremental request inputs', () => {
    expect(
      segmentGenInputs({ text: 'Hola', profile_id: 'auto:alice', speaker_similarity: 'off' }),
    ).toMatchObject({ text: 'Hola', profile_id: 'auto:alice', speaker_similarity: 'off' });
  });

  it('newly analyzed source voices default to a consistent match without changing saved voices', () => {
    const sources = { Alice: {}, Bob: {} };
    const result = applySpeakerCloneDefaults(
      [
        { id: 'a', text: 'Hi', speaker_id: 'Alice', profile_id: 'auto:alice' },
        { id: 'b', text: 'Hi', speaker_id: 'Bob', profile_id: 'saved-bob' },
        { id: 'c', text: 'Hi', speaker_id: 'Alice', speaker_similarity: 'off' },
      ],
      sources,
    );
    expect(result[0].speaker_similarity).toBe('consistent');
    expect(result[1]).toEqual({ id: 'b', text: 'Hi', speaker_id: 'Bob', profile_id: 'saved-bob' });
    expect(result[2]).toMatchObject({ profile_id: 'auto:alice', speaker_similarity: 'off' });
  });
});
