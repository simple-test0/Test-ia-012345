import { useEffect, useRef, useState } from 'react'
import { Loader2, ImageIcon, ChevronDown, Plus } from 'lucide-react'
import { generateImage, getModels, getJobs, getHFModelStatus } from '../api/image'
import type { GenerationMode, ControlNetType } from '../api/image'
import { useWebSocket } from '../hooks/useWebSocket'
import { wsUrl } from '../api/client'
import HFModelBrowser from '../components/image/HFModelBrowser'
import ImageUploadField from '../components/image/ImageUploadField'
import { toast } from '../components/ui/toast'

// ─── Types ───────────────────────────────────────────────────────────────────

interface ImageModel {
  id: string
  name: string
  source: 'curated' | 'downloaded'
  recommended: boolean
  status: 'ready' | 'downloading' | 'error'
  compatible: boolean
  repo_id: string
  tags?: string[]
  gated?: boolean
}

interface ImageJob {
  job_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  prompt: string
  created_at: string
  images?: string[] // base64 data URLs
  queue_position?: number
  mode?: GenerationMode
  error_message?: string
}

interface GenerateParams {
  prompt: string
  negative_prompt: string
  model_id: string
  sampler: string
  steps: number
  cfg_scale: number
  width: number
  height: number
  seed: number
  num_images: number
  lora?: string
  mode?: GenerationMode
  init_image?: string
  strength?: number
  controlnet_type?: ControlNetType
  control_image?: string
}

interface WsStepEvent {
  type: 'step'
  step: number
  total_steps: number
  preview?: string // base64
}

interface WsCompletedEvent {
  type: 'completed'
  images: string[] // base64
}

interface WsQueueEvent {
  type: 'queued'
  position: number
}

interface WsErrorEvent {
  type: 'error'
  message?: string
}

interface WsStartedEvent {
  type: 'started'
  job_id: string
}

type WsEvent = WsStepEvent | WsCompletedEvent | WsQueueEvent | WsErrorEvent | WsStartedEvent

// ─── Constants ───────────────────────────────────────────────────────────────

const SAMPLERS = ['DPM++ 2M', 'Euler', 'Euler a', 'DDIM', 'LMS']
const PIXEL_SIZES = [512, 768, 1024]
const NUM_IMAGES_OPTIONS = [1, 2, 3, 4]

const MODES: { id: GenerationMode; label: string }[] = [
  { id: 'txt2img', label: 'Texte → Image' },
  { id: 'img2img', label: 'Image → Image' },
  { id: 'controlnet', label: 'ControlNet' },
]

const CONTROLNET_TYPES: { id: ControlNetType; label: string; hint: string }[] = [
  { id: 'canny', label: 'Canny (contours)', hint: "Les contours sont extraits automatiquement de l'image." },
  { id: 'depth', label: 'Depth (profondeur)', hint: 'Fournissez une carte de profondeur déjà calculée.' },
  { id: 'pose', label: 'Pose (OpenPose)', hint: 'Fournissez un squelette OpenPose déjà calculé.' },
]

const STATUS_COLORS: Record<ImageJob['status'], string> = {
  queued: 'bg-yellow-500/20 text-yellow-300 border border-yellow-500/40',
  running: 'bg-blue-500/20 text-blue-300 border border-blue-500/40',
  completed: 'bg-green-500/20 text-green-300 border border-green-500/40',
  failed: 'bg-red-500/20 text-red-300 border border-red-500/40',
}

// ─── Active Job WS Progress ───────────────────────────────────────────────────

interface ActiveJobProgressProps {
  jobId: string
  onCompleted: (images: string[]) => void
  onFailed: (message: string) => void
}

function ActiveJobProgress({ jobId, onCompleted, onFailed }: ActiveJobProgressProps) {
  const [step, setStep] = useState(0)
  const [totalSteps, setTotalSteps] = useState(0)
  const [preview, setPreview] = useState<string | null>(null)
  const onCompletedRef = useRef(onCompleted)
  onCompletedRef.current = onCompleted
  const onFailedRef = useRef(onFailed)
  onFailedRef.current = onFailed

  useWebSocket(wsUrl(`/ws/image/${jobId}`), {
    onMessage: (raw) => {
      const evt = raw as WsEvent
      if (evt.type === 'step') {
        setStep(evt.step)
        setTotalSteps(evt.total_steps)
        if (evt.preview) setPreview(evt.preview)
      } else if (evt.type === 'completed') {
        onCompletedRef.current(evt.images)
      } else if (evt.type === 'error') {
        onFailedRef.current(evt.message || 'La génération a échoué')
      }
    },
  })

  const pct = totalSteps > 0 ? Math.round((step / totalSteps) * 100) : 0

  return (
    <div className="mt-2 space-y-2">
      <div className="flex items-center justify-between text-xs text-gray-400">
        <span>Step {step} / {totalSteps}</span>
        <span>{pct}%</span>
      </div>
      <div className="h-2 w-full rounded-full bg-gray-700">
        <div
          className="h-2 rounded-full bg-purple-500 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      {preview && (
        <img
          src={preview}
          alt="Latent preview"
          className="mt-2 w-full rounded-lg object-contain opacity-80"
        />
      )}
    </div>
  )
}

// ─── Job Card ─────────────────────────────────────────────────────────────────

interface JobCardProps {
  job: ImageJob
  onJobCompleted: (jobId: string, images: string[]) => void
  onJobFailed: (jobId: string, message: string) => void
}

function JobCard({ job, onJobCompleted, onJobFailed }: JobCardProps) {
  return (
    <div className="rounded-xl bg-gray-900 border border-gray-800 p-3 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs text-gray-300 line-clamp-2 flex-1">{job.prompt}</p>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${STATUS_COLORS[job.status]}`}>
          {job.status}
        </span>
      </div>

      {job.status === 'running' && (
        <ActiveJobProgress
          jobId={job.job_id}
          onCompleted={(images) => onJobCompleted(job.job_id, images)}
          onFailed={(message) => onJobFailed(job.job_id, message)}
        />
      )}

      {job.status === 'completed' && job.images && job.images.length > 0 && (
        <div className={`grid gap-1 ${job.images.length === 1 ? 'grid-cols-1' : 'grid-cols-2'}`}>
          {job.images.map((img, i) => (
            <img
              key={i}
              src={img}
              alt={`Generated ${i + 1}`}
              className="w-full rounded-lg object-cover aspect-square"
            />
          ))}
        </div>
      )}

      {job.status === 'completed' && (!job.images || job.images.length === 0) && (
        <div className="flex h-24 items-center justify-center rounded-lg bg-gray-800">
          <ImageIcon className="h-8 w-8 text-gray-600" />
        </div>
      )}

      {job.status === 'queued' && job.queue_position !== undefined && (
        <p className="text-xs text-yellow-400">Queue position: {job.queue_position}</p>
      )}

      {job.status === 'failed' && (
        <p className="text-xs text-red-400">{job.error_message || 'La génération a échoué'}</p>
      )}

      <p className="text-[10px] text-gray-600">{new Date(job.created_at).toLocaleString()}</p>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ImageGenerationPage() {
  // Form state
  const [prompt, setPrompt] = useState('')
  const [negativePrompt, setNegativePrompt] = useState('')
  const [models, setModels] = useState<ImageModel[]>([])
  const [selectedModel, setSelectedModel] = useState('')
  const [sampler, setSampler] = useState('DPM++ 2M')
  const [steps, setSteps] = useState(20)
  const [cfgScale, setCfgScale] = useState(7.5)
  const [width, setWidth] = useState(512)
  const [height, setHeight] = useState(512)
  const [seed, setSeed] = useState(-1)
  const [numImages, setNumImages] = useState(1)
  const [lora, setLora] = useState('')

  // Generation mode (txt2img / img2img / controlnet)
  const [mode, setMode] = useState<GenerationMode>('txt2img')
  const [initImage, setInitImage] = useState<string | null>(null)
  const [strength, setStrength] = useState(0.8)
  const [cnType, setCnType] = useState<ControlNetType>('canny')
  const [controlImage, setControlImage] = useState<string | null>(null)

  // UI state
  const [loading, setLoading] = useState(false)
  const [queuePosition, setQueuePosition] = useState<number | null>(null)
  const [jobs, setJobs] = useState<ImageJob[]>([])
  const [error, setError] = useState<string | null>(null)

  // Active job WS (for queue status on the newly submitted job)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)

  // Hugging Face model browser + download tracking
  const [showBrowser, setShowBrowser] = useState(false)
  const [downloadingModels, setDownloadingModels] = useState<Record<string, number>>({})

  useWebSocket(activeJobId ? wsUrl(`/ws/image/${activeJobId}`) : null, {
    onMessage: (raw) => {
      const evt = raw as WsEvent
      if (evt.type === 'queued') {
        setQueuePosition(evt.position)
      } else if (evt.type === 'started' || evt.type === 'step') {
        // Flip the freshly submitted job to running so its card streams progress.
        setQueuePosition(null)
        const id = activeJobId
        if (id) {
          setJobs((prev) =>
            prev.map((j) =>
              j.job_id === id && j.status === 'queued' ? { ...j, status: 'running' as const } : j
            )
          )
        }
      } else if (evt.type === 'completed') {
        setQueuePosition(null)
        if (activeJobId) handleJobCompleted(activeJobId, evt.images)
        setActiveJobId(null)
      } else if (evt.type === 'error') {
        setQueuePosition(null)
        if (activeJobId) handleJobFailed(activeJobId, evt.message || 'La génération a échoué')
        setActiveJobId(null)
      }
    },
  })

  // Fetch models
  const refreshModels = (autoSelect = false) =>
    getModels()
      .then((data: ImageModel[]) => {
        setModels(data)
        if (autoSelect && !selectedModel) {
          const first = data.find((m) => m.status === 'ready')
          if (first) setSelectedModel(first.id)
        }
      })
      .catch(() => setError('Failed to load models'))

  useEffect(() => {
    refreshModels(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Poll status of in-progress HF model downloads.
  useEffect(() => {
    const ids = Object.keys(downloadingModels)
    if (ids.length === 0) return
    const interval = setInterval(() => {
      ids.forEach((id) => {
        getHFModelStatus(id)
          .then((m: { status: string; progress?: number; error_message?: string }) => {
            if (m.status === 'ready') {
              setDownloadingModels((prev) => {
                const next = { ...prev }
                delete next[id]
                return next
              })
              refreshModels()
              toast.success('Modèle téléchargé et prêt à l\'emploi.')
            } else if (m.status === 'error') {
              setDownloadingModels((prev) => {
                const next = { ...prev }
                delete next[id]
                return next
              })
              const msg = m.error_message || 'Le téléchargement du modèle a échoué.'
              setError(msg)
              toast.error(msg)
            } else {
              setDownloadingModels((prev) => ({ ...prev, [id]: m.progress ?? 0 }))
            }
          })
          .catch(() => {})
      })
    }, 3000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [downloadingModels])

  const handleDownloadStarted = (modelId: string) => {
    setDownloadingModels((prev) => ({ ...prev, [modelId]: 0 }))
    refreshModels()
  }

  // Fetch job history
  useEffect(() => {
    getJobs()
      .then((data: ImageJob[]) => setJobs(data))
      .catch(() => {})
  }, [])

  const canGenerate =
    prompt.trim() !== '' &&
    (mode !== 'img2img' || initImage !== null) &&
    (mode !== 'controlnet' || controlImage !== null)

  const handleGenerate = async () => {
    if (!canGenerate) return
    setLoading(true)
    setError(null)
    setQueuePosition(null)

    const params: GenerateParams = {
      prompt,
      negative_prompt: negativePrompt,
      model_id: selectedModel,
      sampler,
      steps,
      cfg_scale: cfgScale,
      width,
      height,
      seed,
      num_images: numImages,
      lora: lora.trim() || undefined,
      mode,
      ...(mode === 'img2img' && { init_image: initImage ?? undefined, strength }),
      ...(mode === 'controlnet' && {
        controlnet_type: cnType,
        control_image: controlImage ?? undefined,
      }),
    }

    try {
      const result = await generateImage(params)
      const newJob: ImageJob = {
        job_id: result.job_id,
        status: result.status ?? 'queued',
        prompt,
        mode,
        created_at: new Date().toISOString(),
        queue_position: result.queue_position,
      }
      setJobs((prev) => [newJob, ...prev])
      setActiveJobId(result.job_id)
    } catch (e) {
      // Surface the backend's message (e.g. invalid mode inputs, model not
      // ready) instead of a generic one when available.
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'La génération a échoué. Réessayez.')
    } finally {
      setLoading(false)
    }
  }

  const handleJobCompleted = (jobId: string, images: string[]) => {
    setJobs((prev) =>
      prev.map((j) =>
        j.job_id === jobId ? { ...j, status: 'completed' as const, images } : j
      )
    )
  }

  const handleJobFailed = (jobId: string, message: string) => {
    setJobs((prev) =>
      prev.map((j) =>
        j.job_id === jobId ? { ...j, status: 'failed' as const, error_message: message } : j
      )
    )
    toast.error(message)
  }

  return (
    <div className="flex h-full gap-4 p-4 overflow-hidden">
      {/* ── Left Panel ── */}
      <aside className="w-[35%] shrink-0 flex flex-col gap-3 overflow-y-auto pr-1">
        {/* Mode Tabs */}
        <div className="grid grid-cols-3 gap-1 rounded-xl bg-gray-900 border border-gray-800 p-1">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => setMode(m.id)}
              className={`rounded-lg px-2 py-1.5 text-xs font-medium transition-colors ${
                mode === m.id
                  ? 'bg-purple-600 text-white'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>

        {/* img2img inputs */}
        {mode === 'img2img' && (
          <>
            <ImageUploadField
              label="Image source"
              value={initImage}
              onChange={setInitImage}
            />
            <div className="flex flex-col gap-1">
              <div className="flex justify-between">
                <label className="text-xs font-medium text-gray-400">
                  Strength <span className="text-gray-600">(fidélité à l'image source)</span>
                </label>
                <span className="text-xs text-purple-400 font-mono">{strength.toFixed(2)}</span>
              </div>
              <input
                type="range" min={0.05} max={1} step={0.05} value={strength}
                onChange={(e) => setStrength(Number(e.target.value))}
                className="w-full accent-purple-500 cursor-pointer"
              />
              <p className="text-[10px] text-gray-600">
                Faible = proche de l'image source, élevé = plus créatif.
              </p>
            </div>
          </>
        )}

        {/* ControlNet inputs */}
        {mode === 'controlnet' && (
          <>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-400">Type de contrôle</label>
              <div className="relative">
                <select
                  className="w-full appearance-none rounded-xl bg-gray-900 border border-gray-800 p-3 pr-8
                    text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors cursor-pointer"
                  value={cnType}
                  onChange={(e) => setCnType(e.target.value as ControlNetType)}
                >
                  {CONTROLNET_TYPES.map((t) => (
                    <option key={t.id} value={t.id}>{t.label}</option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-3 top-3.5 h-4 w-4 text-gray-500" />
              </div>
            </div>
            <ImageUploadField
              label="Image de contrôle"
              hint={CONTROLNET_TYPES.find((t) => t.id === cnType)?.hint}
              value={controlImage}
              onChange={setControlImage}
            />
            <p className="rounded-lg bg-blue-500/10 border border-blue-500/30 px-3 py-2 text-[10px] text-blue-300">
              ControlNet est disponible pour les modèles SD 1.5 et SDXL.
            </p>
          </>
        )}

        {/* Positive Prompt */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-400">Prompt</label>
          <textarea
            className="rounded-xl bg-gray-900 border border-gray-800 p-3 text-sm text-gray-100
              resize-none h-28 focus:outline-none focus:border-purple-500 transition-colors placeholder-gray-600"
            placeholder="Describe the image you want to generate..."
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
        </div>

        {/* Negative Prompt */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-400">Negative Prompt</label>
          <textarea
            className="rounded-xl bg-gray-900 border border-gray-800 p-3 text-sm text-gray-100
              resize-none h-16 focus:outline-none focus:border-purple-500 transition-colors placeholder-gray-600"
            placeholder="Things to avoid..."
            value={negativePrompt}
            onChange={(e) => setNegativePrompt(e.target.value)}
          />
        </div>

        {/* Model Selector */}
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <label className="text-xs font-medium text-gray-400">Model</label>
            <button
              type="button"
              onClick={() => setShowBrowser(true)}
              className="flex items-center gap-1 text-[11px] font-medium text-purple-400 hover:text-purple-300"
            >
              <Plus className="h-3 w-3" /> Ajouter un modèle
            </button>
          </div>
          <div className="relative">
            <select
              className="w-full appearance-none rounded-xl bg-gray-900 border border-gray-800 p-3 pr-8
                text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors cursor-pointer"
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
            >
              {models.length === 0 && <option value="">No models found</option>}
              {(() => {
                const curated = models.filter((m) => m.source === 'curated')
                const downloaded = models.filter((m) => m.source === 'downloaded')
                const optionLabel = (m: ImageModel) => {
                  let label = m.name
                  if (m.status === 'downloading') label += ' (téléchargement…)'
                  else if (m.status === 'error') label += ' (erreur)'
                  else if (!m.compatible) label += ' — VRAM insuffisante'
                  return label
                }
                return (
                  <>
                    {curated.length > 0 && (
                      <optgroup label="Recommandés">
                        {curated.map((m) => (
                          <option key={m.id} value={m.id}>
                            {optionLabel(m)}
                          </option>
                        ))}
                      </optgroup>
                    )}
                    {downloaded.length > 0 && (
                      <optgroup label="Téléchargés">
                        {downloaded.map((m) => (
                          <option key={m.id} value={m.id} disabled={m.status !== 'ready'}>
                            {optionLabel(m)}
                          </option>
                        ))}
                      </optgroup>
                    )}
                  </>
                )
              })()}
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-3.5 h-4 w-4 text-gray-500" />
          </div>
          {Object.keys(downloadingModels).length > 0 && (() => {
            const vals = Object.values(downloadingModels)
            const avg = Math.round(vals.reduce((a, b) => a + b, 0) / vals.length)
            return (
              <span className="flex items-center gap-1.5 self-start rounded-full bg-purple-500/15
                border border-purple-500/30 px-2 py-0.5 text-[10px] text-purple-300">
                <Loader2 className="h-3 w-3 animate-spin" />
                Téléchargement de {vals.length} modèle(s)… {avg}%
              </span>
            )
          })()}
          {models.length > 0 && selectedModel && (() => {
            const m = models.find((x) => x.id === selectedModel)
            return m && m.tags && m.tags.length > 0 ? (
              <span className="self-start rounded-full bg-purple-500/20 border border-purple-500/40
                px-2 py-0.5 text-[10px] text-purple-300 font-medium">
                {m.tags[0]}
              </span>
            ) : null
          })()}
        </div>

        {/* Sampler */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-400">Sampler</label>
          <div className="relative">
            <select
              className="w-full appearance-none rounded-xl bg-gray-900 border border-gray-800 p-3 pr-8
                text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors cursor-pointer"
              value={sampler}
              onChange={(e) => setSampler(e.target.value)}
            >
              {SAMPLERS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-3.5 h-4 w-4 text-gray-500" />
          </div>
        </div>

        {/* Steps Slider */}
        <div className="flex flex-col gap-1">
          <div className="flex justify-between">
            <label className="text-xs font-medium text-gray-400">Steps</label>
            <span className="text-xs text-purple-400 font-mono">{steps}</span>
          </div>
          <input
            type="range" min={1} max={150} value={steps}
            onChange={(e) => setSteps(Number(e.target.value))}
            className="w-full accent-purple-500 cursor-pointer"
          />
        </div>

        {/* CFG Scale Slider */}
        <div className="flex flex-col gap-1">
          <div className="flex justify-between">
            <label className="text-xs font-medium text-gray-400">CFG Scale</label>
            <span className="text-xs text-purple-400 font-mono">{cfgScale.toFixed(1)}</span>
          </div>
          <input
            type="range" min={0} max={30} step={0.5} value={cfgScale}
            onChange={(e) => setCfgScale(Number(e.target.value))}
            className="w-full accent-purple-500 cursor-pointer"
          />
        </div>

        {/* Width / Height */}
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-400">Width</label>
            <div className="relative">
              <select
                className="w-full appearance-none rounded-xl bg-gray-900 border border-gray-800 p-2.5 pr-8
                  text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors cursor-pointer"
                value={width}
                onChange={(e) => setWidth(Number(e.target.value))}
              >
                {PIXEL_SIZES.map((s) => <option key={s} value={s}>{s}px</option>)}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2 top-3 h-3.5 w-3.5 text-gray-500" />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-400">Height</label>
            <div className="relative">
              <select
                className="w-full appearance-none rounded-xl bg-gray-900 border border-gray-800 p-2.5 pr-8
                  text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors cursor-pointer"
                value={height}
                onChange={(e) => setHeight(Number(e.target.value))}
              >
                {PIXEL_SIZES.map((s) => <option key={s} value={s}>{s}px</option>)}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2 top-3 h-3.5 w-3.5 text-gray-500" />
            </div>
          </div>
        </div>

        {/* Seed */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-400">Seed <span className="text-gray-600">(-1 = random)</span></label>
          <input
            type="number"
            className="rounded-xl bg-gray-900 border border-gray-800 p-2.5 text-sm text-gray-100
              focus:outline-none focus:border-purple-500 transition-colors"
            value={seed}
            onChange={(e) => setSeed(Number(e.target.value))}
          />
        </div>

        {/* Num Images */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-400">Number of Images</label>
          <div className="relative">
            <select
              className="w-full appearance-none rounded-xl bg-gray-900 border border-gray-800 p-2.5 pr-8
                text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors cursor-pointer"
              value={numImages}
              onChange={(e) => setNumImages(Number(e.target.value))}
            >
              {NUM_IMAGES_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-3 h-4 w-4 text-gray-500" />
          </div>
        </div>

        {/* LoRA */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-400">
            LoRA <span className="text-gray-600">(HF repo, optionnel)</span>
          </label>
          <input
            className="rounded-xl bg-gray-900 border border-gray-800 p-2.5 text-sm text-gray-100
              focus:outline-none focus:border-purple-500 transition-colors placeholder-gray-600"
            placeholder="ex. ostris/super-cereal-sdxl-lora"
            value={lora}
            onChange={(e) => setLora(e.target.value)}
          />
        </div>

        {/* Error */}
        {error && (
          <p className="rounded-lg bg-red-500/10 border border-red-500/30 px-3 py-2 text-xs text-red-400">
            {error}
          </p>
        )}

        {/* Queue Status */}
        {queuePosition !== null && (
          <p className="rounded-lg bg-yellow-500/10 border border-yellow-500/30 px-3 py-2 text-xs text-yellow-300">
            Queued — position {queuePosition}
          </p>
        )}

        {/* Generate Button */}
        <button
          className="mt-1 flex w-full items-center justify-center gap-2 rounded-xl bg-purple-600
            hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed
            px-4 py-3 text-sm font-semibold text-white transition-colors"
          onClick={handleGenerate}
          disabled={loading || !canGenerate}
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Generating...
            </>
          ) : (
            'Generate'
          )}
        </button>
      </aside>

      {/* ── Right Panel ── */}
      <main className="flex-1 overflow-y-auto">
        <h2 className="mb-3 text-sm font-semibold text-gray-400">Job History</h2>
        {jobs.length === 0 ? (
          <div className="flex h-48 flex-col items-center justify-center gap-3 rounded-xl
            border border-dashed border-gray-800 text-gray-600">
            <ImageIcon className="h-10 w-10" />
            <p className="text-sm">No jobs yet — generate an image to get started</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 xl:grid-cols-3 gap-3">
            {jobs.map((job) => (
              <JobCard
                key={job.job_id}
                job={job}
                onJobCompleted={handleJobCompleted}
                onJobFailed={handleJobFailed}
              />
            ))}
          </div>
        )}
      </main>

      <HFModelBrowser
        open={showBrowser}
        onClose={() => setShowBrowser(false)}
        onDownloadStarted={handleDownloadStarted}
      />
    </div>
  )
}
