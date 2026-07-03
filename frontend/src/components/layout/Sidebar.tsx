import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Bot, FlaskConical, ImageIcon, Power, Terminal } from 'lucide-react'
import { clsx } from 'clsx'
import { shutdownApp } from '../../api/system'

const links = [
  { to: '/image', label: 'Image Gen', icon: ImageIcon },
  { to: '/agent', label: 'Agent', icon: Bot },
  { to: '/labs', label: 'Labs', icon: FlaskConical },
  { to: '/console', label: 'Console', icon: Terminal },
]

export default function Sidebar() {
  const [confirming, setConfirming] = useState(false)
  const [stopped, setStopped] = useState(false)

  const handleShutdown = async () => {
    setConfirming(false)
    try {
      await shutdownApp()
    } catch {
      // The server can die before the response makes it back — that's success.
    }
    setStopped(true)
  }

  if (stopped) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-gray-950">
        <Power className="h-10 w-10 text-gray-600" />
        <p className="text-lg font-medium text-gray-200">Application arrêtée</p>
        <p className="text-sm text-gray-500">
          Les serveurs sont éteints — tu peux fermer cet onglet.
          <br />
          Pour relancer AI Studio, double-clique sur <span className="font-mono text-gray-400">start.bat</span>.
        </p>
      </div>
    )
  }

  return (
    <nav className="flex w-16 flex-col items-center gap-2 border-r border-gray-800 bg-gray-950 py-4">
      {links.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          title={label}
          className={({ isActive }) =>
            clsx(
              'flex flex-col items-center gap-1 rounded-lg p-2 text-xs transition-colors',
              isActive
                ? 'bg-purple-900/50 text-purple-300'
                : 'text-gray-500 hover:bg-gray-800 hover:text-gray-200',
            )
          }
        >
          <Icon size={20} />
          <span className="text-[10px]">{label}</span>
        </NavLink>
      ))}

      <div className="mt-auto">
        <button
          onClick={() => setConfirming(true)}
          title="Arrêter l'application"
          className="flex flex-col items-center gap-1 rounded-lg p-2 text-xs text-gray-500
            transition-colors hover:bg-red-900/40 hover:text-red-400"
        >
          <Power size={20} />
          <span className="text-[10px]">Arrêter</span>
        </button>
      </div>

      {confirming && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
          <div className="w-80 rounded-xl border border-gray-700 bg-gray-900 p-5 shadow-2xl">
            <p className="text-sm font-medium text-gray-100">Arrêter AI Studio ?</p>
            <p className="mt-1 text-xs text-gray-400">
              Les serveurs backend et frontend seront éteints. Les générations et
              entraînements en cours seront interrompus.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setConfirming(false)}
                className="rounded-lg border border-gray-700 px-3 py-1.5 text-xs text-gray-300
                  hover:bg-gray-800 transition-colors"
              >
                Annuler
              </button>
              <button
                onClick={handleShutdown}
                className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white
                  hover:bg-red-500 transition-colors"
              >
                Arrêter
              </button>
            </div>
          </div>
        </div>
      )}
    </nav>
  )
}
