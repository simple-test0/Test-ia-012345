import { useCallback, useEffect, useRef, useState } from 'react'
import { Pause, Play, Trash2, ArrowDownToLine } from 'lucide-react'
import { LogEntry } from '../api/system'
import { useWebSocket } from '../hooks/useWebSocket'
import { wsUrl } from '../api/client'

const MAX_LINES = 2000

const LEVEL_STYLES: Record<string, string> = {
  DEBUG: 'text-gray-500',
  INFO: 'text-gray-300',
  WARNING: 'text-yellow-300',
  ERROR: 'text-red-400',
  CRITICAL: 'text-red-300 bg-red-900/40',
}

const LEVELS = ['TOUS', 'INFO', 'WARNING', 'ERROR']

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString('fr-FR', { hour12: false })
}

export default function ConsolePage() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [paused, setPaused] = useState(false)
  const [level, setLevel] = useState('TOUS')
  const [filter, setFilter] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)
  const pausedRef = useRef(paused)
  pausedRef.current = paused
  const seenIds = useRef(new Set<number>())

  const onMessage = useCallback((data: unknown) => {
    const entry = data as LogEntry & { type?: string }
    if (entry?.type !== 'log' || pausedRef.current) return
    // The WS backlog overlaps with live records — dedupe by sequence id.
    if (seenIds.current.has(entry.id)) return
    seenIds.current.add(entry.id)
    setLogs((prev) => {
      const next = [...prev, entry]
      if (next.length > MAX_LINES) {
        for (const dropped of next.splice(0, next.length - MAX_LINES)) {
          seenIds.current.delete(dropped.id)
        }
      }
      return next
    })
  }, [])

  const { connected } = useWebSocket(wsUrl('/ws/logs'), { onMessage })

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    // Re-engage auto-scroll only when the user is back at the bottom.
    setAutoScroll(el.scrollHeight - el.scrollTop - el.clientHeight < 40)
  }

  const visible = logs.filter((l) => {
    if (level !== 'TOUS') {
      if (level === 'ERROR' && !['ERROR', 'CRITICAL'].includes(l.level)) return false
      if (level === 'WARNING' && !['WARNING', 'ERROR', 'CRITICAL'].includes(l.level)) return false
      if (level === 'INFO' && l.level === 'DEBUG') return false
    }
    if (filter && !l.message.toLowerCase().includes(filter.toLowerCase())) return false
    return true
  })

  return (
    <div className="flex h-full flex-col p-4 gap-3">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-lg font-semibold text-gray-100">Console</h1>
        <span
          className={`inline-flex items-center gap-1.5 text-xs ${connected ? 'text-green-400' : 'text-red-400'}`}
        >
          <span className={`h-2 w-2 rounded-full ${connected ? 'bg-green-400' : 'bg-red-400'}`} />
          {connected ? 'en direct' : 'déconnecté'}
        </span>

        <div className="ml-auto flex items-center gap-2">
          <select
            value={level}
            onChange={(e) => setLevel(e.target.value)}
            className="rounded bg-gray-900 border border-gray-700 px-2 py-1.5 text-xs text-gray-200
              focus:outline-none focus:border-purple-500"
          >
            {LEVELS.map((lv) => (
              <option key={lv} value={lv}>{lv === 'TOUS' ? 'Tous les niveaux' : lv}</option>
            ))}
          </select>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filtrer…"
            className="w-44 rounded bg-gray-900 border border-gray-700 px-2 py-1.5 text-xs text-gray-200
              placeholder-gray-600 focus:outline-none focus:border-purple-500"
          />
          <button
            onClick={() => setPaused((p) => !p)}
            title={paused ? 'Reprendre' : 'Mettre en pause'}
            className={`rounded border px-2 py-1.5 text-xs inline-flex items-center gap-1.5 transition-colors
              ${paused
                ? 'border-yellow-500/50 bg-yellow-500/10 text-yellow-300'
                : 'border-gray-700 bg-gray-900 text-gray-300 hover:bg-gray-800'}`}
          >
            {paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
            {paused ? 'Reprendre' : 'Pause'}
          </button>
          <button
            onClick={() => { setLogs([]); seenIds.current.clear() }}
            title="Vider la console"
            className="rounded border border-gray-700 bg-gray-900 px-2 py-1.5 text-xs text-gray-300
              hover:bg-gray-800 inline-flex items-center gap-1.5 transition-colors"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Vider
          </button>
        </div>
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="relative flex-1 overflow-auto rounded-lg border border-gray-800 bg-black/60 p-3
          font-mono text-[11px] leading-relaxed"
      >
        {visible.length === 0 && (
          <p className="text-gray-600">Aucun log{filter || level !== 'TOUS' ? ' (filtre actif)' : ''} pour le moment…</p>
        )}
        {visible.map((l) => (
          <div key={l.id} className="flex gap-2 whitespace-pre-wrap break-all hover:bg-gray-900/50">
            <span className="shrink-0 text-gray-600">{formatTime(l.ts)}</span>
            <span className={`shrink-0 w-16 ${LEVEL_STYLES[l.level] ?? 'text-gray-300'}`}>{l.level}</span>
            <span className="shrink-0 max-w-40 truncate text-purple-400/70">{l.logger}</span>
            <span className={LEVEL_STYLES[l.level] ?? 'text-gray-300'}>{l.message}</span>
          </div>
        ))}
      </div>

      {!autoScroll && (
        <button
          onClick={() => {
            setAutoScroll(true)
            scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
          }}
          className="absolute bottom-8 right-8 rounded-full bg-purple-600 p-2 text-white shadow-lg
            hover:bg-purple-500 transition-colors"
          title="Reprendre le défilement automatique"
        >
          <ArrowDownToLine className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}
