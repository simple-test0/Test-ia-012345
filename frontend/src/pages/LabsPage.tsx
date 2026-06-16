import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ChevronDown, Loader2, Upload, Download, Trash2, Play, Pause,
  Square, FlaskConical, Database, Cpu, BarChart2, CheckCircle2,
  XCircle, Clock, RefreshCw, Sparkles, Wand2,
} from 'lucide-react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import {
  getArchitectures, getDatasets, deleteDataset, downloadHFDataset, uploadDataset,
  getRuns, createRun, pauseRun, resumeRun, stopRun, exportRun, finetuneRun,
} from '../api/labs'
import { useHardwareInfo } from '../hooks/useHardwareInfo'
import { useWebSocket } from '../hooks/useWebSocket'
import { WS_BASE } from '../api/client'

// ─── Types ────────────────────────────────────────────────────────────────────

interface ParamSchema {
  type: 'integer' | 'float' | 'boolean' | 'select'
  min?: number
  max?: number
  options?: string[]
  label: string
}

interface Architecture {
  id: string
  name: string
  description: string
  task_types: string[]
  min_vram_mb: number
  default_config: Record<string, unknown>
  param_schema: Record<string, ParamSchema>
  tags: string[]
}

interface Dataset {
  id: string
  name: string
  source: 'huggingface' | 'upload'
  source_identifier?: string
  task_type: string
  num_samples?: number
  num_classes?: number
  status: 'downloading' | 'ready' | 'error'
  error_message?: string
  size_bytes?: number
  created_at?: string
}

type RunStatus = 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled'

interface EpochMetric {
  type: string
  epoch: number
  total_epochs?: number
  train_loss?: number
  val_loss?: number
  train_acc?: number
  val_acc?: number
  lr?: number
}

interface TrainingRun {
  id: string
  name: string
  status: RunStatus
  architecture: string
  arch_config: Record<string, unknown>
  training_config: Record<string, unknown>
  dataset_id?: string
  metrics_history?: EpochMetric[]
  current_epoch?: number
  total_epochs?: number
  error_message?: string
  created_at?: string
  completed_at?: string
}

interface TrainingConfig {
  epochs: number
  batch_size: number
  learning_rate: number
  optimizer: string
  lr_scheduler: string
  weight_decay: number
  gradient_clip_norm: number
  gradient_accumulation_steps: number
  use_mixed_precision: string
  label_smoothing: number
  early_stopping_patience: number
  torch_compile: boolean
}

// ─── Constants ────────────────────────────────────────────────────────────────

const TASK_TYPES = ['classification', 'detection', 'nlp']
const OPTIMIZERS = ['adamw', 'adam', 'sgd', 'rmsprop']
const SCHEDULERS = ['cosine', 'linear', 'onecycle', 'none']
const AMP_OPTIONS = ['fp16', 'bf16', 'no']

const STATUS_STYLES: Record<RunStatus, string> = {
  pending:   'bg-gray-500/20 text-gray-400 border border-gray-500/40',
  running:   'bg-blue-500/20 text-blue-300 border border-blue-500/40',
  paused:    'bg-yellow-500/20 text-yellow-300 border border-yellow-500/40',
  completed: 'bg-green-500/20 text-green-300 border border-green-500/40',
  failed:    'bg-red-500/20 text-red-300 border border-red-500/40',
  cancelled: 'bg-gray-500/20 text-gray-400 border border-gray-500/40',
}

const DS_STATUS_STYLES: Record<Dataset['status'], string> = {
  downloading: 'bg-blue-500/20 text-blue-300 border border-blue-500/40',
  ready:       'bg-green-500/20 text-green-300 border border-green-500/40',
  error:       'bg-red-500/20 text-red-300 border border-red-500/40',
}

const DEFAULT_TRAINING: TrainingConfig = {
  epochs: 10,
  batch_size: 16,
  learning_rate: 3e-4,
  optimizer: 'adamw',
  lr_scheduler: 'cosine',
  weight_decay: 1e-4,
  gradient_clip_norm: 1.0,
  gradient_accumulation_steps: 1,
  use_mixed_precision: 'fp16',
  label_smoothing: 0.0,
  early_stopping_patience: 0,
  torch_compile: false,
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtBytes(b?: number) {
  if (!b) return ''
  if (b < 1024) return `${b} B`
  if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`
  if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`
  return `${(b / 1024 ** 3).toFixed(2)} GB`
}

function fmtDate(s?: string) {
  if (!s) return ''
  return new Date(s).toLocaleString()
}

// ─── Metrics Chart ────────────────────────────────────────────────────────────

function MetricsChart({ data }: { data: EpochMetric[] }) {
  if (!data.length) return null
  return (
    <div className="h-44">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -10 }}>
          <XAxis dataKey="epoch" tick={{ fontSize: 10, fill: '#9ca3af' }} />
          <YAxis tick={{ fontSize: 10, fill: '#9ca3af' }} domain={['auto', 'auto']} />
          <Tooltip
            contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8, fontSize: 11 }}
            labelStyle={{ color: '#d1d5db' }}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: '#9ca3af' }} />
          <Line type="monotone" dataKey="train_loss" stroke="#a78bfa" dot={false} strokeWidth={1.5} name="Train Loss" />
          <Line type="monotone" dataKey="val_loss"   stroke="#fb923c" dot={false} strokeWidth={1.5} name="Val Loss" />
          <Line type="monotone" dataKey="train_acc"  stroke="#34d399" dot={false} strokeWidth={1.5} name="Train Acc" />
          <Line type="monotone" dataKey="val_acc"    stroke="#60a5fa" dot={false} strokeWidth={1.5} name="Val Acc" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─── Active Run Card (with live WS) ───────────────────────────────────────────

interface ActiveRunCardProps {
  run: TrainingRun
  onUpdated: (id: string, patch: Partial<TrainingRun>) => void
  onReinforce: (run: TrainingRun) => void
}

function ActiveRunCard({ run, onUpdated, onReinforce }: ActiveRunCardProps) {
  const [liveMetrics, setLiveMetrics] = useState<EpochMetric[]>(run.metrics_history ?? [])
  const [currentEpoch, setCurrentEpoch] = useState(run.current_epoch ?? 0)
  const [totalEpochs, setTotalEpochs] = useState(run.total_epochs ?? (run.training_config?.epochs as number) ?? 10)
  const [busy, setBusy] = useState(false)
  const onUpdatedRef = useRef(onUpdated)
  onUpdatedRef.current = onUpdated

  const isActive = run.status === 'running' || run.status === 'paused' || run.status === 'pending'

  useWebSocket(isActive ? `${WS_BASE}/ws/training/${run.id}` : null, {
    onMessage: (raw) => {
      const evt = raw as Record<string, unknown>
      if (evt.type === 'epoch_metric') {
        const m = evt as unknown as EpochMetric
        setCurrentEpoch(m.epoch)
        if (m.total_epochs) setTotalEpochs(m.total_epochs)
        setLiveMetrics(prev => [...prev, m])
        onUpdatedRef.current(run.id, { current_epoch: m.epoch, status: 'running' })
      } else if (evt.type === 'completed') {
        onUpdatedRef.current(run.id, { status: 'completed' })
      } else if (evt.type === 'error') {
        onUpdatedRef.current(run.id, { status: 'failed', error_message: evt.message as string })
      } else if (evt.type === 'status') {
        onUpdatedRef.current(run.id, { status: evt.status as RunStatus })
      }
    },
  })

  const pct = totalEpochs > 0 ? Math.round((currentEpoch / totalEpochs) * 100) : 0

  const handlePause = async () => {
    setBusy(true)
    try {
      await pauseRun(run.id)
      onUpdatedRef.current(run.id, { status: 'paused' })
    } finally { setBusy(false) }
  }

  const handleResume = async () => {
    setBusy(true)
    try {
      await resumeRun(run.id)
      onUpdatedRef.current(run.id, { status: 'running' })
    } finally { setBusy(false) }
  }

  const handleStop = async () => {
    setBusy(true)
    try {
      await stopRun(run.id)
      onUpdatedRef.current(run.id, { status: 'cancelled' })
    } finally { setBusy(false) }
  }

  const [exporting, setExporting] = useState(false)
  const handleExport = async (fmt: string) => {
    setExporting(true)
    try {
      await exportRun(run.id, fmt)
      const a = document.createElement('a')
      a.href = `/api/v1/labs/runs/${run.id}/export/download`
      a.download = `model_${run.id}.${fmt}`
      a.click()
    } catch { /* ignore */ } finally { setExporting(false) }
  }

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <span className="text-sm font-medium text-gray-100">{run.name}</span>
          <span className="text-[11px] text-gray-500">{run.architecture} · {fmtDate(run.created_at)}</span>
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${STATUS_STYLES[run.status]}`}>
          {run.status}
        </span>
      </div>

      {isActive && (
        <>
          <div className="flex items-center justify-between text-xs text-gray-400">
            <span>Epoch {currentEpoch} / {totalEpochs}</span>
            <span>{pct}%</span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-gray-800">
            <div
              className="h-1.5 rounded-full bg-emerald-500 transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>

          <div className="flex gap-2">
            {run.status === 'running' && (
              <button
                onClick={handlePause}
                disabled={busy}
                className="flex items-center gap-1 rounded-lg bg-yellow-500/10 border border-yellow-500/30
                  px-3 py-1.5 text-xs text-yellow-300 hover:bg-yellow-500/20 transition-colors disabled:opacity-50"
              >
                <Pause className="h-3 w-3" /> Pause
              </button>
            )}
            {run.status === 'paused' && (
              <button
                onClick={handleResume}
                disabled={busy}
                className="flex items-center gap-1 rounded-lg bg-blue-500/10 border border-blue-500/30
                  px-3 py-1.5 text-xs text-blue-300 hover:bg-blue-500/20 transition-colors disabled:opacity-50"
              >
                <Play className="h-3 w-3" /> Resume
              </button>
            )}
            <button
              onClick={handleStop}
              disabled={busy}
              className="flex items-center gap-1 rounded-lg bg-red-500/10 border border-red-500/30
                px-3 py-1.5 text-xs text-red-400 hover:bg-red-500/20 transition-colors disabled:opacity-50"
            >
              <Square className="h-3 w-3" /> Stop
            </button>
          </div>
        </>
      )}

      {liveMetrics.length > 0 && <MetricsChart data={liveMetrics} />}

      {run.status === 'completed' && (
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => onReinforce(run)}
            className="flex items-center gap-1 rounded-lg bg-emerald-500/10 border border-emerald-500/30
              px-3 py-1.5 text-xs text-emerald-300 hover:bg-emerald-500/20 transition-colors"
            title="Continue training from this model's best checkpoint"
          >
            <Sparkles className="h-3 w-3" /> Reinforce
          </button>
          {['onnx', 'safetensors'].map(fmt => (
            <button
              key={fmt}
              onClick={() => handleExport(fmt)}
              disabled={exporting}
              className="flex items-center gap-1 rounded-lg bg-purple-500/10 border border-purple-500/30
                px-3 py-1.5 text-xs text-purple-300 hover:bg-purple-500/20 transition-colors disabled:opacity-50"
            >
              <Download className="h-3 w-3" />
              {exporting ? 'Exporting…' : `Export ${fmt}`}
            </button>
          ))}
        </div>
      )}

      {run.status === 'failed' && run.error_message && (
        <p className="rounded-lg bg-red-500/10 border border-red-500/30 px-3 py-2 text-xs text-red-400">
          {run.error_message}
        </p>
      )}
    </div>
  )
}

// ─── Datasets Tab ─────────────────────────────────────────────────────────────

interface DatasetsTabProps {
  datasets: Dataset[]
  onRefresh: () => void
}

function DatasetsTab({ datasets, onRefresh }: DatasetsTabProps) {
  const [uploadName, setUploadName] = useState('')
  const [uploadTaskType, setUploadTaskType] = useState('classification')
  const [files, setFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)

  const [hfName, setHfName] = useState('')
  const [hfId, setHfId] = useState('')
  const [hfTaskType, setHfTaskType] = useState('classification')
  const [hfLoading, setHfLoading] = useState(false)

  const [deleteId, setDeleteId] = useState<string | null>(null)

  const handleUpload = async () => {
    if (!uploadName.trim() || !files.length) return
    setUploading(true)
    try {
      await uploadDataset(uploadName.trim(), uploadTaskType, files)
      setUploadName('')
      setFiles([])
      onRefresh()
    } catch { /* ignore */ } finally { setUploading(false) }
  }

  const handleHFDownload = async () => {
    if (!hfName.trim() || !hfId.trim()) return
    setHfLoading(true)
    try {
      await downloadHFDataset({ name: hfName.trim(), hf_id: hfId.trim(), task_type: hfTaskType })
      setHfName('')
      setHfId('')
      onRefresh()
    } catch { /* ignore */ } finally { setHfLoading(false) }
  }

  const handleDelete = async (id: string) => {
    setDeleteId(id)
    try {
      await deleteDataset(id)
      onRefresh()
    } catch { /* ignore */ } finally { setDeleteId(null) }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Upload */}
      <div className="rounded-xl bg-gray-900 border border-gray-800 p-3 flex flex-col gap-2">
        <p className="text-xs font-semibold text-gray-300 flex items-center gap-1.5">
          <Upload className="h-3.5 w-3.5" /> Upload Dataset
        </p>
        <input
          type="text"
          placeholder="Dataset name"
          value={uploadName}
          onChange={e => setUploadName(e.target.value)}
          className="rounded-lg bg-gray-800 border border-gray-700 px-2.5 py-1.5 text-xs text-gray-100
            focus:outline-none focus:border-purple-500 transition-colors placeholder-gray-600"
        />
        <SelectField value={uploadTaskType} onChange={setUploadTaskType} options={TASK_TYPES} />
        <label className="flex items-center gap-2 cursor-pointer rounded-lg border border-dashed
          border-gray-700 px-3 py-2 text-xs text-gray-500 hover:border-gray-500 transition-colors">
          <Upload className="h-3.5 w-3.5 shrink-0" />
          {files.length ? `${files.length} file(s) selected` : 'Choose files…'}
          <input type="file" multiple className="hidden" onChange={e => setFiles(Array.from(e.target.files ?? []))} />
        </label>
        <button
          onClick={handleUpload}
          disabled={uploading || !uploadName.trim() || !files.length}
          className="flex items-center justify-center gap-1.5 rounded-lg bg-purple-600 hover:bg-purple-500
            disabled:opacity-50 disabled:cursor-not-allowed px-3 py-1.5 text-xs font-medium text-white transition-colors"
        >
          {uploading ? <><Loader2 className="h-3 w-3 animate-spin" /> Uploading…</> : 'Upload'}
        </button>
      </div>

      {/* HuggingFace */}
      <div className="rounded-xl bg-gray-900 border border-gray-800 p-3 flex flex-col gap-2">
        <p className="text-xs font-semibold text-gray-300 flex items-center gap-1.5">
          <Download className="h-3.5 w-3.5" /> HuggingFace Dataset
        </p>
        <input
          type="text"
          placeholder="Name (e.g. MNIST)"
          value={hfName}
          onChange={e => setHfName(e.target.value)}
          className="rounded-lg bg-gray-800 border border-gray-700 px-2.5 py-1.5 text-xs text-gray-100
            focus:outline-none focus:border-purple-500 transition-colors placeholder-gray-600"
        />
        <input
          type="text"
          placeholder="HF id (e.g. ylecun/mnist)"
          value={hfId}
          onChange={e => setHfId(e.target.value)}
          className="rounded-lg bg-gray-800 border border-gray-700 px-2.5 py-1.5 text-xs text-gray-100
            focus:outline-none focus:border-purple-500 transition-colors placeholder-gray-600"
        />
        <SelectField value={hfTaskType} onChange={setHfTaskType} options={TASK_TYPES} />
        <button
          onClick={handleHFDownload}
          disabled={hfLoading || !hfName.trim() || !hfId.trim()}
          className="flex items-center justify-center gap-1.5 rounded-lg bg-blue-600 hover:bg-blue-500
            disabled:opacity-50 disabled:cursor-not-allowed px-3 py-1.5 text-xs font-medium text-white transition-colors"
        >
          {hfLoading ? <><Loader2 className="h-3 w-3 animate-spin" /> Downloading…</> : 'Download'}
        </button>
      </div>

      {/* Dataset list */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold text-gray-400">Datasets ({datasets.length})</p>
          <button onClick={onRefresh} className="text-gray-600 hover:text-gray-400 transition-colors">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
        {datasets.length === 0 ? (
          <p className="text-xs text-gray-600 text-center py-4">No datasets yet</p>
        ) : (
          datasets.map(ds => (
            <div key={ds.id} className="rounded-lg bg-gray-900 border border-gray-800 p-2.5 flex items-start justify-between gap-2">
              <div className="flex flex-col gap-0.5 min-w-0">
                <span className="text-xs font-medium text-gray-200 truncate">{ds.name}</span>
                <span className="text-[10px] text-gray-500">
                  {ds.source} · {ds.task_type}
                  {ds.num_samples ? ` · ${ds.num_samples.toLocaleString()} samples` : ''}
                  {ds.size_bytes ? ` · ${fmtBytes(ds.size_bytes)}` : ''}
                </span>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-medium ${DS_STATUS_STYLES[ds.status]}`}>
                  {ds.status}
                </span>
                <button
                  onClick={() => handleDelete(ds.id)}
                  disabled={deleteId === ds.id}
                  className="text-gray-600 hover:text-red-400 transition-colors disabled:opacity-50"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

// ─── Architecture Tab ─────────────────────────────────────────────────────────

interface ArchTabProps {
  architectures: Architecture[]
  selectedId: string
  onSelect: (id: string) => void
  archConfig: Record<string, unknown>
  onConfigChange: (key: string, value: unknown) => void
  vramMb: number
}

function ArchTab({ architectures, selectedId, onSelect, archConfig, onConfigChange, vramMb }: ArchTabProps) {
  const selected = architectures.find(a => a.id === selectedId)
  const fits = (a: Architecture) => vramMb <= 0 || a.min_vram_mb <= vramMb

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2">
        {architectures.map(arch => {
          const compatible = fits(arch)
          return (
            <button
              key={arch.id}
              onClick={() => onSelect(arch.id)}
              className={`relative rounded-xl border p-2.5 text-left transition-colors ${
                selectedId === arch.id
                  ? 'border-purple-500 bg-purple-500/10'
                  : 'border-gray-800 bg-gray-900 hover:border-gray-700'
              } ${compatible ? '' : 'opacity-70'}`}
            >
              <p className="text-xs font-semibold text-gray-200 leading-snug">{arch.name}</p>
              <div className="mt-1 flex flex-wrap gap-1">
                {arch.tags.includes('recommended') && (
                  <span className="rounded-full bg-emerald-500/20 border border-emerald-500/40 px-1.5 py-0.5 text-[9px] text-emerald-300">★ recommended</span>
                )}
                {arch.tags.filter(t => t !== 'recommended').map(t => (
                  <span key={t} className="rounded-full bg-gray-800 px-1.5 py-0.5 text-[9px] text-gray-400">{t}</span>
                ))}
              </div>
              <p className={`mt-1 text-[9px] ${compatible ? 'text-gray-600' : 'text-amber-400'}`}>
                {arch.min_vram_mb > 0 ? `Min VRAM: ${(arch.min_vram_mb / 1024).toFixed(1)} GB` : 'Runs on CPU'}
                {compatible ? '' : ' · exceeds detected VRAM'}
              </p>
            </button>
          )
        })}
      </div>

      {selected && (
        <div className="rounded-xl bg-gray-900 border border-gray-800 p-3 flex flex-col gap-2">
          <p className="text-xs text-gray-500 leading-relaxed">{selected.description}</p>
          <div className="border-t border-gray-800 pt-2 flex flex-col gap-2">
            <p className="text-xs font-semibold text-gray-400">Architecture config</p>
            {Object.entries(selected.param_schema).map(([key, schema]) => (
              <div key={key} className="flex flex-col gap-0.5">
                <label className="text-[10px] text-gray-500">{schema.label}</label>
                {schema.type === 'boolean' ? (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => onConfigChange(key, !(archConfig[key] ?? false))}
                      className={`w-8 h-4 rounded-full transition-colors ${archConfig[key] ? 'bg-purple-500' : 'bg-gray-700'}`}
                    >
                      <div className={`h-3 w-3 rounded-full bg-white mx-0.5 transition-transform ${archConfig[key] ? 'translate-x-4' : ''}`} />
                    </button>
                    <span className="text-xs text-gray-400">{archConfig[key] ? 'on' : 'off'}</span>
                  </div>
                ) : schema.type === 'select' ? (
                  <SelectField
                    value={String(archConfig[key] ?? schema.options?.[0] ?? '')}
                    onChange={v => onConfigChange(key, v)}
                    options={schema.options ?? []}
                  />
                ) : (
                  <input
                    type="number"
                    step={schema.type === 'float' ? 0.01 : 1}
                    min={schema.min}
                    max={schema.max}
                    value={(archConfig[key] as number) ?? 0}
                    onChange={e => onConfigChange(key, schema.type === 'float' ? parseFloat(e.target.value) : parseInt(e.target.value))}
                    className="rounded-lg bg-gray-800 border border-gray-700 px-2.5 py-1.5 text-xs text-gray-100
                      focus:outline-none focus:border-purple-500 transition-colors w-full"
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Training Tab ─────────────────────────────────────────────────────────────

interface TrainingTabProps {
  datasets: Dataset[]
  selectedDatasetId: string
  onDatasetSelect: (id: string) => void
  config: TrainingConfig
  onConfigChange: (key: keyof TrainingConfig, value: unknown) => void
  runName: string
  onRunNameChange: (v: string) => void
  onStart: () => void
  starting: boolean
  selectedArch: string
  onAutoTune: () => void
  autoTuneHint?: string
}

function TrainingTab({
  datasets, selectedDatasetId, onDatasetSelect,
  config, onConfigChange, runName, onRunNameChange,
  onStart, starting, selectedArch, onAutoTune, autoTuneHint,
}: TrainingTabProps) {
  const readyDatasets = datasets.filter(d => d.status === 'ready')

  return (
    <div className="flex flex-col gap-3">
      {autoTuneHint && (
        <button
          onClick={onAutoTune}
          className="flex items-center justify-center gap-1.5 rounded-xl bg-blue-500/10 border border-blue-500/30
            px-3 py-2 text-xs font-medium text-blue-300 hover:bg-blue-500/20 transition-colors"
        >
          <Wand2 className="h-3.5 w-3.5" /> Auto-tune for my GPU ({autoTuneHint})
        </button>
      )}

      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-gray-400">Run name</label>
        <input
          type="text"
          placeholder={`${selectedArch || 'model'}-run-1`}
          value={runName}
          onChange={e => onRunNameChange(e.target.value)}
          className="rounded-xl bg-gray-900 border border-gray-800 px-3 py-2 text-sm text-gray-100
            focus:outline-none focus:border-purple-500 transition-colors placeholder-gray-600"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-gray-400">Dataset <span className="text-gray-600">(optional)</span></label>
        <SelectField
          value={selectedDatasetId}
          onChange={onDatasetSelect}
          options={['', ...readyDatasets.map(d => d.id)]}
          labels={['None (use synthetic data)', ...readyDatasets.map(d => d.name)]}
        />
      </div>

      <div className="rounded-xl bg-gray-900 border border-gray-800 p-3 flex flex-col gap-2.5">
        <p className="text-xs font-semibold text-gray-400">Hyperparameters</p>

        <NumField label="Epochs" value={config.epochs} min={1} max={1000} step={1}
          onChange={v => onConfigChange('epochs', v)} />
        <NumField label="Batch size" value={config.batch_size} min={1} max={512} step={1}
          onChange={v => onConfigChange('batch_size', v)} />
        <NumField label="Learning rate" value={config.learning_rate} min={1e-6} max={1} step={1e-5}
          onChange={v => onConfigChange('learning_rate', v)} isFloat />
        <NumField label="Weight decay" value={config.weight_decay} min={0} max={1} step={1e-5}
          onChange={v => onConfigChange('weight_decay', v)} isFloat />
        <NumField label="Gradient clip norm" value={config.gradient_clip_norm} min={0} max={10} step={0.1}
          onChange={v => onConfigChange('gradient_clip_norm', v)} isFloat />
        <NumField label="Gradient accumulation steps" value={config.gradient_accumulation_steps} min={1} max={64} step={1}
          onChange={v => onConfigChange('gradient_accumulation_steps', v)} />
        <NumField label="Label smoothing" value={config.label_smoothing} min={0} max={0.3} step={0.01}
          onChange={v => onConfigChange('label_smoothing', v)} isFloat />
        <NumField label="Early stopping patience (0 = off)" value={config.early_stopping_patience} min={0} max={50} step={1}
          onChange={v => onConfigChange('early_stopping_patience', v)} />

        <div className="flex items-center justify-between gap-2">
          <label className="text-[10px] text-gray-500 shrink-0">torch.compile (faster, CUDA/XPU)</label>
          <button
            onClick={() => onConfigChange('torch_compile', !config.torch_compile)}
            className={`w-8 h-4 rounded-full transition-colors ${config.torch_compile ? 'bg-purple-500' : 'bg-gray-700'}`}
          >
            <div className={`h-3 w-3 rounded-full bg-white mx-0.5 transition-transform ${config.torch_compile ? 'translate-x-4' : ''}`} />
          </button>
        </div>

        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] text-gray-500">Optimizer</label>
          <SelectField value={config.optimizer} onChange={v => onConfigChange('optimizer', v)} options={OPTIMIZERS} />
        </div>
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] text-gray-500">LR Scheduler</label>
          <SelectField value={config.lr_scheduler} onChange={v => onConfigChange('lr_scheduler', v)} options={SCHEDULERS} />
        </div>
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] text-gray-500">Mixed precision</label>
          <SelectField value={config.use_mixed_precision} onChange={v => onConfigChange('use_mixed_precision', v)} options={AMP_OPTIONS} />
        </div>
      </div>

      <button
        onClick={onStart}
        disabled={starting || !selectedArch || !runName.trim()}
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600
          hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed
          px-4 py-3 text-sm font-semibold text-white transition-colors"
      >
        {starting ? (
          <><Loader2 className="h-4 w-4 animate-spin" /> Starting…</>
        ) : (
          <><Play className="h-4 w-4" /> Start Training</>
        )}
      </button>
    </div>
  )
}

// ─── Tiny helpers ─────────────────────────────────────────────────────────────

function SelectField({
  value, onChange, options, labels,
}: { value: string; onChange: (v: string) => void; options: string[]; labels?: string[] }) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full appearance-none rounded-lg bg-gray-800 border border-gray-700 px-2.5 py-1.5 pr-7
          text-xs text-gray-100 focus:outline-none focus:border-purple-500 transition-colors cursor-pointer"
      >
        {options.map((o, i) => (
          <option key={o} value={o}>{labels?.[i] ?? o}</option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 top-2 h-3.5 w-3.5 text-gray-500" />
    </div>
  )
}

function NumField({
  label, value, min, max, step, onChange, isFloat,
}: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; isFloat?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <label className="text-[10px] text-gray-500 shrink-0">{label}</label>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={e => onChange(isFloat ? parseFloat(e.target.value) : parseInt(e.target.value))}
        className="w-28 rounded-lg bg-gray-800 border border-gray-700 px-2 py-1 text-xs text-gray-100
          text-right focus:outline-none focus:border-purple-500 transition-colors"
      />
    </div>
  )
}

// ─── Run History Card ─────────────────────────────────────────────────────────

function RunHistoryCard({ run, onReinforce }: { run: TrainingRun; onReinforce: (run: TrainingRun) => void }) {
  const [expanded, setExpanded] = useState(false)
  const [exporting, setExporting] = useState(false)

  const handleExport = async (fmt: string) => {
    setExporting(true)
    try {
      await exportRun(run.id, fmt)
      const a = document.createElement('a')
      a.href = `/api/v1/labs/runs/${run.id}/export/download`
      a.download = `model_${run.id}.${fmt}`
      a.click()
    } catch { /* ignore */ } finally { setExporting(false) }
  }

  const Icon = run.status === 'completed' ? CheckCircle2 : run.status === 'failed' ? XCircle : Clock

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 overflow-hidden">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-start justify-between gap-2 p-3 hover:bg-gray-800/50 transition-colors text-left"
      >
        <div className="flex items-start gap-2 min-w-0">
          <Icon className={`h-4 w-4 shrink-0 mt-0.5 ${
            run.status === 'completed' ? 'text-green-400' :
            run.status === 'failed' ? 'text-red-400' : 'text-gray-500'
          }`} />
          <div className="flex flex-col gap-0.5 min-w-0">
            <span className="text-sm font-medium text-gray-200 truncate">{run.name}</span>
            <span className="text-[10px] text-gray-500">
              {run.architecture}
              {run.total_epochs ? ` · ${run.current_epoch ?? 0}/${run.total_epochs} epochs` : ''}
              {run.completed_at ? ` · ${fmtDate(run.completed_at)}` : run.created_at ? ` · ${fmtDate(run.created_at)}` : ''}
            </span>
            {run.metrics_history && run.metrics_history.length > 0 && (() => {
              const last = run.metrics_history[run.metrics_history.length - 1]
              return (
                <span className="text-[10px] text-gray-600">
                  {last.val_loss !== undefined ? `Val Loss: ${last.val_loss.toFixed(4)}` : ''}
                  {last.val_acc !== undefined ? ` · Val Acc: ${(last.val_acc * 100).toFixed(1)}%` : ''}
                </span>
              )
            })()}
          </div>
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${STATUS_STYLES[run.status]}`}>
          {run.status}
        </span>
      </button>

      {expanded && (
        <div className="px-3 pb-3 flex flex-col gap-3 border-t border-gray-800">
          {run.metrics_history && run.metrics_history.length > 0 && (
            <div className="pt-3">
              <MetricsChart data={run.metrics_history} />
            </div>
          )}
          {run.error_message && (
            <p className="rounded-lg bg-red-500/10 border border-red-500/30 px-3 py-2 text-xs text-red-400">
              {run.error_message}
            </p>
          )}
          {run.status === 'completed' && (
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => onReinforce(run)}
                className="flex items-center gap-1 rounded-lg bg-emerald-500/10 border border-emerald-500/30
                  px-3 py-1.5 text-xs text-emerald-300 hover:bg-emerald-500/20 transition-colors"
                title="Continue training from this model's best checkpoint"
              >
                <Sparkles className="h-3 w-3" /> Reinforce
              </button>
              {['onnx', 'safetensors'].map(fmt => (
                <button
                  key={fmt}
                  onClick={() => handleExport(fmt)}
                  disabled={exporting}
                  className="flex items-center gap-1 rounded-lg bg-purple-500/10 border border-purple-500/30
                    px-3 py-1.5 text-xs text-purple-300 hover:bg-purple-500/20 transition-colors disabled:opacity-50"
                >
                  <Download className="h-3 w-3" /> Export {fmt}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

type LeftTab = 'datasets' | 'architecture' | 'training'

export default function LabsPage() {
  const [leftTab, setLeftTab] = useState<LeftTab>('architecture')

  // Data
  const [architectures, setArchitectures] = useState<Architecture[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [runs, setRuns] = useState<TrainingRun[]>([])

  // Selection / config
  const [selectedArch, setSelectedArch] = useState('')
  const [archConfig, setArchConfig] = useState<Record<string, unknown>>({})
  const [trainingConfig, setTrainingConfig] = useState<TrainingConfig>(DEFAULT_TRAINING)
  const [selectedDatasetId, setSelectedDatasetId] = useState('')
  const [runName, setRunName] = useState('')
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Hardware-aware tuning.
  const { hardware, recommendations } = useHardwareInfo(15000)
  const vramMb = (() => {
    const gpus = (hardware?.gpus as Array<Record<string, unknown>>) || []
    return (gpus[0]?.vram_total_mb as number) ?? 0
  })()
  const trainingRec = recommendations?.training as Record<string, unknown> | undefined
  const autoTuneHint = trainingRec
    ? `bs ${trainingRec.recommended_batch_size}, ${trainingRec.use_mixed_precision}`
    : undefined

  const fetchDatasets = useCallback(() => {
    getDatasets().then(setDatasets).catch(() => {})
  }, [])

  const fetchRuns = useCallback(() => {
    getRuns().then(setRuns).catch(() => {})
  }, [])

  useEffect(() => {
    getArchitectures().then((data: Architecture[]) => {
      setArchitectures(data)
      if (data.length) {
        setSelectedArch(data[0].id)
        setArchConfig({ ...data[0].default_config })
      }
    }).catch(() => {})
    fetchDatasets()
    fetchRuns()
  }, [fetchDatasets, fetchRuns])

  const handleArchSelect = (id: string) => {
    const arch = architectures.find(a => a.id === id)
    if (arch) {
      setSelectedArch(id)
      setArchConfig({ ...arch.default_config })
    }
  }

  const handleArchConfigChange = (key: string, value: unknown) => {
    setArchConfig(prev => ({ ...prev, [key]: value }))
  }

  const handleTrainingConfigChange = (key: keyof TrainingConfig, value: unknown) => {
    setTrainingConfig(prev => ({ ...prev, [key]: value }))
  }

  const handleStartTraining = async () => {
    if (!selectedArch || !runName.trim()) return
    setStarting(true)
    setError(null)
    try {
      const result = await createRun({
        name: runName.trim(),
        architecture: selectedArch,
        arch_config: archConfig,
        training_config: trainingConfig,
        dataset_id: selectedDatasetId || undefined,
      })
      const newRun: TrainingRun = {
        id: result.id,
        name: runName.trim(),
        status: 'running',
        architecture: selectedArch,
        arch_config: archConfig,
        training_config: trainingConfig as unknown as Record<string, unknown>,
        dataset_id: selectedDatasetId || undefined,
        total_epochs: trainingConfig.epochs,
        current_epoch: 0,
        created_at: new Date().toISOString(),
        metrics_history: [],
      }
      setRuns(prev => [newRun, ...prev])
      setRunName('')
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to start training'
      setError(msg)
    } finally {
      setStarting(false)
    }
  }

  const handleAutoTune = () => {
    if (!trainingRec) return
    setTrainingConfig(prev => ({
      ...prev,
      batch_size: (trainingRec.recommended_batch_size as number) ?? prev.batch_size,
      gradient_accumulation_steps: (trainingRec.gradient_accumulation_steps as number) ?? prev.gradient_accumulation_steps,
      use_mixed_precision: (trainingRec.use_mixed_precision as string) ?? prev.use_mixed_precision,
      torch_compile: Boolean(trainingRec.enable_torch_compile),
    }))
  }

  const handleRunUpdated = useCallback((id: string, patch: Partial<TrainingRun>) => {
    setRuns(prev => prev.map(r => r.id === id ? { ...r, ...patch } : r))
  }, [])

  const handleReinforce = useCallback(async (run: TrainingRun) => {
    try {
      const result = await finetuneRun(run.id, {})
      const child: TrainingRun = {
        id: result.id,
        name: `${run.name} · reinforce`,
        status: 'running',
        architecture: run.architecture,
        arch_config: run.arch_config,
        training_config: run.training_config,
        total_epochs: 5,
        current_epoch: 0,
        created_at: new Date().toISOString(),
        metrics_history: [],
      }
      setRuns(prev => [child, ...prev])
    } catch {
      setError('Failed to start reinforcement run')
    }
  }, [])

  const activeRuns = runs.filter(r => r.status === 'running' || r.status === 'paused' || r.status === 'pending')
  const pastRuns = runs.filter(r => r.status === 'completed' || r.status === 'failed' || r.status === 'cancelled')

  const LEFT_TABS: { id: LeftTab; label: string; icon: typeof Database }[] = [
    { id: 'architecture', label: 'Model', icon: Cpu },
    { id: 'training', label: 'Train', icon: FlaskConical },
    { id: 'datasets', label: 'Data', icon: Database },
  ]

  return (
    <div className="flex h-full gap-4 p-4 overflow-hidden">
      {/* ── Left Panel ── */}
      <aside className="w-[38%] shrink-0 flex flex-col gap-3 overflow-hidden">
        {/* Tab switcher */}
        <div className="flex rounded-xl bg-gray-900 border border-gray-800 p-1 gap-1">
          {LEFT_TABS.map(tab => {
            const Icon = tab.icon
            return (
              <button
                key={tab.id}
                onClick={() => setLeftTab(tab.id)}
                className={`flex-1 flex items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium transition-colors ${
                  leftTab === tab.id
                    ? 'bg-gray-800 text-gray-100'
                    : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {tab.label}
              </button>
            )
          })}
        </div>

        <div className="overflow-y-auto flex-1 pr-0.5">
          {leftTab === 'datasets' && (
            <DatasetsTab datasets={datasets} onRefresh={fetchDatasets} />
          )}

          {leftTab === 'architecture' && (
            <ArchTab
              architectures={architectures}
              selectedId={selectedArch}
              onSelect={handleArchSelect}
              archConfig={archConfig}
              onConfigChange={handleArchConfigChange}
              vramMb={vramMb}
            />
          )}

          {leftTab === 'training' && (
            <>
              {error && (
                <p className="mb-3 rounded-lg bg-red-500/10 border border-red-500/30 px-3 py-2 text-xs text-red-400">
                  {error}
                </p>
              )}
              <TrainingTab
                datasets={datasets}
                selectedDatasetId={selectedDatasetId}
                onDatasetSelect={setSelectedDatasetId}
                config={trainingConfig}
                onConfigChange={handleTrainingConfigChange}
                runName={runName}
                onRunNameChange={setRunName}
                onStart={handleStartTraining}
                starting={starting}
                selectedArch={selectedArch}
                onAutoTune={handleAutoTune}
                autoTuneHint={autoTuneHint}
              />
            </>
          )}
        </div>
      </aside>

      {/* ── Right Panel ── */}
      <main className="flex-1 overflow-y-auto flex flex-col gap-4">
        {/* Active runs */}
        {activeRuns.length > 0 && (
          <section className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-gray-300">Active Runs</h2>
              <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            </div>
            {activeRuns.map(run => (
              <ActiveRunCard key={run.id} run={run} onUpdated={handleRunUpdated} onReinforce={handleReinforce} />
            ))}
          </section>
        )}

        {/* Past runs */}
        <section className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-400">
              <BarChart2 className="inline h-4 w-4 mr-1 mb-0.5" />
              Run History
            </h2>
            <button onClick={fetchRuns} className="text-gray-600 hover:text-gray-400 transition-colors">
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </div>
          {pastRuns.length === 0 && activeRuns.length === 0 ? (
            <div className="flex h-48 flex-col items-center justify-center gap-3 rounded-xl
              border border-dashed border-gray-800 text-gray-600">
              <FlaskConical className="h-10 w-10" />
              <p className="text-sm">No runs yet — configure a model and start training</p>
            </div>
          ) : pastRuns.length === 0 ? (
            <p className="text-xs text-gray-600 py-2">No completed runs yet</p>
          ) : (
            pastRuns.map(run => <RunHistoryCard key={run.id} run={run} onReinforce={handleReinforce} />)
          )}
        </section>
      </main>
    </div>
  )
}
