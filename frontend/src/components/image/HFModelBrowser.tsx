import { useEffect, useRef, useState } from 'react'
import { Search, Download, Lock, Loader2, X, Heart, ArrowDownToLine } from 'lucide-react'
import { searchHFModels, downloadHFModel } from '../../api/image'

interface HFResult {
  repo_id: string
  name: string
  downloads: number
  likes: number
  gated: boolean
  pipeline_tag: string | null
  tags: string[]
}

interface HFModelBrowserProps {
  open: boolean
  onClose: () => void
  onDownloadStarted: (modelId: string) => void
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

export default function HFModelBrowser({ open, onClose, onDownloadStarted }: HFModelBrowserProps) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<HFResult[]>([])
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState<Set<string>>(new Set())
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()

  // Debounced search.
  useEffect(() => {
    if (!open) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    const q = query.trim()
    if (!q) {
      setResults([])
      return
    }
    debounceRef.current = setTimeout(() => {
      setSearching(true)
      setError(null)
      searchHFModels(q)
        .then((data: HFResult[]) => setResults(data))
        .catch(() => setError('La recherche a échoué.'))
        .finally(() => setSearching(false))
    }, 400)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query, open])

  const handleDownload = async (r: HFResult) => {
    setDownloading((prev) => new Set(prev).add(r.repo_id))
    try {
      const res = await downloadHFModel({ repo_id: r.repo_id })
      onDownloadStarted(res.id)
    } catch {
      setError(`Échec du téléchargement de ${r.repo_id}`)
      setDownloading((prev) => {
        const next = new Set(prev)
        next.delete(r.repo_id)
        return next
      })
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="flex max-h-[80vh] w-full max-w-2xl flex-col rounded-2xl border border-gray-800 bg-gray-950 shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-800 p-4">
          <h3 className="text-sm font-semibold text-gray-200">Rechercher un modèle sur Hugging Face</h3>
          <button onClick={onClose} className="rounded-lg p-1 text-gray-500 hover:text-gray-300">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Search input */}
        <div className="p-4">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-gray-500" />
            <input
              autoFocus
              className="w-full rounded-xl border border-gray-800 bg-gray-900 p-2.5 pl-9 text-sm text-gray-100
                focus:border-purple-500 focus:outline-none transition-colors placeholder-gray-600"
              placeholder="ex. sdxl, flux, anime, realistic..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {searching && (
              <Loader2 className="absolute right-3 top-3 h-4 w-4 animate-spin text-purple-400" />
            )}
          </div>
          {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto px-4 pb-4">
          {results.length === 0 && query.trim() && !searching && (
            <p className="py-8 text-center text-sm text-gray-600">Aucun résultat.</p>
          )}
          {results.length === 0 && !query.trim() && (
            <p className="py-8 text-center text-sm text-gray-600">
              Tapez une requête pour rechercher des modèles text-to-image.
            </p>
          )}
          <ul className="space-y-2">
            {results.map((r) => {
              const isDownloading = downloading.has(r.repo_id)
              return (
                <li
                  key={r.repo_id}
                  className="flex items-center justify-between gap-3 rounded-xl border border-gray-800 bg-gray-900 p-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-medium text-gray-100">{r.name}</p>
                      {r.gated && (
                        <span className="flex shrink-0 items-center gap-1 rounded-full border border-amber-500/40
                          bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-300">
                          <Lock className="h-2.5 w-2.5" /> gated
                        </span>
                      )}
                    </div>
                    <p className="truncate text-[11px] text-gray-500">{r.repo_id}</p>
                    <div className="mt-1 flex items-center gap-3 text-[11px] text-gray-500">
                      <span className="flex items-center gap-1">
                        <ArrowDownToLine className="h-3 w-3" /> {formatCount(r.downloads)}
                      </span>
                      <span className="flex items-center gap-1">
                        <Heart className="h-3 w-3" /> {formatCount(r.likes)}
                      </span>
                      {r.pipeline_tag && (
                        <span className="rounded-full bg-purple-500/15 px-1.5 py-0.5 text-purple-300">
                          {r.pipeline_tag}
                        </span>
                      )}
                    </div>
                    {r.gated && (
                      <p className="mt-1 text-[10px] text-amber-400/80">
                        Nécessite un token HF (HUGGINGFACE_TOKEN) et l'acceptation de la licence sur Hugging Face.
                      </p>
                    )}
                  </div>
                  <button
                    onClick={() => handleDownload(r)}
                    disabled={isDownloading}
                    className="flex shrink-0 items-center gap-1.5 rounded-lg bg-purple-600 px-3 py-2 text-xs
                      font-medium text-white hover:bg-purple-500 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isDownloading ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" /> En cours
                      </>
                    ) : (
                      <>
                        <Download className="h-3.5 w-3.5" /> Télécharger
                      </>
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      </div>
    </div>
  )
}
