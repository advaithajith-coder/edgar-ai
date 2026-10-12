import { useEffect, useState } from 'react'
import { api, type Company, type Turn } from './api'
import { Home } from './pages/Home'
import { Report } from './pages/Report'

/** Two pages: the home screen (/) and a company's report (/report?company=AAPL). */
function useLocation() {
  const [location, setLocation] = useState(() => ({ path: window.location.pathname, search: window.location.search }))
  useEffect(() => {
    const onPop = () => setLocation({ path: window.location.pathname, search: window.location.search })
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const navigate = (to: string) => {
    window.history.pushState(null, '', to)
    setLocation({ path: window.location.pathname, search: window.location.search })
    window.scrollTo(0, 0)
  }
  return { ...location, navigate }
}

export default function App() {
  const { path, search, navigate } = useLocation()
  const [company, setCompany] = useState<Company | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [hasKey, setHasKey] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [booted, setBooted] = useState(false)

  // Restore this tab's workspace (company and conversation) from the server.
  useEffect(() => {
    api
      .workspace()
      .then((w) => {
        setCompany(w.company)
        setTurns(w.turns)
        setHasKey(w.hasKey)
      })
      .catch((e) => setError(e.message))
      .finally(() => setBooted(true))
  }, [])

  // On the report page, open the company named in the address (?company=AAPL) if it isn't open yet.
  const wanted = path === '/report' ? new URLSearchParams(search).get('company')?.toUpperCase() : undefined
  useEffect(() => {
    if (!booted || !wanted || busy || wanted === company?.ticker) return
    setBusy(true)
    setError('')
    api
      .loadCompany(wanted)
      .then((loaded) => {
        setCompany(loaded)
        setTurns([])
      })
      .catch((e) => {
        setError((e as Error).message)
        window.history.replaceState(null, '', company ? `/report?company=${company.ticker}` : '/report')
      })
      .finally(() => setBusy(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [booted, wanted])

  if (path !== '/report') return <Home navigate={navigate} current={booted ? company : null} />

  return (
    <Report
      navigate={navigate}
      company={busy ? null : company}
      turns={turns}
      hasKey={hasKey}
      busy={busy || (!booted && !!wanted)}
      error={error}
      onTurn={(t) => setTurns((prev) => [...prev, t])}
      onClearChat={() => api.clearChat().then(() => setTurns([]))}
    />
  )
}
