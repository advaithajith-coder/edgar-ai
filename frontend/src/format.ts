// Accounting-style numbers: grouped digits, negatives in brackets (shown in red ink by the CSS).

const grouped = (digits: number) =>
  new Intl.NumberFormat('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })

export type Formatted = { text: string; negative: boolean }

function bracket(value: number, text: string): Formatted {
  return value < 0 ? { text: `(${text})`, negative: true } : { text, negative: false }
}

/** $ millions → "416.2" in billions. */
export function billions(millions: number): Formatted {
  return bracket(millions, grouped(1).format(Math.abs(millions) / 1000))
}

export function percent(value: number, digits = 1): Formatted {
  return bracket(value, `${grouped(digits).format(Math.abs(value))}%`)
}

/** Statement values in $ millions; small non-whole values (per-share) keep two decimals. */
export function statementValue(value: number): Formatted {
  const digits = Math.abs(value) < 100 && !Number.isInteger(value) ? 2 : 0
  return bracket(value, grouped(digits).format(Math.abs(value)))
}

/** Change from last year to this year: % for money lines, percentage points for ratios.
 *  Rises get a "+" so they can't be mistaken for levels; falls are bracketed like other negatives. */
export function change(kind: 'money' | 'pct', now?: number, before?: number): Formatted | null {
  if (now === undefined || before === undefined || before === 0) return null
  const delta = kind === 'pct' ? now - before : (now / before - 1) * 100
  const text = `${grouped(1).format(Math.abs(delta))}${kind === 'pct' ? ' pts' : '%'}`
  return delta < 0 ? bracket(delta, text) : { text: `+${text}`, negative: false }
}

export function longDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
}
