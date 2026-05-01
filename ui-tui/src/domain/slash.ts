/** Appended to `/model` args from the TUI picker for session scope; stripped in `session` slash before `config.set`. */
export const TUI_SESSION_MODEL_FLAG = '--tui-session'

const TUI_SESSION_MODEL_RE = new RegExp(`(?:^|\\s)${TUI_SESSION_MODEL_FLAG}(?:\\s|$)`)
const TUI_SESSION_STRIP_RE = new RegExp(`\\s*${TUI_SESSION_MODEL_FLAG}\\b\\s*`, 'g')

const stripTuiSessionFlag = (trimmed: string) => trimmed.replace(TUI_SESSION_STRIP_RE, ' ').replace(/\s+/g, ' ').trim()

export const modelValueForConfigSet = (arg: string) => {
  const trimmed = arg.trim()

  if (!trimmed) {
    return trimmed
  }

  if (TUI_SESSION_MODEL_RE.test(trimmed)) {
    return stripTuiSessionFlag(trimmed)
  }

  return trimmed
}

export const looksLikeSlashCommand = (text: string) => /^\/[^\s/]*(?:\s|$)/.test(text)

export const parseSlashCommand = (cmd: string) => {
  const [name = '', ...rest] = cmd.slice(1).split(/\s+/)

  return { arg: rest.join(' '), cmd, name: name.toLowerCase() }
}
