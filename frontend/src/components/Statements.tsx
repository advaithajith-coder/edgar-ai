import { useEffect, useState } from 'react'
import { api, type Company, type Statement } from '../api'
import { statementValue } from '../format'

/** The three statements, laid out like the annual report. */
export function Statements({ company }: { company: Company }) {
  const [active, setActive] = useState(company.statements[0]?.key ?? 'income_statement')
  const [segments, setSegments] = useState(false)
  const [data, setData] = useState<Statement | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setError('')
    api
      .statement(active, segments)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [active, segments, company.ticker])

  return (
    <section className="statements" aria-labelledby="statements-heading">
      <div className="statements-bar">
        <h2 id="statements-heading">Financial statements</h2>
        <label className="check">
          <input type="checkbox" checked={segments} onChange={(e) => setSegments(e.target.checked)} />
          Include segment breakdowns
        </label>
      </div>

      <div className="tabs" role="tablist" aria-label="Statement">
        {company.statements.map((s) => (
          <button
            key={s.key}
            role="tab"
            aria-selected={active === s.key}
            className={active === s.key ? 'tab active' : 'tab'}
            onClick={() => setActive(s.key)}
          >
            {s.title}
          </button>
        ))}
      </div>

      {error && <p className="error">{error}</p>}
      {data && data.rows.length === 0 && <p className="note">This statement isn’t in the filing.</p>}
      {data && data.rows.length > 0 && (
        <>
          <p className="note">{data.unitsNote}</p>
          <div className="statement-scroll" role="tabpanel">
            <table className="statement">
              <thead>
                <tr>
                  <th scope="col">
                    <span className="visually-hidden">Line item</span>
                  </th>
                  {data.years.map((y) => (
                    <th scope="col" className="num" key={y}>FY{y}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, i) =>
                  row.heading ? (
                    <tr className="heading" key={i}>
                      <th scope="rowgroup" colSpan={data.years.length + 1}>{row.label}</th>
                    </tr>
                  ) : (
                    <tr className={row.total ? 'total' : undefined} key={i}>
                      <th scope="row" className={row.indent ? 'indent' : undefined}>{row.label}</th>
                      {data.years.map((y) => {
                        const v = row.values[y]
                        if (v === undefined) return <td className="num" key={y} />
                        const f = statementValue(v)
                        return (
                          <td className={f.negative ? 'num negative' : 'num'} key={y}>{f.text}</td>
                        )
                      })}
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
