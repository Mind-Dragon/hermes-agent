import type { ModelOptionProvider } from '../gatewayTypes.js'

export type MatchScore = [tier: number, distance: number, length: number]

export interface RankedModel {
  index: number
  model: string
  score: MatchScore
}

export interface RankedProvider {
  index: number
  label: string
  modelMatch?: string
  provider: ModelOptionProvider
  score: MatchScore
}

const SEP_RE = /[\s._\-/:]+/g

const normalizeWords = (value: string) => value.toLowerCase().replace(SEP_RE, ' ').trim().replace(/\s+/g, ' ')
const normalizeCompact = (value: string) => normalizeWords(value).replace(/\s+/g, '')

const subsequenceGap = (needle: string, haystack: string): number | null => {
  if (!needle) {
    return 0
  }

  let pos = -1
  let first = -1
  let last = -1

  for (const ch of needle) {
    const next = haystack.indexOf(ch, pos + 1)

    if (next < 0) {
      return null
    }

    if (first < 0) {
      first = next
    }

    last = next
    pos = next
  }

  return Math.max(0, last - first + 1 - needle.length)
}

const bestScore = (a: MatchScore | null, b: MatchScore | null) => {
  if (!a) {
    return b
  }

  if (!b) {
    return a
  }

  return compareMatchScore(a, b) <= 0 ? a : b
}

const compareModelName = (a: string, b: string): number => {
  const left = normalizeWords(a).split(' ').filter(Boolean)
  const right = normalizeWords(b).split(' ').filter(Boolean)
  const limit = Math.min(left.length, right.length)

  for (let i = 0; i < limit; i++) {
    const aPart = left[i]!
    const bPart = right[i]!
    const aNumeric = /^\d+$/.test(aPart)
    const bNumeric = /^\d+$/.test(bPart)

    if (aNumeric && bNumeric) {
      const numericDiff = Number(bPart) - Number(aPart)

      if (numericDiff) {
        return numericDiff
      }

      if (aPart.length !== bPart.length) {
        return aPart.length - bPart.length
      }

      continue
    }

    if (aNumeric !== bNumeric) {
      return aNumeric ? -1 : 1
    }

    const textDiff = aPart.localeCompare(bPart, undefined, { sensitivity: 'base' })

    if (textDiff) {
      return textDiff
    }
  }

  return left.length - right.length || a.localeCompare(b, undefined, { sensitivity: 'base' })
}

const rankField = (query: string, field: string): MatchScore | null => {
  const qWords = normalizeWords(query)
  const qCompact = normalizeCompact(query)
  const fRaw = field.toLowerCase()
  const fWords = normalizeWords(field)
  const fCompact = normalizeCompact(field)

  if (!qWords || !qCompact) {
    return [0, 0, field.length]
  }

  if (!fWords && !fCompact) {
    return null
  }

  if (fRaw.indexOf(query.toLowerCase()) === 0 || fWords.indexOf(qWords) === 0 || fCompact.indexOf(qCompact) === 0) {
    return [0, 0, field.length]
  }

  const tokens = fWords.split(' ').filter(Boolean)
  let tokenIdx = -1

  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i]!

    if (token.indexOf(qWords) === 0 || token.indexOf(qCompact) === 0) {
      tokenIdx = i
      break
    }
  }

  if (tokenIdx >= 0) {
    return [1, tokenIdx, field.length]
  }

  const rawIdx = fRaw.indexOf(query.toLowerCase())
  const wordsIdx = fWords.indexOf(qWords)
  const compactIdx = fCompact.indexOf(qCompact)
  const substringPositions = [rawIdx, wordsIdx, compactIdx].filter(pos => pos >= 0)

  if (substringPositions.length) {
    return [2, Math.min(...substringPositions), field.length]
  }

  const gap = subsequenceGap(qCompact, fCompact)

  if (gap !== null) {
    return [3, gap, field.length]
  }

  return null
}

export function compareMatchScore(a: MatchScore, b: MatchScore): number {
  return a[0] - b[0] || a[1] - b[1]
}

const compareProviderRows = (a: RankedProvider, b: RankedProvider) =>
  a.provider.name.localeCompare(b.provider.name, undefined, { sensitivity: 'base', numeric: true }) ||
  a.provider.slug.localeCompare(b.provider.slug, undefined, { sensitivity: 'base', numeric: true }) ||
  a.index - b.index

const compareProviderPlan = (a: RankedProvider, b: RankedProvider) => {
  const aPlan = a.provider.plan === 'coding' ? 0 : 1
  const bPlan = b.provider.plan === 'coding' ? 0 : 1

  return aPlan - bPlan
}

export function rankText(query: string, fields: string[]): MatchScore | null {
  const trimmed = query.trim()

  if (!trimmed) {
    return [0, 0, 0]
  }

  return fields.reduce<MatchScore | null>((best, field) => bestScore(best, rankField(trimmed, field)), null)
}

export function filterRankModels(query: string, models: string[]): RankedModel[] {
  const trimmed = query.trim()
  const rows = models
    .map((model, index): RankedModel | null => {
      const score: MatchScore | null = trimmed ? rankText(trimmed, [model]) : [0, 0, index]

      return score ? { index, model, score } : null
    })
    .filter((row): row is RankedModel => Boolean(row))

  if (!trimmed) {
    return rows.sort((a, b) => compareModelName(a.model, b.model) || a.index - b.index)
  }

  return rows.sort((a, b) => compareMatchScore(a.score, b.score) || compareModelName(a.model, b.model) || a.index - b.index)
}

export function filterRankProviders(query: string, providers: ModelOptionProvider[], labels: string[]): RankedProvider[] {
  const trimmed = query.trim()
  const rows = providers
    .map((provider, index): RankedProvider | null => {
      const label = labels[index] ?? provider.name
      const directFields = [label, provider.name, provider.slug, provider.warning ?? '']
      const directScore: MatchScore | null = trimmed ? rankText(trimmed, directFields) : [0, 0, 0]
      const modelRows = trimmed && provider.models?.length ? filterRankModels(trimmed, provider.models) : []
      const modelScore = modelRows[0]?.score ?? null
      const modelMatch = modelRows[0]?.model
      const boostedModelScore: MatchScore | null = modelScore ? [modelScore[0] + 1, modelScore[1], modelScore[2]] : null
      const score: MatchScore | null = trimmed ? bestScore(directScore, boostedModelScore) : directScore

      return score ? { index, label, modelMatch, provider, score } : null
    })
    .filter((row): row is RankedProvider => Boolean(row))

  return rows.sort((a, b) => compareMatchScore(a.score, b.score) || compareProviderPlan(a, b) || compareProviderRows(a, b))
}
