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

  it('sorts providers alphabetically for an empty query', () => {
    expect(filterRankProviders('', providers, labels).map(row => row.provider.slug)).toEqual([
      'kimi-coding',
      'kimi-coding-cn',
      'nous',
      'openrouter'
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

  it('prefers coding-plan providers when model matches tie', () => {
    const rows = filterRankProviders('gpt55', [
      { name: 'OpenAI', slug: 'openai', plan: 'api', models: ['openai/gpt-5.5'] },
      { name: 'OpenAI Codex', slug: 'openai-codex', plan: 'coding', models: ['openai/gpt-5.5'] },
      { name: 'Nous Portal', slug: 'nous', plan: 'api', models: ['moonshotai/kimi-k2.5'] }
    ], ['OpenAI', 'OpenAI Codex', 'Nous Portal'])

    expect(rows.map(row => row.provider.slug)).toEqual(['openai-codex', 'openai'])
  })

  it('prefers coding-plan providers for broad gpt queries', () => {
    const rows = filterRankProviders('gpt', [
      { name: 'OpenAI', slug: 'openai', plan: 'api', models: ['gpt-5.4'] },
      { name: 'OpenAI Codex', slug: 'openai-codex', plan: 'coding', models: ['gpt-5.5'] },
      { name: 'GitHub Copilot', slug: 'copilot', plan: 'api', models: ['gpt-5.4'] }
    ], ['OpenAI', 'OpenAI Codex', 'GitHub Copilot'])

    expect(rows.map(row => row.provider.slug).slice(0, 2)).toEqual(['openai-codex', 'copilot'])
  })

  it('sorts models alphabetically with numeric versions first', () => {
    const models = [
      'openai/gpt-4o',
      'openai/gpt-4.1-nano',
      'openai/gpt-5.5',
      'openai/gpt-4.1-mini'
    ]

    expect(filterRankModels('', models).map(row => row.model)).toEqual([
      'openai/gpt-5.5',
      'openai/gpt-4.1-mini',
      'openai/gpt-4.1-nano',
      'openai/gpt-4o'
    ])
  })

  it('prefers higher gpt versions for broad gpt queries', () => {
    const models = [
      'openai/gpt-5-pro',
      'openai/gpt-5.2-pro',
      'openai/gpt-5.4-pro',
      'openai/gpt-5.5-pro'
    ]

    expect(filterRankModels('gpt', models).map(row => row.model)).toEqual([
      'openai/gpt-5.5-pro',
      'openai/gpt-5.4-pro',
      'openai/gpt-5.2-pro',
      'openai/gpt-5-pro'
    ])
  })

  it('surfaces the matching model name for provider rows when the query matches a model id', () => {
    const gptProviders = [
      { name: 'OpenAI', slug: 'openai', models: ['gpt-4.1-mini', 'o3-mini'] },
      { name: 'OpenRouter', slug: 'openrouter', models: ['openai/gpt-5.5', 'moonshotai/kimi-k2.5'] },
      { name: 'Anthropic', slug: 'anthropic', models: ['claude-3.7-sonnet'] }
    ]
    const gptLabels = ['OpenAI', 'OpenRouter', 'Anthropic']
    const rows = filterRankProviders('gpt', gptProviders, gptLabels)

    expect(rows.map(row => row.provider.slug)).toEqual(['openai', 'openrouter'])
    expect((rows[0] as any).modelMatch).toBe('gpt-4.1-mini')
    expect((rows[1] as any).modelMatch).toBe('openai/gpt-5.5')
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
