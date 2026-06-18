import { useEffect, useRef, useState } from 'react'
import { Send, Plus, ChevronDown, ChevronRight, AlertTriangle, Wrench } from 'lucide-react'
import {
  getOllamaModels,
  getTools,
  getSessions,
  createSession,
} from '../api/agent'
import { useWebSocket } from '../hooks/useWebSocket'
import { wsUrl } from '../api/client'

// ─── Types ────────────────────────────────────────────────────────────────────

interface OllamaModel {
  id: string
  name: string
}

interface AgentTool {
  name: string
  description: string
}

interface Session {
  id: string
  name: string
  message_count: number
}

interface ToolCallCard {
  id: string
  tool_name: string
  args: Record<string, unknown>
  result?: string
  expanded: boolean
}

type MessageRole = 'user' | 'assistant'

interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  tool_calls: ToolCallCard[]
  isStreaming?: boolean
}

// WS event types
interface WsTokenEvent { type: 'token'; content: string }
interface WsToolCallEvent { type: 'tool_call'; id: string; tool_name: string; args: Record<string, unknown> }
interface WsToolResultEvent { type: 'tool_result'; id: string; result: string }
interface WsMessageCompleteEvent { type: 'message_complete' }
interface WsErrorEvent { type: 'error'; message: string }
type WsEvent =
  | WsTokenEvent
  | WsToolCallEvent
  | WsToolResultEvent
  | WsMessageCompleteEvent
  | WsErrorEvent

// ─── Tool Call Accordion ──────────────────────────────────────────────────────

interface ToolCallAccordionProps {
  card: ToolCallCard
  onToggle: (id: string) => void
}

function ToolCallAccordion({ card, onToggle }: ToolCallAccordionProps) {
  return (
    <div className="my-1 rounded-lg border border-gray-700 bg-gray-800/60 text-xs overflow-hidden">
      <button
        className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-gray-300 hover:bg-gray-700/40 transition-colors"
        onClick={() => onToggle(card.id)}
      >
        {card.expanded
          ? <ChevronDown className="h-3 w-3 text-purple-400 shrink-0" />
          : <ChevronRight className="h-3 w-3 text-purple-400 shrink-0" />}
        <Wrench className="h-3 w-3 text-purple-400 shrink-0" />
        <span className="font-medium text-purple-300">Used tool:</span>
        <span className="font-mono">{card.tool_name}</span>
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
              <p className="text-gray-500 mb-1">Result</p>
              <pre className="whitespace-pre-wrap break-all text-gray-300 font-mono bg-gray-900/60 rounded p-2">
                {card.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Thinking Indicator ───────────────────────────────────────────────────────

function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-1 px-3 py-2 rounded-xl bg-gray-800 self-start max-w-[80px]">
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="h-2 w-2 rounded-full bg-gray-500 animate-bounce"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </div>
  )
}

// ─── Message Bubble ───────────────────────────────────────────────────────────

interface MessageBubbleProps {
  msg: ChatMessage
  onToggleTool: (msgId: string, toolId: string) => void
}

function MessageBubble({ msg, onToggleTool }: MessageBubbleProps) {
  const isUser = msg.role === 'user'

  return (
    <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} gap-1`}>
      {msg.tool_calls.map((tc) => (
        <ToolCallAccordion
          key={tc.id}
          card={tc}
          onToggle={(id) => onToggleTool(msg.id, id)}
        />
      ))}
      {(msg.content || msg.isStreaming) && (
        <div
          className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words
            ${isUser
              ? 'bg-purple-600 text-white rounded-br-sm'
              : 'bg-gray-800 text-gray-100 rounded-bl-sm'
            }`}
        >
          {msg.content}
          {msg.isStreaming && (
            <span className="inline-block w-1 h-4 ml-0.5 bg-current animate-pulse align-middle" />
          )}
        </div>
      )}
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

let msgCounter = 0
const nextId = () => `msg-${++msgCounter}`

export default function AgentPage() {
  // Sessions
  const [sessions, setSessions] = useState<Session[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)

  // Models & tools
  const [models, setModels] = useState<OllamaModel[]>([])
  const [ollamaAvailable, setOllamaAvailable] = useState(true)
  const [selectedModel, setSelectedModel] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [tools, setTools] = useState<AgentTool[]>([])

  // Chat
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [inputText, setInputText] = useState('')
  const [thinking, setThinking] = useState(false)
  const [errorToast, setErrorToast] = useState<string | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // ── Data fetching ─────────────────────────────────────────────────────────

  useEffect(() => {
    getSessions()
      .then((data: Session[]) => setSessions(data))
      .catch(() => {})

    getOllamaModels()
      .then((resp) => {
        // Backend returns { available, models: string[] }.
        const list: OllamaModel[] = (resp.models || []).map((name) => ({
          id: name,
          name,
        }))
        if (!resp.available || list.length === 0) {
          setOllamaAvailable(false)
        } else {
          setModels(list)
          setSelectedModel(list[0].id)
        }
      })
      .catch(() => setOllamaAvailable(false))

    getTools()
      .then((data: AgentTool[]) => setTools(data))
      .catch(() => {})
  }, [])

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, thinking])

  // Hide error toast after 4 s
  useEffect(() => {
    if (!errorToast) return
    const t = setTimeout(() => setErrorToast(null), 4000)
    return () => clearTimeout(t)
  }, [errorToast])

  // ── WebSocket ─────────────────────────────────────────────────────────────

  const agentWsUrl = selectedSessionId
    ? wsUrl(`/ws/agent/${selectedSessionId}`)
    : null

  const { send } = useWebSocket(agentWsUrl, {
    onMessage: (raw) => {
      const evt = raw as WsEvent

      if (evt.type === 'token') {
        setThinking(false)
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last && last.role === 'assistant' && last.isStreaming) {
            return [
              ...prev.slice(0, -1),
              { ...last, content: last.content + evt.content },
            ]
          }
          // Start a new streaming message
          return [
            ...prev,
            {
              id: nextId(),
              role: 'assistant',
              content: evt.content,
              tool_calls: [],
              isStreaming: true,
            },
          ]
        })
      } else if (evt.type === 'tool_call') {
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          const newTool: ToolCallCard = {
            id: evt.id,
            tool_name: evt.tool_name,
            args: evt.args,
            expanded: false,
          }
          if (last && last.role === 'assistant') {
            return [
              ...prev.slice(0, -1),
              { ...last, tool_calls: [...last.tool_calls, newTool] },
            ]
          }
          return [
            ...prev,
            {
              id: nextId(),
              role: 'assistant',
              content: '',
              tool_calls: [newTool],
              isStreaming: true,
            },
          ]
        })
      } else if (evt.type === 'tool_result') {
        setMessages((prev) =>
          prev.map((m) => ({
            ...m,
            tool_calls: m.tool_calls.map((tc) =>
              tc.id === evt.id ? { ...tc, result: evt.result } : tc
            ),
          }))
        )
      } else if (evt.type === 'message_complete') {
        setThinking(false)
        setMessages((prev) =>
          prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m))
        )
      } else if (evt.type === 'error') {
        setThinking(false)
        setMessages((prev) =>
          prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m))
        )
        setErrorToast(evt.message)
      }
    },
  })

  // ── Actions ───────────────────────────────────────────────────────────────

  const handleNewSession = async () => {
    try {
      const session = await createSession({
        name: `Session ${sessions.length + 1}`,
        model_id: selectedModel,
        system_prompt: systemPrompt,
      })
      setSessions((prev) => [session, ...prev])
      setSelectedSessionId(session.id)
      setMessages([])
    } catch {
      setErrorToast('Failed to create session')
    }
  }

  const handleSend = () => {
    const text = inputText.trim()
    if (!text || !selectedSessionId) return

    const userMsg: ChatMessage = {
      id: nextId(),
      role: 'user',
      content: text,
      tool_calls: [],
    }
    setMessages((prev) => [...prev, userMsg])
    setInputText('')
    setThinking(true)

    send({ content: text, model_id: selectedModel })
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleToggleTool = (msgId: string, toolId: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId
          ? {
              ...m,
              tool_calls: m.tool_calls.map((tc) =>
                tc.id === toolId ? { ...tc, expanded: !tc.expanded } : tc
              ),
            }
          : m
      )
    )
  }

  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full overflow-hidden">
      {/* ── Left Panel: Sessions ── */}
      <aside className="w-64 shrink-0 flex flex-col border-r border-gray-800 overflow-hidden">
        <div className="p-3 border-b border-gray-800">
          <button
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-purple-600
              hover:bg-purple-500 px-3 py-2.5 text-sm font-semibold text-white transition-colors"
            onClick={handleNewSession}
          >
            <Plus className="h-4 w-4" />
            New Session
          </button>
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {sessions.map((s) => (
            <button
              key={s.id}
              className={`w-full rounded-lg px-3 py-2.5 text-left transition-colors
                ${selectedSessionId === s.id
                  ? 'bg-purple-600/30 border border-purple-500/50'
                  : 'hover:bg-gray-800 border border-transparent'
                }`}
              onClick={() => {
                setSelectedSessionId(s.id)
                setMessages([])
              }}
            >
              <p className="text-sm font-medium text-gray-200 truncate">{s.name}</p>
              <p className="text-xs text-gray-500">{s.message_count} messages</p>
            </button>
          ))}
          {sessions.length === 0 && (
            <p className="px-3 py-2 text-xs text-gray-600">No sessions yet</p>
          )}
        </div>

        {/* Model selector + system prompt */}
        <div className="p-3 border-t border-gray-800 space-y-3">
          {!ollamaAvailable && (
            <div className="flex items-start gap-2 rounded-lg bg-yellow-500/10 border border-yellow-500/30 p-2">
              <AlertTriangle className="h-3.5 w-3.5 text-yellow-400 shrink-0 mt-0.5" />
              <p className="text-[10px] text-yellow-300 leading-snug">
                Ollama not detected — install it to use agents
              </p>
            </div>
          )}

          {ollamaAvailable && models.length > 0 && (
            <div className="flex flex-col gap-1">
              <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">Model</label>
              <div className="relative">
                <select
                  className="w-full appearance-none rounded-lg bg-gray-900 border border-gray-800 px-2.5 py-2
                    text-xs text-gray-200 focus:outline-none focus:border-purple-500 cursor-pointer"
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                >
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2 top-2 h-3.5 w-3.5 text-gray-500" />
              </div>
            </div>
          )}

          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">System Prompt</label>
            <textarea
              className="rounded-lg bg-gray-900 border border-gray-800 p-2 text-xs text-gray-200
                resize-none h-20 focus:outline-none focus:border-purple-500 transition-colors placeholder-gray-600"
              placeholder="Optional system instructions..."
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
            />
          </div>
        </div>
      </aside>

      {/* ── Center Panel: Chat ── */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Message thread */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {messages.length === 0 && !thinking && (
            <div className="flex h-full items-center justify-center">
              <p className="text-sm text-gray-600">
                {selectedSessionId
                  ? 'Send a message to start the conversation'
                  : 'Create or select a session to begin'}
              </p>
            </div>
          )}

          {messages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} onToggleTool={handleToggleTool} />
          ))}

          {thinking && <ThinkingIndicator />}
          <div ref={messagesEndRef} />
        </div>

        {/* Error toast */}
        {errorToast && (
          <div className="mx-4 mb-2 rounded-lg bg-red-500/10 border border-red-500/30 px-3 py-2 text-xs text-red-400">
            {errorToast}
          </div>
        )}

        {/* Input bar */}
        <div className="border-t border-gray-800 p-3 flex items-end gap-2">
          <textarea
            ref={inputRef}
            rows={1}
            className="flex-1 resize-none rounded-xl bg-gray-900 border border-gray-800 px-3 py-2.5
              text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors
              placeholder-gray-600 max-h-32 overflow-y-auto"
            placeholder={selectedSessionId ? 'Type a message… (Enter to send)' : 'Select a session first'}
            value={inputText}
            disabled={!selectedSessionId}
            onChange={(e) => {
              setInputText(e.target.value)
              // Auto-resize
              e.target.style.height = 'auto'
              e.target.style.height = `${Math.min(e.target.scrollHeight, 128)}px`
            }}
            onKeyDown={handleKeyDown}
          />
          <button
            className="shrink-0 flex items-center justify-center h-10 w-10 rounded-xl bg-purple-600
              hover:bg-purple-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            onClick={handleSend}
            disabled={!selectedSessionId || !inputText.trim() || thinking}
          >
            <Send className="h-4 w-4 text-white" />
          </button>
        </div>
      </main>

      {/* ── Right Panel: Tools ── */}
      <aside className="w-56 shrink-0 border-l border-gray-800 overflow-y-auto p-3">
        <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">
          Available Tools
        </h3>
        {tools.length === 0 ? (
          <p className="text-xs text-gray-600">No tools loaded</p>
        ) : (
          <div className="space-y-2">
            {tools.map((tool) => (
              <div
                key={tool.name}
                className="rounded-lg bg-gray-900 border border-gray-800 p-2.5 space-y-1"
              >
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
