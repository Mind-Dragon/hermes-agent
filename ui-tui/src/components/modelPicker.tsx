import { Box, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useMemo, useState } from 'react'

import { providerDisplayNames } from '../domain/providers.js'
import { TUI_SESSION_MODEL_FLAG } from '../domain/slash.js'
import type { GatewayClient } from '../gatewayClient.js'
import type { ModelOptionProvider, ModelOptionsResponse } from '../gatewayTypes.js'
import { filterRankModels, filterRankProviders } from '../lib/modelPickerSearch.js'
import { selectedModelForEnter, selectedProviderForEnter, selectedProviderIndexForEnter } from '../lib/modelPickerSelection.js'
import { asRpcResult, rpcErrorMessage } from '../lib/rpc.js'
import type { Theme } from '../theme.js'

import { OverlayHint, useOverlayKeys, windowItems, windowOffset } from './overlayControls.js'

const VISIBLE = 12
const MIN_WIDTH = 40
const MAX_WIDTH = 90

type Stage = 'provider' | 'key' | 'model' | 'disconnect'

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
  const [stage, setStage] = useState<Stage>('provider')
  const [keyInput, setKeyInput] = useState('')
  const [keySaving, setKeySaving] = useState(false)
  const [keyError, setKeyError] = useState('')

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
  const selectedProviderRow = providerRows[providerFilteredIdx]
  const provider = providers[providerIdx] ?? selectedProviderRow?.provider
  const models = provider?.models ?? []
  const modelRows = useMemo(() => filterRankModels(query, models), [models, query])
  const modelFilteredIdx = Math.max(
    0,
    modelRows.findIndex(row => row.index === modelIdx)
  )

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
    if (stage === 'model' || stage === 'key' || stage === 'disconnect') {
      setStage('provider')
      setQuery('')
      setModelIdx(0)
      setKeyInput('')
      setKeyError('')
      setKeySaving(false)

      return
    }

    onCancel()
  }

  useOverlayKeys({ disabled: Boolean(query), onBack: back, onClose: onCancel })

  useInput((ch, key) => {
    // Key entry stage handles its own input
    if (stage === 'key') {
      if (keySaving) {
        return
      }

      if (key.return) {
        if (!keyInput.trim()) {
          return
        }

        setKeySaving(true)
        setKeyError('')
        gw.request<{ provider?: ModelOptionProvider }>('model.save_key', {
          slug: provider?.slug,
          api_key: keyInput.trim(),
          ...(sessionId ? { session_id: sessionId } : {}),
        })
          .then(raw => {
            const r = asRpcResult<{ provider?: ModelOptionProvider }>(raw)

            if (!r?.provider) {
              setKeyError('failed to save key')
              setKeySaving(false)

              return
            }

            // Update the provider in our list with fresh data
            setProviders(prev =>
              prev.map(p => p.slug === r.provider!.slug ? r.provider! : p)
            )
            setKeyInput('')
            setKeySaving(false)
            setStage('model')
            setModelIdx(0)
          })
          .catch((e: unknown) => {
            setKeyError(rpcErrorMessage(e))
            setKeySaving(false)
          })

        return
      }

      if (key.backspace || key.delete) {
        setKeyInput(v => v.slice(0, -1))

        return
      }

      // ctrl+u clears input
      if (ch === '\u0015') {
        setKeyInput('')

        return
      }

      if (ch && !key.ctrl && !key.meta) {
        setKeyInput(v => v + ch)
      }

      return
    }

    // Disconnect confirmation stage
    if (stage === 'disconnect') {
      if (ch.toLowerCase() === 'y' || key.return) {
        if (!provider) {
          setStage('provider')

          return
        }

        setKeySaving(true)
        gw.request<{ disconnected?: boolean }>('model.disconnect', {
          slug: provider.slug,
          ...(sessionId ? { session_id: sessionId } : {}),
        })
          .then(raw => {
            const r = asRpcResult<{ disconnected?: boolean }>(raw)

            if (r?.disconnected) {
              // Mark provider as unauthenticated in local state
              setProviders(prev =>
                prev.map(p => p.slug === provider.slug
                  ? { ...p, authenticated: false, models: [], total_models: 0, warning: p.key_env ? `paste ${p.key_env} to activate` : 'run `hermes model` to configure' }
                  : p
                )
              )
            }

            setKeySaving(false)
            setStage('provider')
          })
          .catch(() => {
            setKeySaving(false)
            setStage('provider')
          })

        return
      }

      if (ch.toLowerCase() === 'n' || key.escape) {
        setStage('provider')

        return
      }

      return
    }

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

    if ((key.ctrl && ch.toLowerCase() === 'g') || (!query && ch.toLowerCase() === 'g')) {
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
        const nextProvider = selectedProviderForEnter(providerRows, providerFilteredIdx)

        if (!nextProvider) {
          return
        }

        const selectedProviderIndex = selectedProviderIndexForEnter(providerRows, providerFilteredIdx, providerIdx)

        if (nextProvider.authenticated === false) {
          setProviderIdx(selectedProviderIndex)
          // api_key providers: prompt for key inline
          if (nextProvider.auth_type === 'api_key' && nextProvider.key_env) {
            setStage('key')
            setKeyInput('')
            setKeyError('')
          }

          // Other auth types: no-op (warning shown tells them to run hermes model)
          return
        }

        setProviderIdx(selectedProviderIndex)
        setStage('model')
        setQuery('')
        setModelIdx(0)

        return
      }

      const model = selectedModelForEnter(modelRows, modelFilteredIdx)

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

    // Disconnect: only in provider stage, only for authenticated providers
    if (ch.toLowerCase() === 'd' && stage === 'provider' && provider?.authenticated !== false) {
      setStage('disconnect')

      return
    }

    const n = ch === '0' ? 10 : Number(ch)

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
        <Text color={t.color.muted}>no providers available</Text>
        <OverlayHint t={t}>Esc/q cancel</OverlayHint>
      </Box>
    )
  }

  // ── Key entry stage ──────────────────────────────────────────────────
  if (stage === 'key' && provider) {
    const masked = keyInput ? '•'.repeat(Math.min(keyInput.length, 40)) : ''

    return (
      <Box flexDirection="column" width={width}>
        <Text bold color={t.color.accent} wrap="truncate-end">
          Configure {provider.name}
        </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          Paste your API key below (saved to ~/.hermes/.env)
        </Text>

        <Text color={t.color.muted} wrap="truncate-end"> </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          {provider.key_env}:
        </Text>

        <Text color={t.color.accent} wrap="truncate-end">
          {'  '}{masked || '(empty)'}{keySaving ? '' : '▎'}
        </Text>

        <Text color={t.color.muted} wrap="truncate-end"> </Text>

        {keyError ? (
          <Text color={t.color.label} wrap="truncate-end">
            error: {keyError}
          </Text>
        ) : keySaving ? (
          <Text color={t.color.muted} wrap="truncate-end">
            saving…
          </Text>
        ) : (
          <Text color={t.color.muted} wrap="truncate-end"> </Text>
        )}

        <OverlayHint t={t}>Enter save · Ctrl+U clear · Esc back</OverlayHint>
      </Box>
    )
  }

  // ── Disconnect confirmation stage ─────────────────────────────────────
  if (stage === 'disconnect' && provider) {
    return (
      <Box flexDirection="column" width={width}>
        <Text bold color={t.color.accent} wrap="truncate-end">
          Disconnect {provider.name}?
        </Text>

        <Text color={t.color.muted} wrap="truncate-end"> </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          This removes saved credentials for {provider.name}.
        </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          You can re-authenticate later by selecting it again.
        </Text>

        <Text color={t.color.muted} wrap="truncate-end"> </Text>

        {keySaving ? (
          <Text color={t.color.muted} wrap="truncate-end">disconnecting…</Text>
        ) : (
          <OverlayHint t={t}>y/Enter confirm · n/Esc cancel</OverlayHint>
        )}
      </Box>
    )
  }

  // ── Provider selection stage ─────────────────────────────────────────
  if (stage === 'provider') {
    const rows = providerRows.map(row => {
      const p = row.provider
      const authMark = p.authenticated === false ? '○' : p.is_current ? '*' : '●'
      const modelCount = p.total_models ?? p.models?.length ?? 0
      const suffix = p.authenticated === false
        ? (p.auth_type === 'api_key' ? '(no key)' : '(needs setup)')
        : `${modelCount} models`
      const modelMatch = row.modelMatch ? ` · ${row.modelMatch}` : ''

      return {
        row,
        text: `${authMark} ${row.label}${modelMatch} · ${suffix}`
      }
    })
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

          const idx = item.row.index
          const p = item.row.provider
          const dimmed = p.authenticated === false

          return (
            <Text
              bold={providerIdx === idx}
              color={providerIdx === idx ? t.color.accent : dimmed ? t.color.label : t.color.muted}
              inverse={providerIdx === idx}
              key={p.slug ?? `row-${idx}`}
              wrap="truncate-end"
            >
              {providerIdx === idx ? '▸ ' : '  '}
              {i + 1}. {item.text}
            </Text>
          )
        })}

        <Text color={t.color.muted} wrap="truncate-end">
          {offset + VISIBLE < rows.length ? ` ↓ ${rows.length - offset - VISIBLE} more` : ' '}
        </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          persist: {persistGlobal ? 'global' : 'session'} · g/Ctrl-G toggle
        </Text>
        <OverlayHint t={t}>
          {query ? 'type filter · Backspace edit · Esc/Ctrl-U clear · Enter choose' : '↑/↓ select · Enter choose · 1-9,0 quick · d disconnect · Esc/q cancel'}
        </OverlayHint>
      </Box>
    )
  }

  // ── Model selection stage ────────────────────────────────────────────
  const { items, offset } = windowItems(modelRows, modelFilteredIdx, VISIBLE)
  const matchText = query
    ? `Filter: ${query} · ${modelRows.length} match${modelRows.length === 1 ? '' : 'es'} · ${models.length} total`
    : `${names[providerIdx] || '(unknown provider)'} · Esc back`

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
        const item = items[i]

        if (!item) {
          return !models.length && i === 0 ? (
            <Text color={t.color.muted} key="empty" wrap="truncate-end">
              no models listed for this provider
            </Text>
          ) : !modelRows.length && i === 0 ? (
            <Text color={t.color.muted} key="empty-model-search" wrap="truncate-end">
              no matches
            </Text>
          ) : (
            <Text color={t.color.muted} key={`pad-${i}`} wrap="truncate-end">
              {' '}
            </Text>
          )
        }

        const idx = item.index
        const row = item.model
        const prefix = modelIdx === idx ? '▸ ' : row === currentModel ? '* ' : '  '

        return (
          <Text
            bold={modelIdx === idx}
            color={modelIdx === idx ? t.color.accent : t.color.muted}
            inverse={modelIdx === idx}
            key={`${provider?.slug ?? 'prov'}:${idx}:${row}`}
            wrap="truncate-end"
          >
            {prefix}
            {i + 1}. {row}
          </Text>
        )
      })}

      <Text color={t.color.muted} wrap="truncate-end">
        {offset + VISIBLE < modelRows.length ? ` ↓ ${modelRows.length - offset - VISIBLE} more` : ' '}
      </Text>

      <Text color={t.color.muted} wrap="truncate-end">
        persist: {persistGlobal ? 'global' : 'session'} · g/Ctrl-G toggle
      </Text>
      <OverlayHint t={t}>
        {query ? 'type filter · Backspace edit · Esc/Ctrl-U clear · Enter switch' : models.length ? '↑/↓ select · Enter switch · 1-9,0 quick · Esc back · q close' : 'Enter/Esc back · q close'}
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
