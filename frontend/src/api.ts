// Talks to the Python backend (server.py). Each browser tab gets its own workspace id.

export type LedgerLine = { label: string; kind: 'money' | 'pct'; values: Record<string, number> }
export type Company = {
  ticker: string
  name: string
  shortName: string
  period: string
  filed: string
  url: string
  ledger: { years: string[]; lines: LedgerLine[] }
  starters: string[]
  statements: { key: string; title: string }[]
}
export type StatementRow = {
  label: string
  heading: boolean
  indent: boolean
  total?: boolean
  values: Record<string, number>
}
export type Statement = { years: string[]; rows: StatementRow[]; unitsNote: string }
/** A passage from the 10-K's written sections that an answer quoted. */
export type Source = { company: string; section: string; heading: string; text: string }
export type Turn = {
  question: string
  answer: string
  suggestions: string[]
  steps: string[]
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  figures: any[]
  sources?: Source[]
  error?: boolean
}
export type Workspace = { company: Company | null; turns: Turn[]; hasKey: boolean }
export type Progress =
  | { type: 'status'; text: string }
  | { type: 'wait'; seconds: number; attempt: number; of: number; reason: string }

function sessionId(): string {
  const key = 'analyst-workspace'
  let id = sessionStorage.getItem(key)
  if (!id) {
    id = crypto.randomUUID()
    sessionStorage.setItem(key, id)
  }
  return id
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('X-Session', sessionId())
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const res = await fetch(path, { ...init, headers })
  if (!res.ok) throw new Error(await errorText(res))
  return res.json() as Promise<T>
}

async function errorText(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') return body.detail
  } catch {
    /* not JSON */
  }
  return res.status === 502 || res.status === 504
    ? 'The app’s server isn’t running. Start it with: uvicorn server:app --port 8010'
    : `The server returned an error (${res.status}).`
}

export type CompanyOption = { ticker: string; name: string }

export const api = {
  workspace: () => request<Workspace>('/api/workspace'),
  searchCompanies: (q: string) => request<CompanyOption[]>(`/api/companies?q=${encodeURIComponent(q)}`),
  loadCompany: (ticker: string) =>
    request<Company>('/api/company', { method: 'POST', body: JSON.stringify({ ticker }) }),
  removeCompany: () => request('/api/company', { method: 'DELETE' }),
  statement: (key: string, segments: boolean) =>
    request<Statement>(`/api/statement/${key}?segments=${segments}`),
  clearChat: () => request('/api/clear', { method: 'POST' }),

  /** Ask a question; progress events arrive while the agent works, then the finished turn. */
  async ask(question: string, onProgress: (p: Progress) => void): Promise<Turn> {
    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Session': sessionId() },
      body: JSON.stringify({ question }),
    })
    if (!res.ok || !res.body) throw new Error(await errorText(res))
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines.filter(Boolean)) {
        const event = JSON.parse(line)
        if (event.type === 'answer') return event as Turn
        onProgress(event)
      }
      if (done) throw new Error('The answer was cut off. Ask again.')
    }
  },
}
