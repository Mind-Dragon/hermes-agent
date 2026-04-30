type ProviderRow = {
  index: number
  provider: { slug: string }
}

type ModelRow = {
  index: number
  model: string
}

export const selectedProviderForEnter = (rows: ProviderRow[], filteredIdx: number) => rows[filteredIdx]?.provider ?? null

export const selectedProviderIndexForEnter = (rows: ProviderRow[], filteredIdx: number, fallbackIndex: number) =>
  rows[filteredIdx]?.index ?? fallbackIndex

export const selectedModelForEnter = (rows: ModelRow[], filteredIdx: number) => rows[filteredIdx]?.model ?? null
