import { useEffect, useId, useRef, useState } from 'react'

/** What the robot is doing; each mood changes its face. */
export type Mood = 'idle' | 'listening' | 'thinking' | 'happy' | 'error'

type Props = {
  mood?: Mood
  size?: number // rendered width in px
  headOnly?: boolean // just the head, for avatars
  track?: boolean // eyes follow the pointer
  greet?: boolean // wave once when it first appears
  decorative?: boolean // hidden from screen readers (text nearby says the same)
  className?: string
}

const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

/** The assistant: the white robot with the glowing visor face, drawn in SVG so it can move. */
export function Robot({ mood = 'idle', size = 220, headOnly, track, greet, decorative, className }: Props) {
  const uid = useId().replace(/:/g, '')
  const ref = useRef<SVGSVGElement>(null)
  const [waving, setWaving] = useState(!!greet)
  const [look, setLook] = useState({ x: 0, y: 0 })

  // Wave for a moment after a greeting or a click.
  useEffect(() => {
    if (!waving) return
    const t = setTimeout(() => setWaving(false), 1900)
    return () => clearTimeout(t)
  }, [waving])

  // Eyes (and a little head tilt) follow the pointer.
  useEffect(() => {
    if (!track || reducedMotion()) return
    let frame = 0
    const onMove = (e: PointerEvent) => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const box = ref.current?.getBoundingClientRect()
        if (!box) return
        const dx = e.clientX - (box.left + box.width / 2)
        const dy = e.clientY - (box.top + box.height * 0.3)
        const dist = Math.hypot(dx, dy) || 1
        const reach = Math.min(1, dist / 420)
        setLook({ x: (dx / dist) * reach, y: (dy / dist) * reach })
      })
    }
    window.addEventListener('pointermove', onMove)
    return () => {
      window.removeEventListener('pointermove', onMove)
      cancelAnimationFrame(frame)
    }
  }, [track])

  const thinking = mood === 'thinking'
  const lookX = thinking ? 0 : look.x
  const lookY = thinking ? -0.6 : look.y
  const style = {
    width: size,
    '--ex': `${lookX * 7}px`,
    '--ey': `${lookY * 5}px`,
    '--tilt': `${lookX * 5}deg`,
  } as React.CSSProperties

  const id = (name: string) => `${uid}-${name}`
  const viewBox = headOnly ? '14 12 172 112' : '0 0 200 236'

  return (
    <svg
      ref={ref}
      viewBox={viewBox}
      className={['bot', `bot-${mood}`, waving && 'bot-waving', headOnly && 'bot-head-only', className]
        .filter(Boolean)
        .join(' ')}
      style={style}
      role={decorative ? undefined : 'img'}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : `EDGAR.AI, ${mood === 'idle' ? 'ready' : mood}`}
      onClick={() => !headOnly && setWaving(true)}
    >
      <defs>
        <linearGradient id={id('shell')} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#FFFFFF" />
          <stop offset="1" stopColor="#CDD4E0" />
        </linearGradient>
        <linearGradient id={id('shell-side')} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#E9EDF3" />
          <stop offset="1" stopColor="#B9C2D0" />
        </linearGradient>
        <linearGradient id={id('visor')} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#2A3A52" />
          <stop offset="1" stopColor="#081019" />
        </linearGradient>
        <filter id={id('glow')} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="2.2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <clipPath id={id('visor-clip')}>
          <rect x="46" y="34" width="108" height="70" rx="30" />
        </clipPath>
        <radialGradient id={id('pad')}>
          <stop offset="0" stopColor="#4FE3F0" stopOpacity="0.55" />
          <stop offset="1" stopColor="#4FE3F0" stopOpacity="0" />
        </radialGradient>
      </defs>

      {!headOnly && <ellipse className="bot-shadow" cx="100" cy="226" rx="44" ry="7" fill={`url(#${id('pad')})`} />}

      <g className="bot-float">
        {!headOnly && (
          <>
            <g className="bot-arm bot-arm-left">
              <rect x="34" y="132" width="20" height="66" rx="10" fill={`url(#${id('shell-side')})`} transform="rotate(12 44 136)" />
            </g>
            <g className="bot-arm bot-arm-right">
              <rect x="146" y="132" width="20" height="66" rx="10" fill={`url(#${id('shell-side')})`} transform="rotate(-12 156 136)" />
            </g>
            <path
              d="M100 120c34 0 46 26 46 52 0 28-20 44-46 44s-46-16-46-44c0-26 12-52 46-52Z"
              fill={`url(#${id('shell')})`}
            />
            <path d="M57 180h36l5-6h44" fill="none" stroke="#B3BCCB" strokeWidth="1.6" strokeLinecap="round" />
            <circle className="bot-core" cx="100" cy="152" r="4" fill="#4FE3F0" filter={`url(#${id('glow')})`} />
          </>
        )}

        <g className="bot-head">
          <rect x="20" y="50" width="20" height="44" rx="9" fill={`url(#${id('shell-side')})`} />
          <rect x="160" y="50" width="20" height="44" rx="9" fill={`url(#${id('shell-side')})`} />
          <rect className="bot-ear-light" x="23" y="62" width="3" height="20" rx="1.5" fill="#4FE3F0" />
          <rect className="bot-ear-light" x="174" y="62" width="3" height="20" rx="1.5" fill="#4FE3F0" />

          <rect x="32" y="18" width="136" height="100" rx="44" fill={`url(#${id('shell')})`} />
          <path d="M60 26c18-6 54-6 76 0" fill="none" stroke="#fff" strokeWidth="5" strokeLinecap="round" opacity="0.9" />
          <rect x="46" y="34" width="108" height="70" rx="30" fill={`url(#${id('visor')})`} />

          <g clipPath={`url(#${id('visor-clip')})`}>
            <rect className="bot-scan" x="46" y="34" width="108" height="10" fill="#4FE3F0" opacity="0" />
            <path d="M58 44c10-6 30-8 44-6" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" opacity="0.08" />
          </g>

          <g className="bot-face" fill="#4FE3F0" filter={`url(#${id('glow')})`}>
            <g className="bot-eyes">
              {/* happy: the half-moon eyes from the picture */}
              <g className="face face-happy">
                <path d="M69 72a9 9 0 0 1 18 0Z" />
                <path d="M113 72a9 9 0 0 1 18 0Z" />
              </g>
              <g className="face face-open">
                <ellipse cx="78" cy="66" rx="6.5" ry="8.5" />
                <ellipse cx="122" cy="66" rx="6.5" ry="8.5" />
              </g>
              <g className="face face-error">
                <path d="M70 62l14 10M84 62 70 72M114 62l14 10M128 62l-14 10" stroke="#FF6B86" strokeWidth="3.5" strokeLinecap="round" fill="none" />
              </g>
            </g>
            <path className="face face-smile" d="M92 84a8 8 0 0 0 16 0Z" />
            <ellipse className="face face-o" cx="100" cy="88" rx="4.5" ry="4" />
            <g className="face face-dots">
              <circle cx="88" cy="88" r="3.2" />
              <circle cx="100" cy="88" r="3.2" />
              <circle cx="112" cy="88" r="3.2" />
            </g>
            <path className="face face-flat" d="M92 90h16" stroke="#FF6B86" strokeWidth="3.5" strokeLinecap="round" fill="none" />
          </g>
        </g>
      </g>
    </svg>
  )
}

/** A speech bubble that types out each phrase, pauses, erases, and moves to the next. */
export function TypeLoop({ phrases, className }: { phrases: string[]; className?: string }) {
  const [index, setIndex] = useState(0)
  const [shown, setShown] = useState(0)
  const [erasing, setErasing] = useState(false)
  const phrase = phrases[index % phrases.length] ?? ''

  useEffect(() => {
    if (reducedMotion()) {
      setShown(phrase.length)
      const t = setTimeout(() => setIndex((i) => i + 1), 3500)
      return () => clearTimeout(t)
    }
    let delay = erasing ? 18 : 42
    if (!erasing && shown === phrase.length) delay = 2200
    if (erasing && shown === 0) delay = 300
    const t = setTimeout(() => {
      if (!erasing && shown < phrase.length) setShown(shown + 1)
      else if (!erasing) setErasing(true)
      else if (shown > 0) setShown(shown - 1)
      else {
        setErasing(false)
        setIndex((i) => i + 1)
      }
    }, delay)
    return () => clearTimeout(t)
  }, [shown, erasing, phrase])

  return (
    <p className={className} aria-live="off">
      {phrase.slice(0, shown)}
      <span className="caret" aria-hidden="true" />
    </p>
  )
}
