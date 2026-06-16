import { useEffect, useRef, useState } from 'react'
import { Loader2, ImageIcon, ChevronDown } from 'lucide-react'
import { generateImage, getModels, getJobs } from '../api/image'
import { useWebSocket } from '../hooks/useWebSocket'
import { WS_BASE } from '../api/client'

// ─── Types ───────────────────────────────────────────────────────────────────

interface ImageModel {
  id: string
  name: string
  compatibility: string // e.g. "stable-diffusion", "sdxl", etc.
}

interface ImageJob {
  job_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  prompt: string
  created_at: string
  images?: string[] // base64 data URLs
  queue_position?: number
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

type WsEvent = WsStepEvent | WsCompletedEvent | WsQueueEvent

// ─── Constants ───────────────────────────────────────────────────────────────

const SAMPLERS = ['DPM++ 2M', 'Euler', 'Euler a', 'DDIM', 'LMS']
const PIXEL_SIZES = [512, 768, 1024]
const NUM_IMAGES_OPTIONS = [1, 2, 3, 4]

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
}

function ActiveJobProgress({ jobId, onCompleted }: ActiveJobProgressProps) {
  const [step, setStep] = useState(0)
  const [totalSteps, setTotalSteps] = useState(0)
  const [preview, setPreview] = useState<string | null>(null)
  const onCompletedRef = useRef(onCompleted)
  onCompletedRef.current = onCompleted

  useWebSocket(`${WS_BASE}/ws/image/${jobId}`, {
    onMessage: (raw) => {
      const evt = raw as WsEvent
      if (evt.type === 'step') {
        setStep(evt.step)
        setTotalSteps(evt.total_steps)
        if (evt.preview) setPreview(evt.preview)
      } else if (evt.type === 'completed') {
        onCompletedRef.current(evt.images)
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
          src={`data:image/png;base64,${preview}`}
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
}

function JobCard({ job, onJobCompleted }: JobCardProps) {
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
        />
      )}

      {job.status === 'completed' && job.images && job.images.length > 0 && (
        <div className={`grid gap-1 ${job.images.length === 1 ? 'grid-cols-1' : 'grid-cols-2'}`}>
          {job.images.map((img, i) => (
            <img
              key={i}
              src={`data:image/png;base64,${img}`}
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
        <p className="text-xs text-red-400">Generation failed</p>
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

  // UI state
  const [loading, setLoading] = useState(false)
  const [queuePosition, setQueuePosition] = useState<number | null>(null)
  const [jobs, setJobs] = useState<ImageJob[]>([])
  const [error, setError] = useState<string | null>(null)

  // Active job WS (for queue status on the newly submitted job)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)

  useWebSocket(activeJobId ? `${WS_BASE}/ws/image/${activeJobId}` : null, {
    onMessage: (raw) => {
      const evt = raw as WsEvent
      if (evt.type === 'queued') {
        setQueuePosition(evt.position)
      } else if (evt.type === 'completed') {
        setQueuePosition(null)
        setActiveJobId(null)
      }
    },
  })

  // Fetch models
  useEffect(() => {
    getModels()
      .then((data: ImageModel[]) => {
        setModels(data)
        if (data.length > 0) setSelectedModel(data[0].id)
      })
      .catch(() => setError('Failed to load models'))
  }, [])

  // Fetch job history
  useEffect(() => {
    getJobs()
      .then((data: ImageJob[]) => setJobs(data))
      .catch(() => {})
  }, [])

  const handleGenerate = async () => {
    if (!prompt.trim()) return
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
    }

    try {
      const result = await generateImage(params)
      const newJob: ImageJob = {
        job_id: result.job_id,
        status: result.status ?? 'queued',
        prompt,
        created_at: new Date().toISOString(),
        queue_position: result.queue_position,
      }
      setJobs((prev) => [newJob, ...prev])
      setActiveJobId(result.job_id)
    } catch (e) {
      setError('Generation failed. Please try again.')
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

  return (
    <div className="flex h-full gap-4 p-4 overflow-hidden">
      {/* ── Left Panel ── */}
      <aside className="w-[35%] shrink-0 flex flex-col gap-3 overflow-y-auto pr-1">
        {/* Positive Prompt */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-400">Prompt</label>
          <textarea
            className="rounded-xl bg-gray-900 border border-gray-800 p-3 text-sm text-gray-100
              resize-none h-28 focus:outline-none focus:border-blue-500 transition-colors placeholder-gray-600"
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
              resize-none h-16 focus:outline-none focus:border-blue-500 transition-colors placeholder-gray-600"
            placeholder="Things to avoid..."
            value={negativePrompt}
            onChange={(e) => setNegativePrompt(e.target.value)}
          />
        </div>

        {/* Model Selector */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-400">Model</label>
          <div className="relative">
            <select
              className="w-full appearance-none rounded-xl bg-gray-900 border border-gray-800 p-3 pr-8
                text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors cursor-pointer"
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
            >
              {models.length === 0 && <option value="">No models found</option>}
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-3.5 h-4 w-4 text-gray-500" />
          </div>
          {models.length > 0 && selectedModel && (() => {
            const m = models.find((x) => x.id === selectedModel)
            return m ? (
              <span className="self-start rounded-full bg-purple-500/20 border border-purple-500/40
                px-2 py-0.5 text-[10px] text-purple-300 font-medium">
                {m.compatibility}
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
          disabled={loading || !prompt.trim()}
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
              <JobCard key={job.job_id} job={job} onJobCompleted={handleJobCompleted} />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
