import type { Company } from '../api'
import { CompanyPicker } from '../components/CompanyPicker'
import { AgentFlow } from '../components/AgentFlow'
import { Ledger } from '../components/Ledger'
import { Robot, TypeLoop } from '../components/Robot'
import { Wordmark } from '../components/Wordmark'

// A real example of the ledger the report page opens with (Apple's FY2023–2025 10-K figures, $ millions).
const REVENUE = { 2023: 383285, 2024: 391035, 2025: 416161 }
const NET_INCOME = { 2023: 96995, 2024: 93736, 2025: 112010 }
const NET_MARGIN = Object.fromEntries(
  Object.entries(REVENUE).map(([y, r]) => [y, (100 * NET_INCOME[y as unknown as keyof typeof NET_INCOME]) / r]),
)
const SPECIMEN: Company = {
  ticker: 'AAPL-example',
  name: 'Apple Inc.',
  shortName: 'Apple',
  period: '',
  filed: '',
  url: '',
  starters: [],
  statements: [],
  ledger: {
    years: ['2023', '2024', '2025'],
    lines: [
      { label: 'Revenue', kind: 'money', values: REVENUE },
      { label: 'Net income', kind: 'money', values: NET_INCOME },
      { label: 'Net margin', kind: 'pct', values: NET_MARGIN },
      { label: 'Free cash flow', kind: 'money', values: { 2023: 99584, 2024: 108807, 2025: 98767 } },
    ],
  },
}

const STEPS = [
  { title: 'Choose a company', text: 'Pick any US-listed company. The app fetches its latest annual report (10‑K) from SEC EDGAR.' },
  { title: 'Read the key figures', text: 'Revenue, profit, margins and cash flow across the years, with the full statements a click away.' },
  { title: 'Ask questions', text: 'Ask in plain English and get answers with charts. Every answer shows how it was calculated.' },
]

// What the robot says on the home screen, one after another.
const GREETINGS = [
  'Hi! I’m EDGAR.AI, your annual report analyst.',
  'Try: “How did Apple’s margins change?”',
  'Try: “Chart Nvidia’s revenue growth.”',
  'I show the working behind every answer.',
  'Pick a company to get started.',
]

type Props = {
  navigate: (to: string) => void
  current: Company | null // a company already open in this tab, if any
}

export function Home({ navigate, current }: Props) {
  const open = (ticker: string) => navigate(`/report?company=${encodeURIComponent(ticker)}`)

  return (
    <div className="home">
      <header className="home-bar">
        <Wordmark onHome={() => navigate('/')} />
        <nav className="home-nav">
          <a href="#agent">How the agent works</a>
          <span className="status">Connected to SEC EDGAR</span>
        </nav>
      </header>

      <main>
        <section className="hero" aria-labelledby="hero-heading">
          <div className="hero-copy">
            <span className="kicker">AI agent for 10‑K annual reports</span>
            <h1 id="hero-heading" className="hero-title">
              Ask questions of any US company’s <span className="glow-text">annual report</span>
            </h1>
            <p className="lede">
              Pick a company and the agent reads its latest 10‑K, lays out the key figures, and answers your
              questions with charts and the working behind them.
            </p>
            <CompanyPicker label="Company" large onSelect={open} />
            {current && (
              <p className="note">
                <a href={`/report?company=${current.ticker}`} onClick={(e) => { e.preventDefault(); open(current.ticker) }}>
                  Continue with {current.name}
                </a>
              </p>
            )}
          </div>

          <div className="hero-bot">
            <TypeLoop className="bubble" phrases={GREETINGS} />
            <Robot size={260} track greet mood="idle" />
          </div>
        </section>

        <section className="preview hud" aria-labelledby="preview-heading">
          <div className="preview-head">
            <h2 id="preview-heading" className="kicker">Sample output: Apple, FY2023 to FY2025</h2>
            <span className="note">What a report opens with, from Apple’s latest 10‑K</span>
          </div>
          <figure className="specimen">
            <Ledger company={SPECIMEN} />
          </figure>
        </section>

        <section className="steps-section" aria-labelledby="how-heading">
          <h2 id="how-heading">Using it</h2>
          <ol className="how">
            {STEPS.map((s, i) => (
              <li key={s.title} className="hud">
                <span className="how-number" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span>
                <h3>{s.title}</h3>
                <p>{s.text}</p>
              </li>
            ))}
          </ol>
        </section>
        <AgentFlow />
      </main>
    </div>
  )
}
