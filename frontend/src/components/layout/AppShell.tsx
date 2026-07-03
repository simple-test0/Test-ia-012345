import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import HardwareBadge from './HardwareBadge'
import { Toaster } from '../ui/toast'

export default function AppShell() {
  return (
    <div className="flex h-screen overflow-hidden bg-gray-950">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-12 items-center justify-between border-b border-gray-800 px-4">
          <span className="flex items-center gap-2.5">
            <span aria-hidden className="h-2.5 w-2.5 bg-purple-500" />
            <span className="font-mono text-xs font-semibold uppercase tracking-[0.3em] text-gray-200">
              AI Studio
            </span>
          </span>
          <HardwareBadge />
        </header>
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
      <Toaster />
    </div>
  )
}
