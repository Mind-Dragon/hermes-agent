import { describe, expect, it } from 'vitest'

import {
  selectedModelForEnter,
  selectedProviderForEnter,
  selectedProviderIndexForEnter
} from '../lib/modelPickerSelection.js'

describe('model picker selection helpers', () => {
  it('uses the highlighted provider row even when the backing cursor is stale', () => {
    const providerRows = [
      { index: 4, provider: { slug: 'openrouter' } },
      { index: 0, provider: { slug: 'nous' } }
    ]

    expect(selectedProviderForEnter(providerRows, 0)?.slug).toBe('openrouter')
    expect(selectedProviderIndexForEnter(providerRows, 0, 0)).toBe(4)
  })

  it('uses the highlighted model row even when the backing cursor is stale', () => {
    const modelRows = [
      { index: 7, model: 'gpt-5.4' },
      { index: 0, model: 'gpt-4.1' }
    ]

    expect(selectedModelForEnter(modelRows, 0)).toBe('gpt-5.4')
  })

  it('returns null for empty rows', () => {
    expect(selectedProviderForEnter([], 0)).toBeNull()
    expect(selectedModelForEnter([], 0)).toBeNull()
  })
})
