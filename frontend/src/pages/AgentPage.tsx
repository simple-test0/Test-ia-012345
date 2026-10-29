import { memo, useCallback, useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import {
  AlertTriangle, Bot, ChevronDown, ChevronRight, Copy, Loader2, Menu, Plus, RefreshCw, Send,
  Trash2, Wrench, X,
} from 'lucide-react'
import {
  createSession,
  deleteSession,
  getOllamaModels,
  getSession,
  getSessions,
  getTools,
  updateSession,
  type AgentSessionSummary,
} from '../api/agent'
import { errorMessage, wsUrl } from '../api/client'
import { useWebSocket } from '../hooks/useWebSocket'
import { usePersistentState } from '../hooks/usePersistentState'
import { loadRecommendations } from '../hooks/useHardwareInfo'
import { toast } from '../components/ui/toast'

// ─── Types ────────────────────────────────────────────────────────────────────

interface AgentTool {
  name: string
  description: string
}

interface ToolCallCard {
  id: string
  tool_name: string
  args: Record<string, unknown>
  result?: string
  expanded: boolean
}

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  tool_calls: ToolCallCard[]
  isStreaming?: boolean
}

type WsEvent =
  | { type: 'token'; content: string }
  | { type: 'tool_call'; id: string; tool_name: string; args: Record<string, unknown> }
  | { type: 'tool_result'; id: string; result: string }
  | { type: 'message_complete' }
  | { type: 'error'; message: string }

const DEFAULT_SYSTEM_PROMPT = 'You are a helpful AI assistant.'

let msgCounter = 0
const nextId = () => `msg-${++msgCounter}`

// ─── Tool Call Accordion ──────────────────────────────────────────────────────

function ToolCallAccordion({ card, onToggle }: { card: ToolCallCard; onToggle: (id: string) => void }) {
  return (
    <div className="my-1 w-full max-w-[85%] rounded-lg border border-gray-700 bg-gray-800/60 text-xs overflow-hidden">
      <button
        className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-gray-300 hover:bg-gray-700/40 transition-colors"
        onClick={() => onToggle(card.id)}
      >
        {card.expanded
          ? <ChevronDown className="h-3 w-3 text-purple-400 shrink-0" />
          : <ChevronRight className="h-3 w-3 text-purple-400 shrink-0" />}
        <Wrench className="h-3 w-3 text-purple-400 shrink-0" />
        <span className="font-medium text-purple-300">Outil :</span>
        <span className="font-mono">{card.tool_name}</span>
        {card.result === undefined && <Loader2 className="ml-auto h-3 w-3 animate-spin text-gray-500" />}
      </button>
      {card.expanded && (
        <div className="border-t border-gray-700 px-3 py-2 space-y-2">
          <div>
            <p className="text-gray-500 mb-1">Arguments</p>
            <pre className="whitespace-pre-wrap break-all text-gray-300 font-mono bg-gray-900/60 rounded p-2">
              {JSON.stringify(card.args, null, 2)}
            </pre>
          </div>
          {card.result !== undefined && (
            <div>
              <p className="text-gray-500 mb-1">Résultat</p>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-gray-300 font-mono bg-gray-900/60 rounded p-2">
                {card.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-1 px-3 py-2 rounded-xl bg-gray-800 self-start max-w-[80px]">
      {[0, 150, 300].map((delay) => (
        <span key={delay} className="h-2 w-2 rounded-full bg-gray-500 animate-bounce"
          style={{ animationDelay: `${delay}ms` }} />
      ))}
    </div>
  )
}

// Readable markdown inside dark chat bubbles (headings, lists, code, tables).
const markdownCls = `[&_p]:my-1.5 [&_ul]:my-1.5 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-1.5 [&_ol]:list-decimal
  [&_ol]:pl-5 [&_li]:my-0.5 [&_h1]:text-base [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold
  [&_a]:text-purple-300 [&_a]:underline [&_code]:rounded [&_code]:bg-black/30 [&_code]:px-1 [&_code]:py-0.5
  [&_code]:font-mono [&_code]:text-[0.85em] [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-lg
  [&_pre]:bg-black/40 [&_pre]:p-3 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_blockquote]:border-l-2
  [&_blockquote]:border-gray-600 [&_blockquote]:pl-3 [&_blockquote]:text-gray-400 [&_table]:my-2
  [&_th]:border [&_th]:border-gray-700 [&_th]:px-2 [&_td]:border [&_td]:border-gray-700 [&_td]:px-2`

const MessageBubble = memo(function MessageBubble({
  msg, onToggleTool,
}: { msg: ChatMessage; onToggleTool: (msgId: string, toolId: string) => void }) {
  const isUser = msg.role === 'user'
  const copy = () => {
    navigator.clipboard?.writeText(msg.content).then(
      () => toast.success('Message copié'),
      () => toast.error('Copie impossible'),
    )
  }

  return (
    <div className={`group flex flex-col ${isUser ? 'items-end' : 'items-start'} gap-1`}>
      {msg.tool_calls.map((tc) => (
        <ToolCallAccordion key={tc.id} card={tc} onToggle={(id) => onToggleTool(msg.id, id)} />
      ))}
      {(msg.content || msg.isStreaming) && (
        <div
          className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed break-words
            ${isUser
              ? 'bg-purple-600 text-white rounded-br-sm whitespace-pre-wrap'
              : `bg-gray-800 text-gray-100 rounded-bl-sm ${markdownCls}`}`}
        >
          {isUser ? msg.content : <Markdown>{msg.content}</Markdown>}
          {msg.isStreaming && (
            <span className="inline-block w-1 h-4 ml-0.5 bg-current animate-pulse align-middle" />
          )}
        </div>
      )}
      {!isUser && msg.content && !msg.isStreaming && (
        <button onClick={copy} className="flex items-center gap-1 text-[10px] text-gray-600 opacity-0 transition-opacity group-hover:opacity-100 hover:text-gray-300">
          <Copy className="h-3 w-3" /> Copier
        </button>
      )}
    </div>
  )
})

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function AgentPage() {
  const [sessions, setSessions] = useState<AgentSessionSummary[]>([])
  const [selectedSessionId, setSelectedSessionId] = usePersistentState<string | null>(
    'aistudio.agent.session', null,
  )
  const [showSessions, setShowSessions] = useState(false) // mobile drawer

  const [models, setModels] = useState<string[]>([])
  const [ollamaStatus, setOllamaStatus] = useState<'checking' | 'up' | 'down'>('checking')
  const [suggested, setSuggested] = useState<string[]>([])
  const [selectedModel, setSelectedModel] = usePersistentState('aistudio.agent.model', '')
  const [systemPrompt, setSystemPrompt] = useState(DEFAULT_SYSTEM_PROMPT)
  const savedPromptRef = useRef(DEFAULT_SYSTEM_PROMPT)
  const [tools, setTools] = useState<AgentTool[]>([])

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [inputText, setInputText] = useState('')
  const [thinking, setThinking] = useState(false) // waiting for the first token
  const [busy, setBusy] = useState(false) // a turn is in progress (until complete)

  const scrollRef = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const pendingSend = useRef<string | null>(null)
  // A session we just created has nothing to load (and loading it would wipe
  // the first message being sent).
  const freshSession = useRef<string | null>(null)

  // ── Data fetching ─────────────────────────────────────────────────────────

  const refreshSessions = useCallback(
    () => getSessions().then(setSessions).catch(() => {}),
    [],
  )

  const checkOllama = useCallback(() => {
    setOllamaStatus('checking')
    getOllamaModels()
      .then(({ available, models: names }) => {
        setOllamaStatus(available ? 'up' : 'down')
        setModels(names)
        setSelectedModel((cur) => (names.includes(cur) ? cur : names[0] ?? ''))
        if (available && names.length === 0) {
          loadRecommendations().then((r) => r && setSuggested(r.agent.recommended_models))
        }
      })
      .catch(() => setOllamaStatus('down'))
  }, [setSelectedModel])

  useEffect(() => {
    refreshSessions()
    checkOllama()
    getTools().then(setTools).catch(() => {})
  }, [refreshSessions, checkOllama])

  // Load the selected session's history and settings.
  useEffect(() => {
    if (!selectedSessionId) {
      setBusy(false)
      setThinking(false)
      setMessages([])
      setSystemPrompt(DEFAULT_SYSTEM_PROMPT)
      savedPromptRef.current = DEFAULT_SYSTEM_PROMPT
      return
    }
    if (freshSession.current === selectedSessionId) {
      freshSession.current = null
      savedPromptRef.current = systemPrompt
      return
    }
    // Switching to another conversation: any turn shown before is not ours.
    setBusy(false)
    setThinking(false)
    let cancelled = false
    setLoadingHistory(true)
    getSession(selectedSessionId)
      .then((s) => {
        if (cancelled) return
        setMessages(
          (s.messages || []).map((m) => ({ id: nextId(), role: m.role, content: m.content, tool_calls: [] })),
        )
        setSystemPrompt(s.system_prompt || '')
        savedPromptRef.current = s.system_prompt || ''
        stickToBottom.current = true
      })
      .catch(() => {
        if (cancelled) return
        setSelectedSessionId(null) // deleted elsewhere
      })
      .finally(() => !cancelled && setLoadingHistory(false))
    return () => {
      cancelled = true
    }
  }, [selectedSessionId, setSelectedSessionId])

  // Auto-scroll, unless the user scrolled up to read.
  useEffect(() => {
    const el = scrollRef.current
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight
  }, [messages, thinking])

  const onScroll = () => {
    const el = scrollRef.current
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  // ── WebSocket ─────────────────────────────────────────────────────────────

  const agentWsUrl = selectedSessionId ? wsUrl(`/ws/agent/${selectedSessionId}`) : null

  const finishTurn = () => {
    setThinking(false)
    setBusy(false)
    setMessages((prev) => prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m)))
  }

  const { connected, send } = useWebSocket(agentWsUrl, {
    onOpen: () => {
      // First message of a brand-new session waits for the socket.
      if (pendingSend.current !== null) {
        const content = pendingSend.current
        pendingSend.current = null
        send({ content, model_id: selectedModel })
      }
    },
    onMessage: (raw) => {
      const evt = raw as WsEvent
      if (evt.type === 'token') {
        setThinking(false)
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last && last.role === 'assistant' && last.isStreaming) {
            return [...prev.slice(0, -1), { ...last, content: last.content + evt.content }]
          }
          return [...prev, { id: nextId(), role: 'assistant', content: evt.content, tool_calls: [], isStreaming: true }]
        })
      } else if (evt.type === 'tool_call') {
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          const card: ToolCallCard = { id: evt.id, tool_name: evt.tool_name, args: evt.args, expanded: false }
          if (last && last.role === 'assistant') {
            return [...prev.slice(0, -1), { ...last, tool_calls: [...last.tool_calls, card], isStreaming: true }]
          }
          return [...prev, { id: nextId(), role: 'assistant', content: '', tool_calls: [card], isStreaming: true }]
        })
      } else if (evt.type === 'tool_result') {
        setMessages((prev) =>
          prev.map((m) => ({
            ...m,
            tool_calls: m.tool_calls.map((tc) => (tc.id === evt.id ? { ...tc, result: evt.result } : tc)),
          })),
        )
      } else if (evt.type === 'message_complete') {
        finishTurn()
        refreshSessions() // message count / auto-generated title
      } else if (evt.type === 'error') {
        finishTurn()
        toast.error(evt.message)
      }
    },
  })

  // ── Actions ───────────────────────────────────────────────────────────────

  const handleNewSession = async (): Promise<string | null> => {
    try {
      const session = await createSession({
        name: `Session ${sessions.length + 1}`,
        model_id: selectedModel,
        system_prompt: systemPrompt.trim() || DEFAULT_SYSTEM_PROMPT,
      })
      setSessions((prev) => [session, ...prev])
      freshSession.current = session.id
      setSelectedSessionId(session.id)
      setMessages([])
      setShowSessions(false)
      inputRef.current?.focus()
      return session.id
    } catch (e) {
      toast.error(errorMessage(e, 'Impossible de créer la session'))
      return null
    }
  }

  const handleDeleteSession = async (id: string) => {
    if (!window.confirm('Supprimer cette conversation ?')) return
    try {
      await deleteSession(id)
      setSessions((prev) => prev.filter((s) => s.id !== id))
      if (selectedSessionId === id) setSelectedSessionId(null)
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  const saveSystemPrompt = () => {
    if (!selectedSessionId || systemPrompt === savedPromptRef.current) return
    updateSession(selectedSessionId, { system_prompt: systemPrompt })
      .then(() => {
        savedPromptRef.current = systemPrompt
        toast.success('Prompt système enregistré pour cette session')
      })
      .catch((e) => toast.error(errorMessage(e)))
  }

  const handleSend = async () => {
    const text = inputText.trim()
    // One turn at a time: a second message mid-answer would interleave replies.
    if (!text || busy) return
    if (!selectedModel) {
      toast.error('Aucun modèle Ollama disponible.')
      return
    }

    let sessionId = selectedSessionId
    if (!sessionId) {
      // Typing straight away creates a session: no extra click needed.
      sessionId = await handleNewSession()
      if (!sessionId) return
      pendingSend.current = text
    } else if (!send({ content: text, model_id: selectedModel })) {
      toast.error('Connexion au serveur perdue — nouvelle tentative en cours, réessayez dans un instant.')
      return
    }

    stickToBottom.current = true
    setMessages((prev) => [...prev, { id: nextId(), role: 'user', content: text, tool_calls: [] }])
    setInputText('')
    if (inputRef.current) inputRef.current.style.height = 'auto'
    setThinking(true)
    setBusy(true)
  }

  // If the socket drops mid-answer, stop the spinner and reload the saved
  // conversation once it is back (the server finishes the turn anyway).
  const wasConnected = useRef(false)
  useEffect(() => {
    if (wasConnected.current && !connected && busy) {
      setThinking(false)
      setBusy(false)
      toast.info('Connexion interrompue — la réponse sera rechargée à la reconnexion.')
    }
    if (!wasConnected.current && connected && selectedSessionId && !busy && messages.length > 0) {
      getSession(selectedSessionId)
        .then((s) => {
          if ((s.messages?.length ?? 0) > messages.filter((m) => !m.isStreaming).length) {
            setMessages(s.messages.map((m) => ({ id: nextId(), role: m.role, content: m.content, tool_calls: [] })))
          }
        })
        .catch(() => {})
    }
    wasConnected.current = connected
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleToggleTool = useCallback((msgId: string, toolId: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId
          ? { ...m, tool_calls: m.tool_calls.map((tc) => (tc.id === toolId ? { ...tc, expanded: !tc.expanded } : tc)) }
          : m,
      ),
    )
  }, [])

  const canChat = ollamaStatus === 'up' && !!selectedModel

  // ─────────────────────────────────────────────────────────────────────────

  const sessionsPanel = (
    <>
      <div className="p-3 border-b border-gray-800 flex gap-2">
        <button
          className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-purple-600
            hover:bg-purple-500 px-3 py-2.5 text-sm font-semibold text-white transition-colors"
          onClick={() => handleNewSession()}
        >
          <Plus className="h-4 w-4" /> Nouvelle conversation
        </button>
        <button className="md:hidden rounded-xl border border-gray-800 px-2 text-gray-400" onClick={() => setShowSessions(false)}>
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {sessions.map((s) => (
          <div
            key={s.id}
            className={`group flex items-center rounded-lg border transition-colors
              ${selectedSessionId === s.id ? 'bg-purple-600/30 border-purple-500/50' : 'hover:bg-gray-800 border-transparent'}`}
          >
            <button
              className="min-w-0 flex-1 px-3 py-2.5 text-left"
              onClick={() => {
                setSelectedSessionId(s.id)
                setShowSessions(false)
              }}
            >
              <p className="text-sm font-medium text-gray-200 truncate">{s.name}</p>
              <p className="text-xs text-gray-500">{s.message_count} messages</p>
            </button>
            <button
              onClick={() => handleDeleteSession(s.id)}
              className="mr-1 rounded p-1.5 text-gray-600 opacity-0 transition-opacity group-hover:opacity-100 hover:text-red-300 focus:opacity-100"
              title="Supprimer"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        {sessions.length === 0 && <p className="px-3 py-2 text-xs text-gray-600">Aucune conversation</p>}
      </div>

      <div className="p-3 border-t border-gray-800 space-y-3">
        {ollamaStatus === 'down' && (
          <div className="flex items-start gap-2 rounded-lg bg-yellow-500/10 border border-yellow-500/30 p-2">
            <AlertTriangle className="h-3.5 w-3.5 text-yellow-400 shrink-0 mt-0.5" />
            <div className="text-[10px] text-yellow-300 leading-snug space-y-1">
              <p>Ollama est injoignable. Installez-le depuis ollama.com puis lancez-le.</p>
              <button onClick={checkOllama} className="flex items-center gap-1 underline">
                <RefreshCw className="h-3 w-3" /> Réessayer
              </button>
            </div>
          </div>
        )}

        {ollamaStatus === 'up' && models.length === 0 && (
          <div className="rounded-lg bg-yellow-500/10 border border-yellow-500/30 p-2 text-[10px] text-yellow-300 leading-snug space-y-1">
            <p>Aucun modèle installé. Dans un terminal :</p>
            <code className="block rounded bg-black/40 px-1.5 py-1 font-mono">
              ollama pull {suggested[0] ?? 'llama3.2'}
            </code>
            <button onClick={checkOllama} className="flex items-center gap-1 underline">
              <RefreshCw className="h-3 w-3" /> Actualiser
            </button>
          </div>
        )}

        {models.length > 0 && (
          <div className="flex flex-col gap-1">
            <label htmlFor="agent-model" className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">Modèle</label>
            <div className="relative">
              <select
                id="agent-model"
                className="w-full appearance-none rounded-lg bg-gray-900 border border-gray-800 px-2.5 py-2
                  text-xs text-gray-200 focus:outline-none focus:border-purple-500 cursor-pointer"
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
              >
                {models.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2 top-2 h-3.5 w-3.5 text-gray-500" />
            </div>
          </div>
        )}

        <div className="flex flex-col gap-1">
          <label htmlFor="sys-prompt" className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">
            Prompt système {selectedSessionId && <span className="normal-case text-gray-600">(sauvé en quittant le champ)</span>}
          </label>
          <textarea
            id="sys-prompt"
            className="rounded-lg bg-gray-900 border border-gray-800 p-2 text-xs text-gray-200
              resize-y h-20 focus:outline-none focus:border-purple-500 transition-colors placeholder-gray-600"
            placeholder="Instructions pour l'assistant…"
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            onBlur={saveSystemPrompt}
          />
        </div>
      </div>
    </>
  )

  return (
    <div className="relative flex h-full overflow-hidden">
      {/* ── Left Panel: Sessions (drawer on mobile) ── */}
      <aside className="hidden md:flex w-64 shrink-0 flex-col border-r border-gray-800 overflow-hidden">
        {sessionsPanel}
      </aside>
      {showSessions && (
        <div className="md:hidden absolute inset-0 z-30 flex">
          <aside className="flex w-72 max-w-[85%] flex-col border-r border-gray-800 bg-gray-950 overflow-hidden">
            {sessionsPanel}
          </aside>
          <div className="flex-1 bg-black/50" onClick={() => setShowSessions(false)} />
        </div>
      )}

      {/* ── Center Panel: Chat ── */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <div className="md:hidden flex items-center gap-2 border-b border-gray-800 px-3 py-2">
          <button onClick={() => setShowSessions(true)} className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-800">
            <Menu className="h-4 w-4" />
          </button>
          <span className="truncate text-xs text-gray-400">
            {sessions.find((s) => s.id === selectedSessionId)?.name ?? 'Nouvelle conversation'}
          </span>
        </div>

        <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto p-4 space-y-3">
          {loadingHistory && (
            <div className="flex justify-center py-6 text-gray-500"><Loader2 className="h-5 w-5 animate-spin" /></div>
          )}
          {!loadingHistory && messages.length === 0 && !thinking && (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
              <Bot className="h-10 w-10 text-gray-700" />
              <p className="text-sm text-gray-500">
                {canChat
                  ? 'Posez une question — une conversation est créée automatiquement.'
                  : ollamaStatus === 'checking'
                    ? 'Connexion à Ollama…'
                    : 'Démarrez Ollama et installez un modèle pour discuter.'}
              </p>
            </div>
          )}

          {messages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} onToggleTool={handleToggleTool} />
          ))}

          {thinking && <ThinkingIndicator />}
        </div>

        {/* Input bar */}
        <div className="border-t border-gray-800 p-3 flex items-end gap-2">
          <textarea
            ref={inputRef}
            rows={1}
            className="flex-1 resize-none rounded-xl bg-gray-900 border border-gray-800 px-3 py-2.5
              text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors
              placeholder-gray-600 max-h-40 overflow-y-auto disabled:opacity-50"
            placeholder={canChat ? 'Votre message… (Entrée pour envoyer, Maj+Entrée pour une nouvelle ligne)' : 'Ollama indisponible'}
            value={inputText}
            disabled={!canChat}
            onChange={(e) => {
              setInputText(e.target.value)
              e.target.style.height = 'auto'
              e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`
            }}
            onKeyDown={handleKeyDown}
          />
          <button
            className="shrink-0 flex items-center justify-center h-10 w-10 rounded-xl bg-purple-600
              hover:bg-purple-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            onClick={handleSend}
            disabled={!canChat || !inputText.trim() || busy}
            title="Envoyer"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin text-white" /> : <Send className="h-4 w-4 text-white" />}
          </button>
        </div>
      </main>

      {/* ── Right Panel: Tools ── */}
      <aside className="hidden lg:block w-56 shrink-0 border-l border-gray-800 overflow-y-auto p-3">
        <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Outils disponibles</h3>
        {tools.length === 0 ? (
          <p className="text-xs text-gray-600">Aucun outil chargé</p>
        ) : (
          <div className="space-y-2">
            {tools.map((tool) => (
              <div key={tool.name} className="rounded-lg bg-gray-900 border border-gray-800 p-2.5 space-y-1">
                <div className="flex items-center gap-1.5">
                  <Wrench className="h-3 w-3 text-purple-400 shrink-0" />
                  <p className="text-xs font-mono font-medium text-purple-300 truncate">{tool.name}</p>
                </div>
                <p className="text-[10px] text-gray-500 leading-snug line-clamp-3">{tool.description}</p>
              </div>
            ))}
          </div>
        )}
      </aside>
    </div>
  )
}
