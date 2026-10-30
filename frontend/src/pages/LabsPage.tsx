import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import {
  Cpu, Database, Download, FlaskConical, Loader2, Pause, Play, Square, Trash2, Upload,
} from 'lucide-react'
import {
  createRun,
  deleteDataset,
  deleteRun,
  downloadExport,
  downloadHFDataset,
  exportRun,
  getArchitectures,
  getDatasets,
  getRuns,
  pauseRun,
  resumeRun,
  stopRun,
  uploadDataset,
} from '../api/labs'
import { errorMessage, wsUrl } from '../api/client'
import { useWebSocket } from '../hooks/useWebSocket'
import { loadRecommendations } from '../hooks/useHardwareInfo'
import { usePersistentState } from '../hooks/usePersistentState'
import { toast } from '../components/ui/toast'
import type { EpochMetric } from '../components/labs/MetricsChart'

// Charts are only downloaded once a run has metrics to show.
const MetricsChart = lazy(() => import('../components/labs/MetricsChart'))

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
  num_classes?: number
  size_bytes?: number
  error_message?: string | null
}

interface Run {
  id: string
  name: string
  architecture: string
  status: string
  current_epoch?: number
  total_epochs?: number
  metrics_history?: (EpochMetric & { type?: string })[]
  best_checkpoint_path?: string | null
  error_message?: string | null
  hardware_snapshot?: { accelerator?: string } | null
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-gray-500/20 text-gray-300 border border-gray-500/40',
  downloading: 'bg-blue-500/20 text-blue-300 border border-blue-500/40',
  running: 'bg-blue-500/20 text-blue-300 border border-blue-500/40',
  paused: 'bg-yellow-500/20 text-yellow-300 border border-yellow-500/40',
  completed: 'bg-green-500/20 text-green-300 border border-green-500/40',
  ready: 'bg-green-500/20 text-green-300 border border-green-500/40',
  failed: 'bg-red-500/20 text-red-300 border border-red-500/40',
  error: 'bg-red-500/20 text-red-300 border border-red-500/40',
  cancelled: 'bg-gray-500/20 text-gray-400 border border-gray-500/40',
}

const STATUS_LABELS: Record<string, string> = {
  pending: 'en attente', downloading: 'téléchargement', running: 'en cours', paused: 'en pause',
  completed: 'terminé', ready: 'prêt', failed: 'échec', error: 'erreur', cancelled: 'arrêté',
}

const isLive = (s: string) => s === 'running' || s === 'paused' || s === 'pending'

const inputCls = 'rounded-lg bg-gray-950 border border-gray-800 p-2 text-sm text-gray-100 focus:outline-none focus:border-purple-500'

function formatBytes(n?: number) {
  if (!n) return ''
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`
  return `${Math.max(1, Math.round(n / 1e3))} KB`
}

// ─── Live metrics for a running run ──────────────────────────────────────────

function RunLive({ run, onEpoch }: { run: Run; onEpoch: (runId: string, m: EpochMetric) => void }) {
  const [latest, setLatest] = useState<Record<string, number> | null>(null)
  const [warning, setWarning] = useState<string | null>(null)
  const [device, setDevice] = useState<string | null>(null)

  useWebSocket(wsUrl(`/ws/training/${run.id}`), {
    onMessage: (raw) => {
      const evt = raw as { type: string; message?: string; device?: string } & Record<string, number>
      if (evt.type === 'batch_metric') setLatest(evt)
      else if (evt.type === 'epoch_metric') {
        setLatest(evt)
        onEpoch(run.id, evt as unknown as EpochMetric)
      } else if (evt.type === 'warning' && evt.message) setWarning(evt.message)
      else if (evt.type === 'model_info' && evt.device) setDevice(evt.device)
    },
  })

  return (
    <div className="flex flex-col gap-1">
      {warning && (
        <p className="rounded bg-amber-500/10 border border-amber-500/30 px-2 py-1 text-[10px] text-amber-300">⚠ {warning}</p>
      )}
      {latest ? (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-gray-400 font-mono">
          {latest.epoch !== undefined && <span>epoch {latest.epoch}</span>}
          {latest.step !== undefined && latest.train_loss === undefined && <span>step {latest.step}</span>}
          {latest.loss !== undefined && <span>loss {latest.loss}</span>}
          {latest.train_loss !== undefined && <span>train_loss {latest.train_loss}</span>}
          {latest.val_loss !== undefined && <span>val_loss {latest.val_loss}</span>}
          {latest.val_acc !== undefined && <span>val_acc {(latest.val_acc * 100).toFixed(1)}%</span>}
          {device && <span className="text-gray-600">{device}</span>}
        </div>
      ) : (
        <p className="flex items-center gap-1.5 text-[11px] text-gray-500">
          <Loader2 className="h-3 w-3 animate-spin" /> Démarrage (chargement de PyTorch)…
        </p>
      )}
    </div>
  )
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function LabsPage() {
  const [architectures, setArchitectures] = useState<Architecture[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [busy, setBusy] = useState<Record<string, boolean>>({})

  // New run form (remembered between visits)
  const [runName, setRunName] = useState('')
  const [selectedArch, setSelectedArch] = usePersistentState('aistudio.labs.arch', '')
  const [selectedDataset, setSelectedDataset] = useState('')
  const [epochs, setEpochs] = usePersistentState('aistudio.labs.epochs', 10)
  const [batchSize, setBatchSize] = usePersistentState<number | null>('aistudio.labs.batch', null)
  const [learningRate, setLearningRate] = usePersistentState('aistudio.labs.lr', 0.0003)
  const [creating, setCreating] = useState(false)

  // Dataset forms
  const [dsName, setDsName] = useState('')
  const [dsHfId, setDsHfId] = useState('')
  const [uploadPct, setUploadPct] = useState<number | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const refreshDatasets = useCallback(() => getDatasets().then(setDatasets).catch(() => {}), [])
  const refreshRuns = useCallback(() => getRuns().then(setRuns).catch(() => {}), [])

  useEffect(() => {
    getArchitectures()
      .then((data: Architecture[]) => {
        setArchitectures(data)
        setSelectedArch((cur) => (data.some((a) => a.id === cur) ? cur : data[0]?.id ?? ''))
      })
      .catch((e) => toast.error(`Architectures indisponibles : ${errorMessage(e)}`))
    refreshDatasets()
    refreshRuns()
    // Sensible default batch size for this machine.
    loadRecommendations().then((r) => {
      if (r) setBatchSize((cur) => cur ?? r.training.recommended_batch_size)
    })
  }, [refreshDatasets, refreshRuns, setSelectedArch, setBatchSize])

  // Poll while something is in progress (WebSocket gives the live details).
  const anyRunLive = runs.some((r) => isLive(r.status))
  useEffect(() => {
    if (!anyRunLive) return
    const t = setInterval(refreshRuns, 5000)
    return () => clearInterval(t)
  }, [anyRunLive, refreshRuns])

  const anyDatasetDownloading = datasets.some((d) => d.status === 'downloading')
  useEffect(() => {
    if (!anyDatasetDownloading) return
    const t = setInterval(refreshDatasets, 3000)
    return () => clearInterval(t)
  }, [anyDatasetDownloading, refreshDatasets])

  // Notify when a dataset finishes downloading.
  const prevDatasets = useRef<Dataset[]>([])
  useEffect(() => {
    for (const d of datasets) {
      const before = prevDatasets.current.find((p) => p.id === d.id)
      if (before?.status === 'downloading' && d.status === 'ready') toast.success(`Dataset « ${d.name} » prêt`)
      if (before?.status === 'downloading' && d.status === 'error') toast.error(d.error_message || `Échec : ${d.name}`)
    }
    prevDatasets.current = datasets
  }, [datasets])

  const withBusy = async (key: string, fn: () => Promise<unknown>) => {
    setBusy((b) => ({ ...b, [key]: true }))
    try {
      await fn()
    } catch (e) {
      toast.error(errorMessage(e, 'Action impossible'))
    } finally {
      setBusy((b) => ({ ...b, [key]: false }))
    }
  }

  const handleDownloadDataset = () =>
    withBusy('hf', async () => {
      if (!dsHfId.trim()) return
      await downloadHFDataset({
        name: dsName.trim() || dsHfId.trim().split('/').pop()!,
        hf_id: dsHfId.trim(),
        task_type: 'classification',
      })
      setDsName('')
      setDsHfId('')
      toast.info('Téléchargement du dataset démarré…')
      refreshDatasets()
    })

  const handleUpload = (files: FileList | null) => {
    if (!files || files.length === 0) return
    const list = Array.from(files)
    const name = dsName.trim() || list[0].name.replace(/\.[^.]+$/, '')
    withBusy('upload', async () => {
      setUploadPct(0)
      try {
        await uploadDataset(name, list, setUploadPct)
        toast.success(`${list.length} fichier(s) importé(s)`)
        setDsName('')
        refreshDatasets()
      } finally {
        setUploadPct(null)
        if (fileRef.current) fileRef.current.value = ''
      }
    })
  }

  const handleDeleteDataset = (d: Dataset) => {
    if (!window.confirm(`Supprimer le dataset « ${d.name} » et ses fichiers ?`)) return
    withBusy(`ds-${d.id}`, async () => {
      await deleteDataset(d.id)
      if (selectedDataset === d.id) setSelectedDataset('')
      refreshDatasets()
    })
  }

  const handleCreateRun = async () => {
    if (!selectedArch) return
    setCreating(true)
    const arch = architectures.find((a) => a.id === selectedArch)
    const name = runName.trim() || `${selectedArch}-${new Date().toLocaleTimeString().replace(/:/g, '')}`
    try {
      await createRun({
        name,
        architecture: selectedArch,
        arch_config: arch?.default_config ?? {},
        training_config: { epochs, batch_size: batchSize ?? 16, learning_rate: learningRate },
        dataset_id: selectedDataset || null,
      })
      setRunName('')
      toast.success(`Entraînement « ${name} » lancé`)
      refreshRuns()
    } catch (e) {
      toast.error(errorMessage(e, 'Échec de la création du run'))
    } finally {
      setCreating(false)
    }
  }

  const control = (key: string, fn: () => Promise<unknown>) =>
    withBusy(key, async () => {
      await fn()
      refreshRuns()
    })

  const handleExport = (run: Run, format: 'onnx' | 'safetensors') =>
    withBusy(`exp-${run.id}-${format}`, async () => {
      await exportRun(run.id, format)
      await downloadExport(run.id, format)
    })

  const handleDeleteRun = (run: Run) => {
    if (!window.confirm(`Supprimer le run « ${run.name} » et ses checkpoints ?`)) return
    control(`del-${run.id}`, () => deleteRun(run.id))
  }

  const appendEpoch = useCallback((runId: string, m: EpochMetric) => {
    setRuns((prev) =>
      prev.map((r) =>
        r.id === runId && !(r.metrics_history ?? []).some((x) => x.epoch === m.epoch)
          ? { ...r, current_epoch: m.epoch, metrics_history: [...(r.metrics_history ?? []), m] }
          : r,
      ),
    )
  }, [])

  const selectedArchInfo = architectures.find((a) => a.id === selectedArch)

  return (
    <div className="flex h-full flex-col md:flex-row gap-4 p-4 overflow-y-auto md:overflow-hidden">
      {/* ── Left: configuration ── */}
      <aside className="w-full md:w-[380px] md:shrink-0 flex flex-col gap-4 md:overflow-y-auto pr-1">
        {/* New run */}
        <section className="rounded-xl border border-gray-800 bg-gray-900 p-3 flex flex-col gap-2">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-200">
            <FlaskConical className="h-4 w-4 text-purple-400" /> Nouvel entraînement
          </h3>

          <label htmlFor="run-name" className="text-xs font-medium text-gray-400">Nom <span className="text-gray-600">(optionnel)</span></label>
          <input id="run-name" className={inputCls} value={runName} onChange={(e) => setRunName(e.target.value)} placeholder="mon-run" />

          <label htmlFor="arch" className="text-xs font-medium text-gray-400">Architecture</label>
          <select id="arch" className={inputCls} value={selectedArch} onChange={(e) => setSelectedArch(e.target.value)}>
            {architectures.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          {selectedArchInfo && <p className="text-[11px] leading-snug text-gray-500">{selectedArchInfo.description}</p>}

          <label htmlFor="ds" className="text-xs font-medium text-gray-400">Dataset</label>
          <select id="ds" className={inputCls} value={selectedDataset} onChange={(e) => setSelectedDataset(e.target.value)}>
            <option value="">— Données aléatoires (démo) —</option>
            {datasets.filter((d) => d.status === 'ready').map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>

          <div className="grid grid-cols-3 gap-2">
            <div className="flex flex-col gap-1">
              <label htmlFor="epochs" className="text-[11px] text-gray-400">Epochs</label>
              <input id="epochs" type="number" min={1} max={10000} value={epochs}
                onChange={(e) => setEpochs(Math.max(1, Number(e.target.value) || 1))} className={`${inputCls} p-1.5`} />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="batch" className="text-[11px] text-gray-400">Batch</label>
              <input id="batch" type="number" min={1} value={batchSize ?? 16}
                onChange={(e) => setBatchSize(Math.max(1, Number(e.target.value) || 1))} className={`${inputCls} p-1.5`} />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="lr" className="text-[11px] text-gray-400">LR</label>
              <input id="lr" type="number" step={0.0001} min={0} value={learningRate}
                onChange={(e) => setLearningRate(Number(e.target.value))} className={`${inputCls} p-1.5`} />
            </div>
          </div>

          <button
            onClick={handleCreateRun}
            disabled={creating || !selectedArch}
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
          <input className={inputCls} value={dsName} onChange={(e) => setDsName(e.target.value)} placeholder="Nom (optionnel)" aria-label="Nom du dataset" />
          <div className="flex gap-2">
            <input
              className={`${inputCls} min-w-0 flex-1`}
              value={dsHfId}
              onChange={(e) => setDsHfId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleDownloadDataset()}
              placeholder="Hugging Face (ex. mnist, cifar10)"
              aria-label="Identifiant Hugging Face"
            />
            <button
              onClick={handleDownloadDataset}
              disabled={!dsHfId.trim() || busy.hf}
              className="flex items-center gap-1 rounded-lg bg-gray-800 hover:bg-gray-700 disabled:opacity-50 px-2.5 text-xs text-gray-200"
              title="Télécharger depuis Hugging Face"
            >
              {busy.hf ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
            </button>
          </div>
          <input ref={fileRef} type="file" multiple className="hidden" onChange={(e) => handleUpload(e.target.files)} />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={busy.upload}
            className="flex items-center justify-center gap-2 rounded-lg border border-dashed border-gray-700 px-3 py-2 text-xs text-gray-400 hover:border-purple-500 hover:text-purple-300 disabled:opacity-50"
          >
            {uploadPct !== null ? (
              <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Import… {uploadPct}%</>
            ) : (
              <><Upload className="h-3.5 w-3.5" /> Importer des fichiers locaux</>
            )}
          </button>
          <ul className="flex flex-col gap-1">
            {datasets.length === 0 && <li className="text-[11px] text-gray-600">Aucun dataset.</li>}
            {datasets.map((d) => (
              <li key={d.id} className="group flex items-center justify-between gap-2 text-xs text-gray-300">
                <span className="min-w-0 truncate" title={d.error_message ?? undefined}>
                  {d.name}
                  <span className="ml-1 text-[10px] text-gray-600">
                    {d.num_samples ? `${d.num_samples} éléments` : ''} {formatBytes(d.size_bytes)}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-1">
                  <span className={`rounded-full px-2 py-0.5 text-[10px] ${STATUS_COLORS[d.status] ?? STATUS_COLORS.pending}`}>
                    {d.status === 'downloading' && <Loader2 className="mr-1 inline h-2.5 w-2.5 animate-spin" />}
                    {STATUS_LABELS[d.status] ?? d.status}
                  </span>
                  <button onClick={() => handleDeleteDataset(d)} disabled={busy[`ds-${d.id}`]}
                    className="rounded p-1 text-gray-600 hover:text-red-300" title="Supprimer">
                    <Trash2 className="h-3 w-3" />
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </section>
      </aside>

      {/* ── Right: runs ── */}
      <main className="flex-1 md:overflow-y-auto">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-400">
          <Cpu className="h-4 w-4" /> Entraînements
        </h2>
        {runs.length === 0 ? (
          <div className="flex h-48 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-gray-800 text-gray-600">
            <FlaskConical className="h-10 w-10" />
            <p className="text-sm">Aucun run — lancez un entraînement pour commencer</p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {runs.map((run) => {
              const history = (run.metrics_history ?? []).filter((m) => m.epoch !== undefined)
              const pct = run.total_epochs ? Math.round(((run.current_epoch ?? 0) / run.total_epochs) * 100) : 0
              return (
                <div key={run.id} className="rounded-xl border border-gray-800 bg-gray-900 p-3 flex flex-col gap-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-gray-100">{run.name}</p>
                      <p className="text-[11px] text-gray-500">
                        {run.architecture}
                        {run.hardware_snapshot?.accelerator && ` · ${run.hardware_snapshot.accelerator.toUpperCase()}`}
                      </p>
                    </div>
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${STATUS_COLORS[run.status] ?? STATUS_COLORS.pending}`}>
                      {STATUS_LABELS[run.status] ?? run.status}
                    </span>
                  </div>

                  {run.total_epochs ? (
                    <div className="space-y-1">
                      <div className="flex justify-between text-[11px] text-gray-500">
                        <span>epoch {run.current_epoch ?? 0} / {run.total_epochs}</span>
                        <span>{pct}%</span>
                      </div>
                      <div className="h-1.5 w-full rounded-full bg-gray-800">
                        <div className="h-1.5 rounded-full bg-purple-500 transition-all" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  ) : null}

                  {(run.status === 'running' || run.status === 'paused') && <RunLive run={run} onEpoch={appendEpoch} />}

                  {history.length >= 2 && (
                    <Suspense fallback={<div className="h-40" />}>
                      <MetricsChart data={history} />
                    </Suspense>
                  )}

                  {run.status === 'failed' && run.error_message && (
                    <p className="rounded bg-red-500/10 px-2 py-1 text-[11px] text-red-300 break-words">{run.error_message}</p>
                  )}

                  <div className="flex flex-wrap gap-2">
                    {isLive(run.status) && (
                      <>
                        {run.status === 'paused' ? (
                          <button onClick={() => control(`r-${run.id}`, () => resumeRun(run.id))} disabled={busy[`r-${run.id}`]}
                            className="flex items-center gap-1 rounded-lg bg-gray-800 hover:bg-gray-700 px-2.5 py-1 text-xs text-gray-200 disabled:opacity-50">
                            <Play className="h-3 w-3" /> Reprendre
                          </button>
                        ) : (
                          <button onClick={() => control(`p-${run.id}`, () => pauseRun(run.id))} disabled={busy[`p-${run.id}`]}
                            className="flex items-center gap-1 rounded-lg bg-gray-800 hover:bg-gray-700 px-2.5 py-1 text-xs text-gray-200 disabled:opacity-50">
                            <Pause className="h-3 w-3" /> Pause
                          </button>
                        )}
                        <button onClick={() => control(`s-${run.id}`, () => stopRun(run.id))} disabled={busy[`s-${run.id}`]}
                          className="flex items-center gap-1 rounded-lg bg-red-900/50 hover:bg-red-900 px-2.5 py-1 text-xs text-red-200 disabled:opacity-50">
                          {busy[`s-${run.id}`] ? <Loader2 className="h-3 w-3 animate-spin" /> : <Square className="h-3 w-3" />} Stop
                        </button>
                      </>
                    )}
                    {!isLive(run.status) && run.best_checkpoint_path && (
                      (['onnx', 'safetensors'] as const).map((fmt) => (
                        <button key={fmt} onClick={() => handleExport(run, fmt)} disabled={busy[`exp-${run.id}-${fmt}`]}
                          className="flex items-center gap-1 rounded-lg bg-gray-800 hover:bg-gray-700 px-2.5 py-1 text-xs text-gray-200 disabled:opacity-50"
                          title={`Exporter et télécharger au format ${fmt}`}>
                          {busy[`exp-${run.id}-${fmt}`] ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
                          {fmt === 'onnx' ? 'ONNX' : 'safetensors'}
                        </button>
                      ))
                    )}
                    {!isLive(run.status) && (
                      <button onClick={() => handleDeleteRun(run)} disabled={busy[`del-${run.id}`]}
                        className="ml-auto flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-gray-500 hover:text-red-300 disabled:opacity-50"
                        title="Supprimer le run">
                        <Trash2 className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </main>
    </div>
  )
}
