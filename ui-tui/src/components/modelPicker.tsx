import { Box, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useMemo, useState } from 'react'

import { providerDisplayNames } from '../domain/providers.js'
import { TUI_SESSION_MODEL_FLAG } from '../domain/slash.js'
import type { GatewayClient } from '../gatewayClient.js'
import type { ModelOptionProvider, ModelOptionsResponse } from '../gatewayTypes.js'
import { asRpcResult, rpcErrorMessage } from '../lib/rpc.js'
import { filterRankModels, filterRankProviders } from '../lib/modelPickerSearch.js'
import type { RankedModel } from '../lib/modelPickerSearch.js'
import type { Theme } from '../theme.js'

import { OverlayHint, useOverlayKeys, windowItems, windowOffset } from './overlayControls.js'

const VISIBLE = 12
const MIN_WIDTH = 40
const MAX_WIDTH = 90

const isPrintableSearchText = (ch: string) => ch.length > 0 && Array.from(ch).every(c => c >= ' ' && c !== '\u007F')

export function ModelPicker({ gw, onCancel, onSelect, sessionId, t }: ModelPickerProps) {
  const [providers, setProviders] = useState<ModelOptionProvider[]>([])
  const [currentModel, setCurrentModel] = useState('')
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)
  const [persistGlobal, setPersistGlobal] = useState(false)
  const [providerIdx, setProviderIdx] = useState(0)
  const [modelIdx, setModelIdx] = useState(0)
  const [query, setQuery] = useState('')
  const [stage, setStage] = useState<'model' | 'provider'>('provider')

  const { stdout } = useStdout()
  // Pin the picker to a stable width so the FloatBox parent (which shrinks-
  // to-fit with alignSelf="flex-start") doesn't resize as long provider /
  // model names scroll into view, and so `wrap="truncate-end"` on each row
  // has an actual constraint to truncate against.
  const width = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, (stdout?.columns ?? 80) - 6))

  useEffect(() => {
    gw.request<ModelOptionsResponse>('model.options', sessionId ? { session_id: sessionId } : {})
      .then(raw => {
        const r = asRpcResult<ModelOptionsResponse>(raw)

        if (!r) {
          setErr('invalid response: model.options')
          setLoading(false)

          return
        }

        const next = r.providers ?? []
        setProviders(next)
        setCurrentModel(String(r.model ?? ''))
        setProviderIdx(
          Math.max(
            0,
            next.findIndex(p => p.is_current)
          )
        )
        setModelIdx(0)
        setQuery('')
        setStage('provider')
        setErr('')
        setLoading(false)
      })
      .catch((e: unknown) => {
        setErr(rpcErrorMessage(e))
        setLoading(false)
      })
  }, [gw, sessionId])

  const names = useMemo(() => providerDisplayNames(providers), [providers])
  const providerRows = useMemo(() => filterRankProviders(query, providers, names), [names, providers, query])
  const providerFilteredIdx = Math.max(
    0,
    providerRows.findIndex(row => row.index === providerIdx)
  )
  const provider = providers[providerIdx] ?? providerRows[providerFilteredIdx]?.provider
  const models = provider?.models ?? []
  const modelRows = useMemo(() => filterRankModels(query, models), [models, query])
  const modelFilteredIdx = Math.max(
    0,
    modelRows.findIndex(row => row.index === modelIdx)
  )
  const selectedProviderRow = providerRows[providerFilteredIdx]

  useEffect(() => {
    if (!query || stage !== 'provider') {
      return
    }

    setProviderIdx(providerRows[0]?.index ?? 0)
  }, [providerRows, query, stage])

  useEffect(() => {
    if (!query || stage !== 'model') {
      return
    }

    setModelIdx(modelRows[0]?.index ?? 0)
  }, [modelRows, query, stage])

  useEffect(() => {
    if (stage !== 'provider') {
      return
    }

    if (!providerRows.length) {
      setProviderIdx(0)

      return
    }

    if (!providerRows.some(row => row.index === providerIdx)) {
      setProviderIdx(providerRows[0]!.index)
    }
  }, [providerIdx, providerRows, stage])

  useEffect(() => {
    if (stage !== 'model') {
      return
    }

    if (!modelRows.length) {
      setModelIdx(0)

      return
    }

    if (!modelRows.some(row => row.index === modelIdx)) {
      setModelIdx(modelRows[0]!.index)
    }
  }, [modelIdx, modelRows, stage])

  const back = () => {
    if (stage === 'model') {
      setStage('provider')
      setQuery('')
      setModelIdx(0)

      return
    }

    onCancel()
  }

  useOverlayKeys({ disabled: Boolean(query), onBack: back, onClose: onCancel })

  useInput((ch, key) => {
    if (key.escape) {
      if (query) {
        setQuery('')
        setProviderIdx(providerRows[0]?.index ?? 0)
        setModelIdx(modelRows[0]?.index ?? 0)
      }

      return
    }

    if (key.backspace || key.delete) {
      if (query) {
        setQuery(v => v.slice(0, -1))
      }

      return
    }

    if (key.ctrl && ch.toLowerCase() === 'u') {
      setQuery('')

      return
    }

    if (key.ctrl && ch.toLowerCase() === 'g') {
      setPersistGlobal(v => !v)

      return
    }

    const rows = stage === 'provider' ? providerRows : modelRows
    const cursor = stage === 'provider' ? providerFilteredIdx : modelFilteredIdx

    if (key.upArrow && cursor > 0) {
      const next = rows[cursor - 1]

      if (next) {
        stage === 'provider' ? setProviderIdx(next.index) : setModelIdx(next.index)
      }

      return
    }

    if (key.downArrow && cursor < rows.length - 1) {
      const next = rows[cursor + 1]

      if (next) {
        stage === 'provider' ? setProviderIdx(next.index) : setModelIdx(next.index)
      }

      return
    }

    if (key.return) {
      if (stage === 'provider') {
        const nextProvider = providers[providerIdx] ?? selectedProviderRow?.provider

        if (!nextProvider) {
          return
        }

        setStage('model')
        setQuery('')
        setModelIdx(0)

        return
      }

      const model = models[modelIdx]

      if (provider && model) {
        onSelect(`${model} --provider ${provider.slug}${persistGlobal ? ' --global' : ` ${TUI_SESSION_MODEL_FLAG}`}`)
      } else {
        setStage('provider')
        setQuery('')
      }

      return
    }

    if (!query && ch === 'q') {
      return
    }

    const n = ch === '0' ? 10 : parseInt(ch, 10)

    if (!query && !Number.isNaN(n) && n >= 1 && n <= Math.min(10, rows.length)) {
      const offset = windowOffset(rows.length, cursor, VISIBLE)
      const next = rows[offset + n - 1]

      if (!next) {
        return
      }

      if (stage === 'provider') {
        setProviderIdx(next.index)
      } else if (provider) {
        const model = models[next.index]

        if (model) {
          onSelect(`${model} --provider ${provider.slug}${persistGlobal ? ' --global' : ` ${TUI_SESSION_MODEL_FLAG}`}`)
        }
      }

      return
    }

    if (!key.ctrl && !key.meta && !key.super && isPrintableSearchText(ch)) {
      setQuery(v => v + ch)

      if (stage === 'provider') {
        setProviderIdx(0)
      } else {
        setModelIdx(0)
      }
    }
  })

  if (loading) {
    return <Text color={t.color.muted}>loading models…</Text>
  }

  if (err) {
    return (
      <Box flexDirection="column">
        <Text color={t.color.label}>error: {err}</Text>
        <OverlayHint t={t}>Esc/q cancel</OverlayHint>
      </Box>
    )
  }

  if (!providers.length) {
    return (
      <Box flexDirection="column">
        <Text color={t.color.muted}>no authenticated providers</Text>
        <OverlayHint t={t}>Esc/q cancel</OverlayHint>
      </Box>
    )
  }

  if (stage === 'provider') {
    const rows = providerRows.map(row => ({
      row,
      text: `${row.provider.is_current ? '*' : ' '} ${row.label} · ${row.provider.total_models ?? row.provider.models?.length ?? 0} models`
    }))
    const { items, offset } = windowItems(rows, providerFilteredIdx, VISIBLE)
    const matchText = query ? `Filter: ${query} · ${providerRows.length} match${providerRows.length === 1 ? '' : 'es'}` : 'Type to filter · Enter to continue'

    return (
      <Box flexDirection="column" width={width}>
        <Text bold color={t.color.accent} wrap="truncate-end">
          Select provider (step 1/2)
        </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          {matchText}
        </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          Current: {currentModel || '(unknown)'}
        </Text>
        <Text color={t.color.label} wrap="truncate-end">
          {provider?.warning ? `warning: ${provider.warning}` : ' '}
        </Text>
        <Text color={t.color.muted} wrap="truncate-end">
          {offset > 0 ? ` ↑ ${offset} more` : ' '}
        </Text>

        {Array.from({ length: VISIBLE }, (_, i) => {
          const item = items[i]
          const idx = offset + i

          if (!item) {
            return !providerRows.length && i === 0 ? (
              <Text color={t.color.muted} key="empty-provider-search" wrap="truncate-end">
                no matches
              </Text>
            ) : (
              <Text color={t.color.muted} key={`pad-${i}`} wrap="truncate-end">
                {' '}
              </Text>
            )
          }

          return (
            <Text
              bold={providerFilteredIdx === idx}
              color={providerFilteredIdx === idx ? t.color.accent : t.color.muted}
              inverse={providerFilteredIdx === idx}
              key={`${item.row.provider.slug}:${item.row.index}`}
              wrap="truncate-end"
            >
              {providerFilteredIdx === idx ? '▸ ' : '  '}
              {i + 1}. {item.text}
            </Text>
          )
        })}

        <Text color={t.color.muted} wrap="truncate-end">
          {offset + VISIBLE < rows.length ? ` ↓ ${rows.length - offset - VISIBLE} more` : ' '}
        </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          persist: {persistGlobal ? 'global' : 'session'} · Ctrl-G toggle
        </Text>
        <OverlayHint t={t}>
          {query ? 'type filter · Backspace edit · Esc/Ctrl-U clear · Enter choose' : '↑/↓ select · Enter choose · 1-9,0 quick · Ctrl-G persist · Esc/q cancel'}
        </OverlayHint>
      </Box>
    )
  }

  const { items, offset } = windowItems(modelRows, modelFilteredIdx, VISIBLE)
  const selectedProviderLabel = selectedProviderRow?.label ?? names[providerIdx] ?? provider?.name ?? '(unknown provider)'
  const matchText = query
    ? `Filter: ${query} · ${modelRows.length} match${modelRows.length === 1 ? '' : 'es'} · ${models.length} total`
    : `${selectedProviderLabel} · Type to filter · Esc back`

  return (
    <Box flexDirection="column" width={width}>
      <Text bold color={t.color.accent} wrap="truncate-end">
        Select model (step 2/2)
      </Text>

      <Text color={t.color.muted} wrap="truncate-end">
        {matchText}
      </Text>
      <Text color={t.color.label} wrap="truncate-end">
        {provider?.warning ? `warning: ${provider.warning}` : ' '}
      </Text>
      <Text color={t.color.muted} wrap="truncate-end">
        {offset > 0 ? ` ↑ ${offset} more` : ' '}
      </Text>

      {Array.from({ length: VISIBLE }, (_, i) => {
        const row = items[i] as RankedModel | undefined
        const idx = offset + i

        if (!row) {
          return !modelRows.length && i === 0 ? (
            <Text color={t.color.muted} key="empty" wrap="truncate-end">
              {models.length ? 'no matches' : 'no models listed for this provider'}
            </Text>
          ) : (
            <Text color={t.color.muted} key={`pad-${i}`} wrap="truncate-end">
              {' '}
            </Text>
          )
        }

        const prefix = modelFilteredIdx === idx ? '▸ ' : row.model === currentModel ? '* ' : '  '

        return (
          <Text
            bold={modelFilteredIdx === idx}
            color={modelFilteredIdx === idx ? t.color.accent : t.color.muted}
            inverse={modelFilteredIdx === idx}
            key={`${provider?.slug ?? 'prov'}:${row.index}:${row.model}`}
            wrap="truncate-end"
          >
            {prefix}
            {i + 1}. {row.model}
          </Text>
        )
      })}

      <Text color={t.color.muted} wrap="truncate-end">
        {offset + VISIBLE < modelRows.length ? ` ↓ ${modelRows.length - offset - VISIBLE} more` : ' '}
      </Text>

      <Text color={t.color.muted} wrap="truncate-end">
        persist: {persistGlobal ? 'global' : 'session'} · Ctrl-G toggle
      </Text>
      <OverlayHint t={t}>
        {query
          ? 'type filter · Backspace edit · Esc/Ctrl-U clear · Enter switch'
          : models.length
            ? '↑/↓ select · Enter switch · 1-9,0 quick · Ctrl-G persist · Esc back · q close'
            : 'Enter/Esc back · q close'}
      </OverlayHint>
    </Box>
  )
}

interface ModelPickerProps {
  gw: GatewayClient
  onCancel: () => void
  onSelect: (value: string) => void
  sessionId: string | null
  t: Theme
}
