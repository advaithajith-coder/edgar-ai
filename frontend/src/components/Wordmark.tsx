import { Robot } from './Robot'

/** The app's name with the robot's head; links home. */
export function Wordmark({ onHome }: { onHome: () => void }) {
  return (
    <a
      href="/"
      className="wordmark"
      onClick={(e) => {
        e.preventDefault()
        onHome()
      }}
    >
      <Robot headOnly decorative size={34} />
      Annual Report Analyst
    </a>
  )
}
