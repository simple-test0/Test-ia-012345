import { useEffect, useState } from 'react'
import { Loader2, Play, Pause, Square, Download, FlaskConical, Database, Cpu } from 'lucide-react'
import {
  getArchitectures,
  getDatasets,
  downloadHFDataset,
  getRuns,
  createRun,
  pauseRun,
  resumeRun,
  stopRun,
} from '../api/labs'
import { useWebSocket } from '../hooks/useWebSocket'
import { wsUrl } from '../api/client'

// ─── Types ───────────────────────────────────────────────────────────────────

interface Architecture {
  id: string
  name: string
  description: string
  task_types: string[]
  min_vram_mb: number
  default_config: Record<string, unknown>
  tags?: string[]
}

interface Dataset {
  id: string
  name: string
  source: string
  status: string
  num_samples?: number
}

interface Run {
  id: string
  name: string
  architecture: string
  status: string
  current_epoch?: number
  total_epochs?: number
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-gray-500/20 text-gray-300 border border-gray-500/40',
  running: 'bg-blue-500/20 text-blue-300 border border-blue-500/40',
  paused: 'bg-yellow-500/20 text-yellow-300 border border-yellow-500/40',
  completed: 'bg-green-500/20 text-green-300 border border-green-500/40',
  failed: 'bg-red-500/20 text-red-300 border border-red-500/40',
}

// ─── Live metrics for a running run ──────────────────────────────────────────

function RunMetrics({ runId }: { runId: string }) {
  const [latest, setLatest] = useState<Record<string, number> | null>(null)
  const [warning, setWarning] = useState<string | null>(null)

  useWebSocket(wsUrl(`/ws/training/${runId}`), {
    onMessage: (raw) => {
      const evt = raw as { type: string; message?: string } & Record<string, number>
      if (evt.type === 'epoch_metric' || evt.type === 'batch_metric') {
        setLatest(evt)
      } else if (evt.type === 'warning' && evt.message) {
        setWarning(evt.message)
      }
    },
  })

  return (
    <div className="flex flex-col gap-1">
      {warning && (
        <p className="rounded bg-amber-500/10 border border-amber-500/30 px-2 py-1 text-[10px] text-amber-300">
          ⚠ {warning}
        </p>
      )}
      {latest ? (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-gray-400">
          {latest.epoch !== undefined && <span>epoch {latest.epoch}</span>}
          {latest.train_loss !== undefined && <span>train_loss {latest.train_loss}</span>}
          {latest.val_loss !== undefined && <span>val_loss {latest.val_loss}</span>}
          {latest.val_acc !== undefined && <span>val_acc {latest.val_acc}</span>}
          {latest.loss !== undefined && <span>loss {latest.loss}</span>}
        </div>
      ) : (
        <p className="text-[11px] text-gray-500">En attente de métriques…</p>
      )}
    </div>
  )
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function LabsPage() {
  const [architectures, setArchitectures] = useState<Architecture[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [error, setError] = useState<string | null>(null)

  // New run form
  const [runName, setRunName] = useState('')
  const [selectedArch, setSelectedArch] = useState('')
  const [selectedDataset, setSelectedDataset] = useState('')
  const [epochs, setEpochs] = useState(10)
  const [batchSize, setBatchSize] = useState(16)
  const [learningRate, setLearningRate] = useState(0.0003)
  const [creating, setCreating] = useState(false)

  // HF dataset form
  const [dsName, setDsName] = useState('')
  const [dsHfId, setDsHfId] = useState('')

  const refreshDatasets = () =>
    getDatasets().then(setDatasets).catch(() => {})
  const refreshRuns = () =>
    getRuns().then(setRuns).catch(() => {})

  useEffect(() => {
    getArchitectures()
      .then((data: Architecture[]) => {
        setArchitectures(data)
        if (data.length > 0) setSelectedArch(data[0].id)
      })
      .catch(() => setError('Impossible de charger les architectures'))
    refreshDatasets()
    refreshRuns()
  }, [])

  // Poll runs while any is active.
  useEffect(() => {
    const active = runs.some((r) => r.status === 'running' || r.status === 'pending')
    if (!active) return
    const interval = setInterval(refreshRuns, 4000)
    return () => clearInterval(interval)
  }, [runs])

  const handleDownloadDataset = async () => {
    if (!dsName.trim() || !dsHfId.trim()) return
    try {
      await downloadHFDataset({ name: dsName, hf_id: dsHfId, task_type: 'classification' })
      setDsName('')
      setDsHfId('')
      refreshDatasets()
    } catch {
      setError('Échec du téléchargement du dataset')
    }
  }

  const handleCreateRun = async () => {
    if (!runName.trim() || !selectedArch) return
    setCreating(true)
    setError(null)
    const arch = architectures.find((a) => a.id === selectedArch)
    try {
      await createRun({
        name: runName,
        architecture: selectedArch,
        arch_config: arch?.default_config ?? {},
        training_config: {
          epochs,
          batch_size: batchSize,
          learning_rate: learningRate,
        },
        dataset_id: selectedDataset || null,
      })
      setRunName('')
      refreshRuns()
    } catch {
      setError('Échec de la création du run')
    } finally {
      setCreating(false)
    }
  }

  const control = async (fn: (id: string) => Promise<unknown>, id: string) => {
    try {
      await fn(id)
      refreshRuns()
    } catch {
      setError('Action impossible')
    }
  }

  return (
    <div className="flex h-full gap-4 p-4 overflow-hidden">
      {/* ── Left: configuration ── */}
      <aside className="w-[38%] shrink-0 flex flex-col gap-4 overflow-y-auto pr-1">
        {/* New run */}
        <section className="rounded-xl border border-gray-800 bg-gray-900 p-3 flex flex-col gap-2">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-200">
            <FlaskConical className="h-4 w-4 text-purple-400" /> Nouvel entraînement
          </h3>

          <label className="text-xs font-medium text-gray-400">Nom</label>
          <input
            className="rounded-lg bg-gray-950 border border-gray-800 p-2 text-sm text-gray-100 focus:outline-none focus:border-purple-500"
            value={runName}
            onChange={(e) => setRunName(e.target.value)}
            placeholder="mon-run"
          />

          <label className="text-xs font-medium text-gray-400">Architecture</label>
          <select
            className="rounded-lg bg-gray-950 border border-gray-800 p-2 text-sm text-gray-100 focus:outline-none focus:border-purple-500"
            value={selectedArch}
            onChange={(e) => setSelectedArch(e.target.value)}
          >
            {architectures.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>

          <label className="text-xs font-medium text-gray-400">Dataset (optionnel)</label>
          <select
            className="rounded-lg bg-gray-950 border border-gray-800 p-2 text-sm text-gray-100 focus:outline-none focus:border-purple-500"
            value={selectedDataset}
            onChange={(e) => setSelectedDataset(e.target.value)}
          >
            <option value="">— Données aléatoires (démo) —</option>
            {datasets
              .filter((d) => d.status === 'ready')
              .map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
          </select>

          <div className="grid grid-cols-3 gap-2">
            <div className="flex flex-col gap-1">
              <label className="text-[11px] text-gray-400">Epochs</label>
              <input type="number" min={1} value={epochs}
                onChange={(e) => setEpochs(Number(e.target.value))}
                className="rounded-lg bg-gray-950 border border-gray-800 p-1.5 text-sm text-gray-100 focus:outline-none focus:border-purple-500" />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[11px] text-gray-400">Batch</label>
              <input type="number" min={1} value={batchSize}
                onChange={(e) => setBatchSize(Number(e.target.value))}
                className="rounded-lg bg-gray-950 border border-gray-800 p-1.5 text-sm text-gray-100 focus:outline-none focus:border-purple-500" />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[11px] text-gray-400">LR</label>
              <input type="number" step={0.0001} value={learningRate}
                onChange={(e) => setLearningRate(Number(e.target.value))}
                className="rounded-lg bg-gray-950 border border-gray-800 p-1.5 text-sm text-gray-100 focus:outline-none focus:border-purple-500" />
            </div>
          </div>

          <button
            onClick={handleCreateRun}
            disabled={creating || !runName.trim()}
            className="mt-1 flex items-center justify-center gap-2 rounded-lg bg-purple-600 hover:bg-purple-500
              disabled:opacity-50 disabled:cursor-not-allowed px-3 py-2 text-sm font-semibold text-white"
          >
            {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Lancer l'entraînement
          </button>
        </section>

        {/* Datasets */}
        <section className="rounded-xl border border-gray-800 bg-gray-900 p-3 flex flex-col gap-2">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-200">
            <Database className="h-4 w-4 text-purple-400" /> Datasets
          </h3>
          <div className="flex gap-2">
            <input
              className="flex-1 rounded-lg bg-gray-950 border border-gray-800 p-2 text-sm text-gray-100 focus:outline-none focus:border-purple-500"
              value={dsName} onChange={(e) => setDsName(e.target.value)} placeholder="Nom"
            />
            <input
              className="flex-1 rounded-lg bg-gray-950 border border-gray-800 p-2 text-sm text-gray-100 focus:outline-none focus:border-purple-500"
              value={dsHfId} onChange={(e) => setDsHfId(e.target.value)} placeholder="HF id (ex. mnist)"
            />
            <button
              onClick={handleDownloadDataset}
              disabled={!dsName.trim() || !dsHfId.trim()}
              className="flex items-center gap-1 rounded-lg bg-gray-800 hover:bg-gray-700 disabled:opacity-50 px-2.5 text-xs text-gray-200"
            >
              <Download className="h-3.5 w-3.5" />
            </button>
          </div>
          <ul className="flex flex-col gap-1">
            {datasets.length === 0 && <li className="text-[11px] text-gray-600">Aucun dataset.</li>}
            {datasets.map((d) => (
              <li key={d.id} className="flex items-center justify-between text-xs text-gray-300">
                <span className="truncate">{d.name}</span>
                <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${STATUS_COLORS[d.status] ?? STATUS_COLORS.pending}`}>
                  {d.status}
                </span>
              </li>
            ))}
          </ul>
        </section>

        {error && (
          <p className="rounded-lg bg-red-500/10 border border-red-500/30 px-3 py-2 text-xs text-red-400">{error}</p>
        )}
      </aside>

      {/* ── Right: runs ── */}
      <main className="flex-1 overflow-y-auto">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-400">
          <Cpu className="h-4 w-4" /> Runs d'entraînement
        </h2>
        {runs.length === 0 ? (
          <div className="flex h-48 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-gray-800 text-gray-600">
            <FlaskConical className="h-10 w-10" />
            <p className="text-sm">Aucun run — lancez un entraînement pour commencer</p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {runs.map((run) => (
              <div key={run.id} className="rounded-xl border border-gray-800 bg-gray-900 p-3 flex flex-col gap-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-medium text-gray-100">{run.name}</p>
                    <p className="text-[11px] text-gray-500">{run.architecture}</p>
                  </div>
                  <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${STATUS_COLORS[run.status] ?? STATUS_COLORS.pending}`}>
                    {run.status}
                  </span>
                </div>

                {run.total_epochs ? (
                  <p className="text-[11px] text-gray-500">
                    epoch {run.current_epoch ?? 0} / {run.total_epochs}
                  </p>
                ) : null}

                {(run.status === 'running' || run.status === 'paused') && <RunMetrics runId={run.id} />}

                {(run.status === 'running' || run.status === 'paused' || run.status === 'pending') && (
                  <div className="flex gap-2">
                    {run.status === 'paused' ? (
                      <button onClick={() => control(resumeRun, run.id)}
                        className="flex items-center gap-1 rounded-lg bg-gray-800 hover:bg-gray-700 px-2.5 py-1 text-xs text-gray-200">
                        <Play className="h-3 w-3" /> Reprendre
                      </button>
                    ) : (
                      <button onClick={() => control(pauseRun, run.id)}
                        className="flex items-center gap-1 rounded-lg bg-gray-800 hover:bg-gray-700 px-2.5 py-1 text-xs text-gray-200">
                        <Pause className="h-3 w-3" /> Pause
                      </button>
                    )}
                    <button onClick={() => control(stopRun, run.id)}
                      className="flex items-center gap-1 rounded-lg bg-red-900/50 hover:bg-red-900 px-2.5 py-1 text-xs text-red-200">
                      <Square className="h-3 w-3" /> Stop
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
