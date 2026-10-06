import { describe, expect, it } from 'vitest';
import { activeGrantIds, rebaseGrantDraft } from './grants';

describe('grant draft intent after a concurrent revision', () => {
  it('keeps a competing addition and preserves the explicit requested addition', () => {
    expect(rebaseGrantDraft(new Set(['a']), new Set(['a', 'b']), new Set(['a', 'c']))).toEqual(
      new Set(['a', 'b', 'c']),
    );
  });
  it('preserves a competing revocation when the user did not request that resource', () => {
    expect(rebaseGrantDraft(new Set(['a', 'c']), new Set(['a', 'b', 'c']), new Set(['a']))).toEqual(
      new Set(['a', 'b']),
    );
  });
  it('retains an explicit removal while leaving unrelated new grants unchanged', () => {
    expect(rebaseGrantDraft(new Set(['a', 'b']), new Set(['a']), new Set(['a', 'b', 'c']))).toEqual(
      new Set(['a', 'c']),
    );
  });
  it('does not treat a revoked record as an active selection', () => {
    expect(
      activeGrantIds([
        { resource_id: 'a', state: 'active' },
        { resource_id: 'b', state: 'revoked' },
      ]),
    ).toEqual(new Set(['a']));
  });
});
