import { useCallback, useEffect, useRef, useState } from 'react'

/** One line of the example trace: what kind it is decides its colour and prefix. */
type Line = { kind: 'cmd' | 'out' | 'user' | 'think' | 'call' | 'back' | 'say'; text: string }

type Stage = {
  key: string
  name: string
  title: string
  text: string
  points: string[]
  icon: React.ReactNode
  trace: Line[]
}

const stroke = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round' } as const

// A worked example for Apple: a "why" question that needs both the numbers and the written 10-K.
// Figures match the sample ledger above; passage counts and quotes come from Apple's actual 10-K.
const STAGES: Stage[] = [
  {
    key: 'fetch',
    name: 'Fetch',
    title: 'Fetch the filing from SEC EDGAR',
    text: 'When you pick a company, the app looks up its latest annual report (10‑K) on SEC EDGAR and downloads two things: the financial statement pages and the main written document.',
    points: ['Ticker or name lookup against the SEC company list', 'Finds the income statement, balance sheet and cash flow pages', 'Nothing is typed in by hand, so figures match the filing'],
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path {...stroke} d="M6 3h8l4 4v14H6z" />
        <path {...stroke} d="M14 3v4h4M9 12h6M9 16h6" />
      </svg>
    ),
    trace: [
      { kind: 'cmd', text: 'open AAPL' },
      { kind: 'out', text: 'SEC EDGAR: Apple Inc., latest 10-K filed 2025-10-31' },
      { kind: 'out', text: 'statement pages found: income statement, balance sheet, cash flow' },
      { kind: 'out', text: 'main document: the full written 10-K' },
    ],
  },
  {
    key: 'load',
    name: 'Load',
    title: 'Turn the statements into a database',
    text: 'Each statement is cleaned up and loaded into an in-memory DuckDB database, with one row per line item per fiscal year, so it can be queried with SQL.',
    points: ['Bracketed negatives and units (millions, per share) are parsed', 'Segment breakdowns are kept separate from company-wide totals', 'Each browser tab gets its own private workspace'],
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <ellipse {...stroke} cx="12" cy="5.5" rx="7" ry="2.5" />
        <path {...stroke} d="M5 5.5v13c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-13M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5" />
      </svg>
    ),
    trace: [
      { kind: 'cmd', text: 'load statements into duckdb' },
      { kind: 'out', text: 'aapl_income_statement   fiscal years 2023, 2024, 2025' },
      { kind: 'out', text: 'aapl_balance_sheet      fiscal years 2024, 2025' },
      { kind: 'out', text: 'aapl_cash_flow          fiscal years 2023, 2024, 2025' },
      { kind: 'out', text: 'columns: line_item, section, segment, fiscal_year, value, units' },
    ],
  },
  {
    key: 'read',
    name: 'Read',
    title: 'Index the written sections',
    text: 'Numbers say what changed; the text says why. The app pulls the risk factors, management’s discussion (MD&A) and market risk sections out of the 10‑K, cuts them into short passages and builds a full-text search index.',
    points: [
      'Finds each section by its “Item 1A / 7 / 7A” heading, skipping the table of contents',
      'Page headers, footers and number tables are stripped out',
      'Searching runs locally in DuckDB, so it costs no AI tokens',
    ],
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path {...stroke} d="M5 4h9M5 8h9M5 12h5" />
        <circle {...stroke} cx="15" cy="15" r="4" />
        <path {...stroke} d="m18 18 3 3" />
      </svg>
    ),
    trace: [
      { kind: 'cmd', text: 'index written sections' },
      { kind: 'out', text: 'Risk factors   66 passages' },
      { kind: 'out', text: 'MD&A           38 passages' },
      { kind: 'out', text: 'Market risk     4 passages' },
      { kind: 'out', text: 'aapl_filing_text: 108 passages, full-text index ready' },
    ],
  },
  {
    key: 'plan',
    name: 'Plan',
    title: 'The language model plans the work',
    text: 'Your question goes to a large language model running on Groq, together with the recent conversation. It doesn’t answer from memory. It decides which tools to use to look the answer up.',
    points: ['Built with LangChain; temperature 0 for steady, repeatable answers', '“Why” questions get the numbers first, then the filing’s own explanation', 'If Groq is rate-limited, it waits and retries without losing progress'],
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect {...stroke} x="6" y="6" width="12" height="12" rx="2" />
        <path {...stroke} d="M10 10h4v4h-4zM9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" />
      </svg>
    ),
    trace: [
      { kind: 'user', text: 'Why did Apple’s margins improve in FY2025?' },
      { kind: 'think', text: 'first the numbers: margins are standard ratios, use financial_ratios' },
      { kind: 'think', text: 'then the reason: search the MD&A with search_filing' },
    ],
  },
  {
    key: 'tools',
    name: 'Use tools',
    title: 'It calls tools in a loop until it has the facts',
    text: 'The model calls tools, reads what comes back, and repeats until it has what it needs. If a query fails it reads the error, fixes it and tries again.',
    points: [
      'list_tables and find_line_items: see what’s loaded and the exact line names',
      'financial_ratios: margins, growth, ROE, ROA, debt-to-equity, free cash flow',
      'run_sql: read-only SQL for anything else; create_chart: draws a chart',
      'search_filing: the 3 best passages, trimmed to the sentences that matter',
    ],
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path {...stroke} d="M14.5 6.5a4 4 0 0 0-5.3 5L3.5 17.2a1.8 1.8 0 0 0 2.5 2.6l5.8-5.8a4 4 0 0 0 5-5.3l-2.4 2.4-2.3-.6-.6-2.3z" />
      </svg>
    ),
    trace: [
      { kind: 'call', text: 'financial_ratios(companies="aapl", ratios="operating_margin, net_margin")' },
      { kind: 'back', text: '6 rows, saved as table `ratios`' },
      { kind: 'call', text: 'search_filing(query="gross margin services products", section="MD&A")' },
      { kind: 'back', text: '3 passages: MD&A › Services Gross Margin, Products Gross Margin, …' },
    ],
  },
  {
    key: 'answer',
    name: 'Answer',
    title: 'You get an answer you can check',
    text: 'The model writes a short answer using only numbers from tool results and reasons quoted from the filing. The quoted passages appear under “From the 10‑K”, the queries under “How this was calculated”.',
    points: ['Every figure comes from the filing, never a guess', 'Reasons are quoted from management, never invented', 'If the filing doesn’t explain something, or the data can’t answer, it says so'],
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path {...stroke} d="M4 5h16v11H9l-5 4z" />
        <path {...stroke} d="m9 10.5 2 2 4-4" />
      </svg>
    ),
    trace: [
      { kind: 'say', text: 'Operating margin rose from 31.5% to 32.0%, and net margin from 24.0% to 26.9%.' },
      { kind: 'say', text: 'Apple says Services gross margin grew “primarily due to higher Services net sales and a different mix of services” (MD&A).' },
      { kind: 'out', text: '+ 2 quoted passages under “From the 10‑K”' },
      { kind: 'out', text: 'suggestions: How much did tariffs cost? | Compare with Microsoft' },
    ],
  },
]

const PREFIX: Record<Line['kind'], string> = {
  cmd: '$', out: '', user: 'you', think: 'plan', call: 'tool', back: '←', say: 'edgar',
}

const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

/** Types the trace out line by line; `done` turns true when the last line is complete.
 *  Mount it with a key per stage so each stage starts from an empty terminal. */
function useTrace(lines: Line[], running: boolean) {
  const total = lines.reduce((n, l) => n + l.text.length, 0)
  const [chars, setChars] = useState(() => (reducedMotion() ? total : 0))
  useEffect(() => {
    if (!running || chars >= total) return
    const t = setTimeout(() => setChars((c) => Math.min(total, c + 2)), 14)
    return () => clearTimeout(t)
  }, [chars, total, running])

  let left = chars
  const shown = lines.map((l) => {
    const take = Math.max(0, Math.min(l.text.length, left))
    left -= l.text.length
    return { ...l, text: l.text.slice(0, take) }
  })
  // Lines that haven't started yet stay hidden (the first one shows, so the caret has a home).
  const visible = shown.filter((l, i) => l.text.length > 0 || i === 0)
  return { visible, done: chars >= total }
}

function Terminal({ stage, step, running, onDone }: { stage: Stage; step: number; running: boolean; onDone: () => void }) {
  const { visible, done } = useTrace(stage.trace, running)
  useEffect(() => {
    if (done) onDone()
  }, [done, onDone])
  return (
    <div className="terminal" aria-label={`Example: ${stage.name} step for Apple`}>
      <div className="terminal-bar" aria-hidden="true">
        <i /><i /><i />
        <span>edgar.ai trace: apple</span>
      </div>
      <div className="terminal-body">
        {visible.map((l, i) => (
          <p key={i} className={`t-line t-${l.kind}`}>
            <span className="t-prefix">{PREFIX[l.kind]}</span>
            <span>
              {l.text}
              {!done && i === visible.length - 1 && <span className="caret" aria-hidden="true" />}
            </span>
          </p>
        ))}
        {done && <p className="t-line t-done"><span className="t-prefix">✓</span><span>step {step} of {STAGES.length} complete</span></p>}
      </div>
    </div>
  )
}

/** "Inside the agent": the five stages from filing to answer, with a worked example trace. */
export function AgentFlow() {
  const [active, setActive] = useState(0)
  const [auto, setAuto] = useState(true)
  const [inView, setInView] = useState(false)
  const ref = useRef<HTMLElement>(null)
  const [done, setDone] = useState(false)
  const stage = STAGES[active]
  const onDone = useCallback(() => setDone(true), [])

  // Only start once the section is on screen.
  useEffect(() => {
    const el = ref.current
    if (!el || !('IntersectionObserver' in window)) return setInView(true)
    const io = new IntersectionObserver(([e]) => setInView(e.isIntersecting), { threshold: 0.35 })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  // Autoplay: move to the next stage a moment after its trace finishes.
  useEffect(() => {
    if (!auto || !done || !inView || reducedMotion()) return
    const t = setTimeout(() => setActive((a) => (a + 1) % STAGES.length), 2600)
    return () => clearTimeout(t)
  }, [auto, done, inView, active])

  useEffect(() => setDone(false), [active])

  const choose = (i: number) => {
    setActive(i)
    setAuto(false)
  }

  return (
    <section ref={ref} id="agent" className="agent-flow hud" aria-labelledby="agent-heading">
      <div className="agent-flow-head">
        <div>
          <span className="kicker">Inside the agent</span>
          <h2 id="agent-heading">From filing to answer in six steps</h2>
        </div>
        <button className="secondary" onClick={() => setAuto((a) => !a)} aria-pressed={auto}>
          {auto ? 'Pause tour' : 'Play tour'}
        </button>
      </div>

      <ol className="rail" style={{ '--progress': active / (STAGES.length - 1) } as React.CSSProperties}>
        {STAGES.map((s, i) => (
          <li key={s.key}>
            <button
              className={['node', i === active && 'active', i < active && 'passed'].filter(Boolean).join(' ')}
              aria-current={i === active ? 'step' : undefined}
              onClick={() => choose(i)}
            >
              <span className="node-icon">{s.icon}</span>
              <span className="node-label">
                <span className="node-number">{String(i + 1).padStart(2, '0')}</span>
                {s.name}
              </span>
            </button>
          </li>
        ))}
      </ol>

      <div className="stage" key={stage.key}>
        <div className="stage-copy">
          <h3>{stage.title}</h3>
          <p>{stage.text}</p>
          <ul>
            {stage.points.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>

        <Terminal key={stage.key} stage={stage} step={active + 1} running={inView} onDone={onDone} />
      </div>
    </section>
  )
}
