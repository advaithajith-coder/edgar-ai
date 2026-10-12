import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, type Progress, type Turn } from '../api'
import { Robot, type Mood } from './Robot'

// Plotly is large, so it's only downloaded when the first chart appears.
const Chart = lazy(() => import('./Chart'))

type Props = {
  subject: string | null // company short name, or null before a company is loaded
  ready: boolean // something is loaded to ask about
  hasKey: boolean
  starters: string[]
  turns: Turn[]
  onTurn: (turn: Turn) => void
  onClear: () => void
}

function progressText(p: Progress | null): string {
  if (!p) return 'Reading the question'
  if (p.type === 'status') return p.text
  return `${p.reason}. Retrying in ${p.seconds} s (attempt ${p.attempt} of ${p.of}).`
}

const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

/** Reveals text a few words at a time, like it's being typed. Returns the visible part. */
function useTypewriter(text: string, active: boolean, onTick: () => void) {
  const [shown, setShown] = useState(active && !reducedMotion() ? 0 : text.length)
  useEffect(() => {
    if (shown >= text.length) return
    // Finish in about 1.6 s whatever the length.
    const step = Math.max(3, Math.ceil(text.length / 80))
    const t = setTimeout(() => {
      setShown((n) => Math.min(text.length, n + step))
      onTick()
    }, 20)
    return () => clearTimeout(t)
  }, [shown, text, onTick])
  return { visible: text.slice(0, shown), done: shown >= text.length, skip: () => setShown(text.length) }
}

function Answer({
  turn,
  latest,
  fresh,
  onAsk,
  onTick,
}: {
  turn: Turn
  latest: boolean
  fresh: boolean
  onAsk: (q: string) => void
  onTick: () => void
}) {
  const { visible, done, skip } = useTypewriter(turn.answer, fresh, onTick)
  return (
    <div className="reply">
      <Robot headOnly decorative size={36} mood={turn.error ? 'error' : 'idle'} />
      <article className={turn.error ? 'answer failed' : 'answer'} onClick={done ? undefined : skip}>
        <div className={done ? 'markdown' : 'markdown typing-cursor'}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{visible}</ReactMarkdown>
        </div>
        {done && (
          <>
            {turn.figures.map((f, i) => (
              <Suspense key={i} fallback={<div className="chart" aria-busy="true" />}>
                <Chart figure={f} />
              </Suspense>
            ))}
            {turn.steps.length > 0 && (
              <details className="steps">
                <summary>How this was calculated</summary>
                {turn.steps.map((s, i) => (
                  <pre key={i}>
                    <code>{s}</code>
                  </pre>
                ))}
              </details>
            )}
            {turn.sources && turn.sources.length > 0 && (
              <details className="steps sources" open>
                <summary>From the 10‑K ({turn.sources.length} {turn.sources.length === 1 ? 'passage' : 'passages'})</summary>
                {turn.sources.map((s, i) => (
                  <blockquote key={i}>
                    <p>{s.text}</p>
                    <cite>{[s.section, s.heading].filter(Boolean).join(' › ')}</cite>
                  </blockquote>
                ))}
              </details>
            )}
            {latest && turn.suggestions.length > 0 && (
              <div className="suggestions" aria-label="Follow-up questions">
                {turn.suggestions.map((s, i) => (
                  <button key={s} className="suggestion" style={{ '--i': i } as React.CSSProperties} onClick={() => onAsk(s)}>
                    {s}
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </article>
    </div>
  )
}

export function Conversation({ subject, ready, hasKey, starters, turns, onTurn, onClear }: Props) {
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<string | null>(null)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [fresh, setFresh] = useState(-1) // index of the answer that arrived in this visit, typed out
  const [reaction, setReaction] = useState<Mood | null>(null) // a short-lived mood after an answer
  const endRef = useRef<HTMLDivElement>(null)
  // Braces matter: newer browsers make scrollIntoView return a Promise, which React would
  // mistake for an effect cleanup function and crash on.
  const scroll = useRef(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }).current

  useEffect(scroll, [turns.length, pending, scroll])

  useEffect(() => {
    if (!reaction) return
    const t = setTimeout(() => setReaction(null), 2400)
    return () => clearTimeout(t)
  }, [reaction])

  async function ask(question: string) {
    const q = question.trim()
    if (!q || pending) return
    setDraft('')
    setPending(q)
    setProgress(null)
    let turn: Turn
    try {
      turn = await api.ask(q, setProgress)
    } catch (e) {
      turn = { question: q, answer: (e as Error).message, suggestions: [], steps: [], figures: [], error: true }
    }
    setFresh(turns.length)
    setReaction(turn.error ? 'error' : 'happy')
    onTurn(turn)
    setPending(null)
  }

  const mood: Mood = pending ? 'thinking' : reaction ?? (draft.trim() ? 'listening' : 'idle')
  const status = pending ? 'Thinking…' : !ready ? 'Waiting for a company' : hasKey ? `Online, reading ${subject ?? 'the'}’s 10‑K` : 'Missing API key'

  return (
    <section className="conversation" aria-labelledby="conversation-heading">
      <header className="conversation-head">
        <Robot headOnly decorative size={44} mood={mood} />
        <div className="conversation-title">
          <h2 id="conversation-heading" className="bot-name">EDGAR<span>.AI</span></h2>
          <span className={pending ? 'status busy' : 'status'}>{status}</span>
        </div>
        {turns.length > 0 && !pending && (
          <button className="text-button" onClick={onClear}>
            Clear chat
          </button>
        )}
      </header>

      <div className="messages" aria-live="polite">
        {turns.length === 0 && !pending && (
          <div className="welcome">
            <p className="bubble">
              {!ready
                ? 'Hi, I’m EDGAR.AI! Load a company and I’ll read its annual report for you.'
                : `Hi, I’m EDGAR.AI! I’ve read ${subject ? `${subject}’s` : 'the'} latest 10‑K. Ask me anything about it.`}
            </p>
            <Robot size={150} track greet mood={mood} />
            {ready && !hasKey && (
              <p className="error">The Groq API key is missing. Add GROQ_API_KEY to the .env file and restart the server.</p>
            )}
            {ready && starters.length > 0 && (
              <div className="starters">
                <p className="empty-note">Start with one of these, or type your own question.</p>
                {starters.map((s, i) => (
                  <button key={s} className="suggestion" style={{ '--i': i } as React.CSSProperties} onClick={() => ask(s)}>
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {turns.map((turn, i) => (
          <div className="turn" key={i}>
            <p className="question">{turn.question}</p>
            <Answer
              turn={turn}
              latest={i === turns.length - 1 && !pending}
              fresh={i === fresh}
              onAsk={ask}
              onTick={scroll}
            />
          </div>
        ))}

        {pending && (
          <div className="turn">
            <p className="question">{pending}</p>
            <div className="reply">
              <Robot headOnly decorative size={36} mood="thinking" />
              <div className="answer working" role="status">
                <span className="dots" aria-hidden="true"><i /><i /><i /></span>
                {progressText(progress)}
                <span className="working-bar" aria-hidden="true" />
              </div>
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault()
          ask(draft)
        }}
      >
        <label htmlFor="question" className="visually-hidden">
          Your question
        </label>
        <textarea
          id="question"
          rows={2}
          value={draft}
          disabled={!ready}
          placeholder={ready ? `Ask a question${subject ? ` about ${subject}` : ''}` : 'Load a company first'}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              ask(draft)
            }
          }}
        />
        <button type="submit" className="primary" disabled={!ready || !draft.trim() || !!pending}>
          Ask
          <svg className="send-icon" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M2 8h10M8.5 3.5 13 8l-4.5 4.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </form>
    </section>
  )
}
