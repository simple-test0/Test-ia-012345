import { useEffect, useState } from 'react'
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react'

type ToastKind = 'success' | 'error' | 'info'

interface ToastItem {
  id: number
  kind: ToastKind
  message: string
}

// Tiny pub/sub so any module can fire a toast without prop drilling / context.
let _id = 0
const listeners = new Set<(t: ToastItem) => void>()

function emit(kind: ToastKind, message: string) {
  const item = { id: ++_id, kind, message }
  listeners.forEach((l) => l(item))
}

export const toast = {
  success: (m: string) => emit('success', m),
  error: (m: string) => emit('error', m),
  info: (m: string) => emit('info', m),
}

const STYLES: Record<ToastKind, string> = {
  success: 'border-green-500/40 bg-green-500/10 text-green-200',
  error: 'border-red-500/40 bg-red-500/10 text-red-200',
  info: 'border-purple-500/40 bg-purple-500/10 text-purple-200',
}

const ICONS: Record<ToastKind, typeof Info> = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
}

export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>([])

  useEffect(() => {
    const onToast = (t: ToastItem) => {
      setItems((prev) => [...prev, t])
      setTimeout(() => {
        setItems((prev) => prev.filter((x) => x.id !== t.id))
      }, 5000)
    }
    listeners.add(onToast)
    return () => {
      listeners.delete(onToast)
    }
  }, [])

  const dismiss = (id: number) => setItems((prev) => prev.filter((x) => x.id !== id))

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex flex-col gap-2">
      {items.map((t) => {
        const Icon = ICONS[t.kind]
        return (
          <div
            key={t.id}
            className={`pointer-events-auto flex items-start gap-2 rounded-xl border px-3 py-2
              text-sm shadow-lg backdrop-blur max-w-sm ${STYLES[t.kind]}`}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" />
            <span className="flex-1">{t.message}</span>
            <button onClick={() => dismiss(t.id)} className="shrink-0 opacity-60 hover:opacity-100">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )
      })}
    </div>
  )
}
