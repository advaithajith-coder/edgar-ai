import type { Company, Turn } from '../api'
import { CompanyPicker } from '../components/CompanyPicker'
import { Conversation } from '../components/Conversation'
import { Ledger } from '../components/Ledger'
import { Statements } from '../components/Statements'
import { Wordmark } from '../components/Wordmark'
import { longDate } from '../format'

type Props = {
  navigate: (to: string) => void
  company: Company | null
  turns: Turn[]
  hasKey: boolean
  busy: boolean
  error: string
  onTurn: (turn: Turn) => void
  onClearChat: () => void
}

export function Report(p: Props) {
  const open = (ticker: string) => p.navigate(`/report?company=${encodeURIComponent(ticker)}`)

  return (
    <div className="desk">
      <main className="paper">
        <div className="report-bar">
          <Wordmark onHome={() => p.navigate('/')} />
          {p.company && <CompanyPicker label="Open another company" onSelect={open} busy={p.busy} />}
        </div>

        {p.error && <p className="error" role="alert">{p.error}</p>}

        {p.company ? (
          <>
            <header className="company-head">
              <span className="ticker-chip">{p.company.ticker}</span>
              <h1 className="company-name">{p.company.name}</h1>
              <p className="filing">
                Annual report (10‑K) for the fiscal year ended {longDate(p.company.period)}, filed{' '}
                {longDate(p.company.filed)}.{' '}
                <a href={p.company.url} target="_blank" rel="noreferrer">Open the filing on SEC.gov</a>
              </p>
            </header>
            <Ledger company={p.company} />
            <Statements company={p.company} key={p.company.ticker} />
          </>
        ) : (
          <section className="choose" aria-labelledby="choose-heading">
            <h1 id="choose-heading" className="company-name">
              {p.busy ? 'Opening the report…' : 'Choose a company'}
            </h1>
            {!p.busy && (
              <>
                <p className="lede">Pick a US-listed company to open its latest annual report.</p>
                <CompanyPicker label="Company" large onSelect={open} />
              </>
            )}
          </section>
        )}
      </main>

      <Conversation
        subject={p.company?.shortName ?? null}
        ready={!!p.company}
        hasKey={p.hasKey}
        starters={p.company?.starters ?? []}
        turns={p.turns}
        onTurn={p.onTurn}
        onClear={p.onClearChat}
      />
    </div>
  )
}
