import type { Company } from '../api'
import { billions, change, percent, type Formatted } from '../format'

function Cell({ value }: { value: Formatted | null }) {
  if (!value) return <td className="num empty" aria-label="not available" />
  return <td className={value.negative ? 'num negative' : 'num'}>{value.text}</td>
}

/** The key lines of the annual report across the years, set like a columnar ledger. */
export function Ledger({ company }: { company: Company }) {
  const { years, lines } = company.ledger
  const latest = years[years.length - 1]
  const prior = years[years.length - 2]

  return (
    <table className="ledger" key={company.ticker}>
      <caption className="visually-hidden">
        Key figures for {company.name} by fiscal year. Money in billions of US dollars.
      </caption>
      <thead>
        <tr>
          <th scope="col" className="ledger-unit">$ billions</th>
          {years.map((y) => (
            <th scope="col" className="num" key={y}>FY{y}</th>
          ))}
          <th scope="col" className="num">Change</th>
        </tr>
      </thead>
      <tbody>
        {lines.map((line, row) => (
          <tr key={line.label} style={{ '--row': row } as React.CSSProperties}>
            <th scope="row">{line.label}</th>
            {years.map((y) => {
              const v = line.values[y]
              return (
                <Cell key={y} value={v === undefined ? null : line.kind === 'money' ? billions(v) : percent(v)} />
              )
            })}
            <Cell value={change(line.kind, line.values[latest], prior ? line.values[prior] : undefined)} />
          </tr>
        ))}
      </tbody>
    </table>
  )
}
