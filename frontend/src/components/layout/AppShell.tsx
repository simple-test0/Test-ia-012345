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
          <span className="text-sm font-semibold text-purple-400 tracking-wide">AI Studio</span>
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
