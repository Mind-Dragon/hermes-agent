import { describe, expect, it } from 'vitest'

import { filterRankModels, filterRankProviders, rankText } from '../lib/modelPickerSearch.js'

describe('model picker search ranking', () => {
  const providers = [
    { name: 'Nous Portal', slug: 'nous', models: ['deepseek/deepseek-v3'] },
    { name: 'OpenRouter', slug: 'openrouter', models: ['moonshotai/kimi-k2.5', 'openai/gpt-5.5'] },
    { name: 'Kimi For Coding', slug: 'kimi-coding', models: ['kimi-k2.6-FCED'] },
    { name: 'Kimi For Coding', slug: 'kimi-coding-cn', models: ['kimi-k2.6-cn'] }
  ]
  const labels = ['Nous Portal', 'OpenRouter', 'Kimi For Coding (kimi-coding)', 'Kimi For Coding (kimi-coding-cn)']

  it('preserves order for an empty query', () => {
    expect(filterRankProviders('', providers, labels).map(row => row.provider.slug)).toEqual([
      'nous',
      'openrouter',
      'kimi-coding',
      'kimi-coding-cn'
    ])
  })

  it('ranks provider name prefix matches over child model substring matches', () => {
    expect(filterRankProviders('kimi', providers, labels).map(row => row.provider.slug)).toEqual([
      'kimi-coding',
      'kimi-coding-cn',
      'openrouter'
    ])
  })

  it('keeps duplicate provider names distinct by slug', () => {
    const rows = filterRankProviders('coding-cn', providers, labels)

    expect(rows[0]?.provider.slug).toBe('kimi-coding-cn')
    expect(rows.map(row => row.provider.slug)).toContain('kimi-coding')
  })

  it('finds providers by child model id', () => {
    expect(filterRankProviders('gpt55', providers, labels).map(row => row.provider.slug)).toEqual(['openrouter'])
  })

  it('ranks model prefix before substring before fuzzy subsequence', () => {
    const rows = filterRankModels('kimi', ['openai/not-kimi', 'kimi-k2.6-FCED', 'k-x-i-m-i-test'])

    expect(rows.map(row => row.model)).toEqual(['kimi-k2.6-FCED', 'openai/not-kimi', 'k-x-i-m-i-test'])
  })

  it('matches compact model ids across separators', () => {
    expect(filterRankModels('gpt55', ['openai/gpt-5.5', 'openai/gpt-4.1']).map(row => row.model)).toEqual([
      'openai/gpt-5.5'
    ])
  })

  it('rejects non-matches', () => {
    expect(rankText('zzzz', ['kimi-k2.6-FCED'])).toBeNull()
  })
})
