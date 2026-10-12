import { useEffect, useId, useRef, useState } from 'react'
import { api, type CompanyOption } from '../api'

type Props = {
  onSelect: (ticker: string) => void
  busy?: boolean
  large?: boolean
  label: string
}

/** Dropdown for choosing a company: shows popular companies, or matches as you type a name or ticker. */
export function CompanyPicker({ onSelect, busy, large, label }: Props) {
  const id = useId()
  const listId = `${id}-list`
  const [query, setQuery] = useState('')
  const [options, setOptions] = useState<CompanyOption[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState('')
  const request = useRef(0)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    const mine = ++request.current
    setSearching(true)
    const timer = setTimeout(() => {
      api
        .searchCompanies(query)
        .then((found) => {
          if (mine !== request.current) return
          setOptions(found)
          setActive(0)
          setError('')
        })
        .catch((e) => mine === request.current && setError(e.message))
        .finally(() => mine === request.current && setSearching(false))
    }, query ? 150 : 0)
    return () => clearTimeout(timer)
  }, [query, open])

  function choose(option?: CompanyOption) {
    const ticker = option?.ticker ?? query.trim().toUpperCase()
    if (!ticker || busy) return
    setOpen(false)
    setQuery('')
    input.current?.blur()
    onSelect(ticker)
  }

  const activeId = open && options[active] ? `${id}-opt-${active}` : undefined

  return (
    <div className={large ? 'picker large' : 'picker'}>
      <label htmlFor={`${id}-input`} className="picker-label">{label}</label>
      <div className="picker-field">
        <input
          ref={input}
          id={`${id}-input`}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-activedescendant={activeId}
          aria-autocomplete="list"
          autoComplete="off"
          spellCheck={false}
          placeholder={busy ? 'Opening the report…' : 'Company name or ticker'}
          value={query}
          disabled={busy}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              setOpen(true)
              setActive((a) => Math.min(a + 1, options.length - 1))
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              setActive((a) => Math.max(a - 1, 0))
            } else if (e.key === 'Enter') {
              e.preventDefault()
              choose(open ? options[active] : undefined)
            } else if (e.key === 'Escape') {
              setOpen(false)
            }
          }}
        />
        <button
          type="button"
          className="picker-toggle"
          tabIndex={-1}
          aria-label={open ? 'Close company list' : 'Show company list'}
          disabled={busy}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            setOpen((o) => !o)
            input.current?.focus()
          }}
        >
          <svg viewBox="0 0 12 8" aria-hidden="true" className={open ? 'chevron up' : 'chevron'}>
            <path d="M1 1.5 6 6.5l5-5" fill="none" stroke="currentColor" strokeWidth="1.6" />
          </svg>
        </button>
      </div>

      {open && (
        <ul id={listId} role="listbox" className="picker-list" onMouseDown={(e) => e.preventDefault()}>
          {!query && options.length > 0 && (
            <li className="picker-note" role="presentation">Popular companies</li>
          )}
          {options.map((o, i) => (
            <li
              key={o.ticker}
              id={`${id}-opt-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? 'picker-option active' : 'picker-option'}
              onMouseEnter={() => setActive(i)}
              onClick={() => choose(o)}
            >
              <span className="picker-name">{o.name}</span>
              <span className="picker-ticker">{o.ticker}</span>
            </li>
          ))}
          {!searching && !error && query && options.length === 0 && (
            <li className="picker-note" role="presentation">
              No company matches “{query}”. Try its ticker or full name.
            </li>
          )}
          {searching && options.length === 0 && <li className="picker-note" role="presentation">Searching…</li>}
          {error && <li className="picker-note error" role="presentation">{error}</li>}
        </ul>
      )}
    </div>
  )
}
