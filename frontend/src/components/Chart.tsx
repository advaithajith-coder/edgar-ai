import { useEffect, useRef } from 'react'
import Plotly from 'plotly.js-dist-min'

// Series colours, in order: robot cyan, violet, green, amber, slate. Red is kept for negatives only.
const SERIES = ['#4FE3F0', '#8D7DFF', '#5CF2A6', '#F6C26B', '#8797B0']

/** Draws a chart the agent made (a Plotly figure from the backend) in the app's own style. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export default function Chart({ figure }: { figure: any }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const data = (figure.data ?? []).map((trace: any, i: number) => {
      const color = SERIES[i % SERIES.length]
      const t = { ...trace }
      if (t.marker && typeof t.marker.color === 'string') t.marker = { ...t.marker, color }
      if (t.line && typeof t.line.color === 'string') t.line = { ...t.line, color, width: 2.5 }
      return t
    })
    const source = figure.layout ?? {}
    // Column names as readable axis titles: "fiscal_year" → "Fiscal year"
    const readable = (text?: string) => text && (text.charAt(0).toUpperCase() + text.slice(1)).replace(/_/g, ' ')
    const axis = (a: { title?: { text?: string } } = {}) => ({
      ...a,
      // Years are labels, not quantities: no "2,024.5" ticks between them
      ...(/year|period/i.test(a.title?.text ?? '') ? { type: 'category' } : {}),
      gridcolor: '#152038',
      linecolor: '#1D2B45',
      zerolinecolor: '#1D2B45',
      tickfont: { size: 12, color: '#8797B0' },
      title: { ...a.title, text: readable(a.title?.text), font: { size: 12, color: '#8797B0' } },
    })
    const layout = {
      ...source,
      template: undefined,
      title: { text: source.title?.text ?? '', x: 0, xanchor: 'left', font: { size: 15, color: '#E6EDF7' } },
      font: { family: '"Public Sans", system-ui, sans-serif', color: '#E6EDF7', size: 13 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      colorway: SERIES,
      margin: { l: 56, r: 16, t: 44, b: 48 },
      height: 320,
      legend: { orientation: 'h', y: -0.22, x: 0, title: { text: '' } },
      xaxis: axis(source.xaxis),
      yaxis: axis(source.yaxis),
      hoverlabel: { bgcolor: '#0D1525', bordercolor: '#4FE3F0', font: { family: '"JetBrains Mono", monospace', color: '#E6EDF7' } },
    }
    Plotly.react(el, data, layout, { displaylogo: false, responsive: true, modeBarButtonsToRemove: ['lasso2d', 'select2d'] })
    return () => Plotly.purge(el)
  }, [figure])

  return <div className="chart" ref={ref} />
}
