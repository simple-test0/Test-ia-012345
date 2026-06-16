import { NavLink } from 'react-router-dom'
import { Bot, FlaskConical, ImageIcon } from 'lucide-react'
import { clsx } from 'clsx'

const links = [
  { to: '/image', label: 'Image Gen', icon: ImageIcon },
  { to: '/agent', label: 'Agent', icon: Bot },
  { to: '/labs', label: 'Labs', icon: FlaskConical },
]

export default function Sidebar() {
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
    </nav>
  )
}
