import { describe, expect, it } from 'vitest'
import { progressFromDraft, progressWithDraft } from './Planner'

describe('Planner progress saving', () => {
  it('unlocks only when the edited RP reaches the vehicle cost', () => {
    expect(progressFromDraft('50', 100)).toEqual({ rp: 50, done: false })
    expect(progressFromDraft('100', 100)).toEqual({ rp: 100, done: true })
  })

  it('clamps invalid and excessive values before saving', () => {
    expect(progressFromDraft('-20', 100)).toEqual({ rp: 0, done: false })
    expect(progressFromDraft('250', 100)).toEqual({ rp: 100, done: true })
    expect(progressFromDraft('invalid', 100)).toEqual({ rp: 0, done: false })
  })

  it('does not reset the completion flag for catalog entries without an RP cost', () => {
    expect(progressFromDraft('0', 0, true)).toEqual({ rp: 0, done: true })
    expect(progressFromDraft('0', 0, false)).toEqual({ rp: 0, done: false })
  })

  it('overlays the unsaved target draft on cascade progress', () => {
    expect(progressWithDraft(
      { 1: { rp_current: 50, done: false }, 2: { rp_current: 25, done: false } },
      1,
      { rp: 75, done: false },
    )).toEqual({
      1: { rp_current: 75, done: false },
      2: { rp_current: 25, done: false },
    })
  })
})
