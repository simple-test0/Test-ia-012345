import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, Dices, ImageIcon, Loader2, Lock, Plus, Sparkles, Trash2 } from 'lucide-react'
import {
  deleteHFModel,
  generateImage,
  getHFModelStatus,
  getJobs,
  getModels,
  getSamplers,
  type GenerateParams,
  type ImageJob,
  type ImageModel,
} from '../api/image'
import { errorMessage } from '../api/client'
import HFModelBrowser from '../components/image/HFModelBrowser'
import JobCard from '../components/image/JobCard'
import Lightbox from '../components/image/Lightbox'
import { toast } from '../components/ui/toast'
import { usePersistentState } from '../hooks/usePersistentState'

// ─── Constants ───────────────────────────────────────────────────────────────

const DEFAULT_SAMPLERS = ['DPM++ 2M', 'DPM++ 2M Karras', 'Euler', 'Euler a', 'DDIM', 'LMS']
const PIXEL_SIZES = [512, 576, 640, 704, 768, 832, 896, 960, 1024, 1152, 1280, 1536]
const NUM_IMAGES_OPTIONS = [1, 2, 3, 4]
const PAGE_SIZE = 24
const MAX_SEED = 2 ** 32 - 1

const ASPECTS: { label: string; w: number; h: number }[] = [
  { label: '1:1', w: 1, h: 1 },
  { label: '3:2', w: 3, h: 2 },
  { label: '2:3', w: 2, h: 3 },
  { label: '16:9', w: 16, h: 9 },
  { label: '9:16', w: 9, h: 16 },
]

interface FormState {
  prompt: string
  negativePrompt: string
  modelId: string
  sampler: string
  steps: number
  cfgScale: number
  width: number
  height: number
  seed: number
  numImages: number
  lora: string
}

const DEFAULT_FORM: FormState = {
  prompt: '',
  negativePrompt: '',
  modelId: '',
  sampler: 'DPM++ 2M',
  steps: 20,
  cfgScale: 7.5,
  width: 512,
  height: 512,
  seed: -1,
  numImages: 1,
  lora: '',
}

const selectCls = `w-full appearance-none rounded-xl bg-gray-900 border border-gray-800 p-2.5 pr-8
  text-sm text-gray-100 focus:outline-none focus:border-purple-500 transition-colors cursor-pointer`
const inputCls = `rounded-xl bg-gray-900 border border-gray-800 p-2.5 text-sm text-gray-100
  focus:outline-none focus:border-purple-500 transition-colors placeholder-gray-600`

const roundTo8 = (n: number) => Math.max(64, Math.round(n / 8) * 8)

// Hugging Face tags include lots of metadata ("license:mit", "diffusers"…).
const NOISY_TAGS = new Set(['diffusers', 'safetensors', 'endpoints_compatible', 'text-to-image', 'en', 'arxiv'])
const isUsefulTag = (t: string) => !t.includes(':') && !NOISY_TAGS.has(t)

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ImageGenerationPage() {
  const [form, setForm] = usePersistentState<FormState>('aistudio.image.form', DEFAULT_FORM)
  const set = useCallback(
    <K extends keyof FormState>(key: K, value: FormState[K]) =>
      setForm((f) => ({ ...f, [key]: value })),
    [setForm],
  )

  const [models, setModels] = useState<ImageModel[]>([])
  const [samplers, setSamplers] = useState<string[]>(DEFAULT_SAMPLERS)
  const [submitting, setSubmitting] = useState(false)
  const [jobs, setJobs] = useState<ImageJob[]>([])
  const [jobsLoading, setJobsLoading] = useState(true)
  const [hasMore, setHasMore] = useState(false)
  const [lightbox, setLightbox] = useState<{ job: ImageJob; index: number } | null>(null)

  // Hugging Face model browser + download tracking
  const [showBrowser, setShowBrowser] = useState(false)
  const [downloadingModels, setDownloadingModels] = useState<Record<string, number>>({})

  const promptRef = useRef<HTMLTextAreaElement>(null)

  // ── Models ──────────────────────────────────────────────────────────────────

  const refreshModels = useCallback(
    () =>
      getModels()
        .then((data) => {
          setModels(data)
          // Resume tracking of downloads started before a reload.
          const inFlight = data.filter((m) => m.status === 'downloading')
          if (inFlight.length) {
            setDownloadingModels((prev) => {
              const next = { ...prev }
              inFlight.forEach((m) => { next[m.id] = m.progress ?? next[m.id] ?? 0 })
              return next
            })
          }
          setForm((f) => {
            const current = data.find((m) => m.id === f.modelId && m.status === 'ready')
            if (current) return f
            const first =
              data.find((m) => m.status === 'ready' && m.compatible) ??
              data.find((m) => m.status === 'ready')
            return first ? { ...f, modelId: first.id } : f
          })
        })
        .catch((e) => toast.error(`Modèles indisponibles : ${errorMessage(e)}`)),
    [setForm],
  )

  useEffect(() => {
    refreshModels()
    getSamplers().then((s) => s.length && setSamplers(s)).catch(() => {})
  }, [refreshModels])

  const selectedModel = models.find((m) => m.id === form.modelId)

  // Picking a model applies its recommended settings (steps, CFG, size).
  const handleModelChange = (id: string) => {
    const m = models.find((x) => x.id === id)
    setForm((f) => ({
      ...f,
      modelId: id,
      ...(m
        ? {
            steps: m.recommended_steps ?? f.steps,
            cfgScale: m.default_cfg ?? f.cfgScale,
            width: m.default_width ?? f.width,
            height: m.default_height ?? f.height,
          }
        : {}),
    }))
    if (m && !m.compatible) {
      toast.info(`${m.name} demande ~${Math.round((m.min_vram_mb ?? 0) / 1024)} GB de VRAM : la génération risque d'être lente ou d'échouer.`)
    }
  }

  // Poll status of in-progress HF model downloads.
  useEffect(() => {
    const ids = Object.keys(downloadingModels)
    if (ids.length === 0) return
    const interval = setInterval(() => {
      ids.forEach((id) => {
        getHFModelStatus(id)
          .then((m) => {
            if (m.status === 'downloading') {
              setDownloadingModels((prev) => ({ ...prev, [id]: m.progress ?? 0 }))
              return
            }
            setDownloadingModels((prev) => {
              const next = { ...prev }
              delete next[id]
              return next
            })
            refreshModels()
            if (m.status === 'ready') toast.success(`${m.name} est téléchargé et prêt.`)
            else toast.error(m.error_message || 'Le téléchargement du modèle a échoué.')
          })
          .catch(() => {
            setDownloadingModels((prev) => {
              const next = { ...prev }
              delete next[id]
              return next
            })
          })
      })
    }, 3000)
    return () => clearInterval(interval)
  }, [downloadingModels, refreshModels])

  const handleDownloadStarted = (modelId: string) => {
    setDownloadingModels((prev) => ({ ...prev, [modelId]: 0 }))
    refreshModels()
  }

  const handleDeleteModel = async () => {
    if (!selectedModel || selectedModel.source !== 'downloaded') return
    if (!window.confirm(`Supprimer ${selectedModel.name} du disque ?`)) return
    try {
      await deleteHFModel(selectedModel.id)
      toast.success(`${selectedModel.name} supprimé.`)
      setForm((f) => ({ ...f, modelId: '' }))
      refreshModels()
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  // ── Jobs ────────────────────────────────────────────────────────────────────

  const loadJobs = useCallback((offset: number) => {
    setJobsLoading(true)
    getJobs(PAGE_SIZE, offset)
      .then((data) => {
        setJobs((prev) => {
          if (offset === 0) return data
          const seen = new Set(prev.map((j) => j.job_id))
          return [...prev, ...data.filter((j) => !seen.has(j.job_id))]
        })
        setHasMore(data.length === PAGE_SIZE)
      })
      .catch((e) => toast.error(`Historique indisponible : ${errorMessage(e)}`))
      .finally(() => setJobsLoading(false))
  }, [])

  useEffect(() => loadJobs(0), [loadJobs])

  const updateJob = useCallback((jobId: string, patch: Partial<ImageJob>) => {
    setJobs((prev) => prev.map((j) => (j.job_id === jobId ? { ...j, ...patch } : j)))
  }, [])

  const removeJob = useCallback((jobId: string) => {
    setJobs((prev) => prev.filter((j) => j.job_id !== jobId))
  }, [])

  const reuseJob = useCallback(
    (job: ImageJob) => {
      setForm((f) => ({
        ...f,
        prompt: job.prompt,
        negativePrompt: job.negative_prompt ?? '',
        modelId: models.some((m) => m.id === job.model_id) ? job.model_id : f.modelId,
        sampler: job.sampler ?? f.sampler,
        steps: job.steps,
        cfgScale: job.cfg_scale ?? f.cfgScale,
        width: job.width,
        height: job.height,
        seed: job.seed,
        numImages: job.num_images ?? f.numImages,
      }))
      promptRef.current?.focus()
      toast.info('Réglages chargés (seed incluse) — modifiez puis générez.')
    },
    [models, setForm],
  )

  const openImage = useCallback((job: ImageJob, index: number) => setLightbox({ job, index }), [])

  const modelNames = useMemo(() => Object.fromEntries(models.map((m) => [m.id, m.name])), [models])

  // ── Generate ────────────────────────────────────────────────────────────────

  const canGenerate = !submitting && !!form.prompt.trim() && selectedModel?.status === 'ready'

  const handleGenerate = async () => {
    if (!canGenerate) return
    setSubmitting(true)
    const params: GenerateParams = {
      prompt: form.prompt.trim(),
      negative_prompt: form.negativePrompt,
      model_id: form.modelId,
      sampler: form.sampler,
      steps: form.steps,
      cfg_scale: form.cfgScale,
      width: form.width,
      height: form.height,
      seed: form.seed,
      num_images: form.numImages,
      lora: form.lora.trim() || undefined,
    }

    try {
      const result = await generateImage(params)
      const newJob: ImageJob = {
        job_id: result.job_id,
        status: result.status ?? 'queued',
        model_id: params.model_id,
        prompt: params.prompt,
        negative_prompt: params.negative_prompt,
        width: params.width,
        height: params.height,
        steps: params.steps,
        cfg_scale: params.cfg_scale,
        seed: result.seed ?? params.seed,
        sampler: params.sampler,
        num_images: params.num_images,
        images: [],
        full_images: [],
        created_at: new Date().toISOString(),
        queue_position: result.queue_position,
      }
      setJobs((prev) => [newJob, ...prev])
    } catch (e) {
      toast.error(errorMessage(e, 'La génération a échoué'))
    } finally {
      setSubmitting(false)
    }
  }

  // Ctrl/Cmd + Enter generates from anywhere on the page.
  const generateRef = useRef(handleGenerate)
  generateRef.current = handleGenerate
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        generateRef.current()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const applyAspect = (w: number, h: number) => {
    // Keep roughly the same pixel count as the model's native size.
    const base = (selectedModel?.default_width ?? 512) * (selectedModel?.default_height ?? 512)
    const k = Math.sqrt(base / (w * h))
    setForm((f) => ({ ...f, width: roundTo8(w * k), height: roundTo8(h * k) }))
  }

  const sizeOptions = (current: number) =>
    PIXEL_SIZES.includes(current) ? PIXEL_SIZES : [...PIXEL_SIZES, current].sort((a, b) => a - b)

  const activeCount = jobs.filter((j) => j.status === 'queued' || j.status === 'running').length
  const downloadingVals = Object.values(downloadingModels)

  return (
    <div className="flex h-full flex-col md:flex-row gap-4 p-4 overflow-y-auto md:overflow-hidden">
      {/* ── Left Panel ── */}
      <aside className="w-full md:w-[360px] lg:w-[400px] md:shrink-0 flex flex-col gap-3 md:overflow-y-auto pr-1">
        {/* Positive Prompt */}
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <label htmlFor="prompt" className="text-xs font-medium text-gray-400">Prompt</label>
            <span className="text-[10px] text-gray-600">Ctrl+Entrée pour générer</span>
          </div>
          <textarea
            id="prompt"
            ref={promptRef}
            className={`${inputCls} p-3 resize-y min-h-[7rem]`}
            placeholder="Décrivez l'image à générer…"
            value={form.prompt}
            onChange={(e) => set('prompt', e.target.value)}
          />
        </div>

        {/* Negative Prompt */}
        <div className="flex flex-col gap-1">
          <label htmlFor="neg" className="text-xs font-medium text-gray-400">
            Prompt négatif
            {selectedModel && selectedModel.source === 'curated' && selectedModel.tags?.includes('flux') && (
              <span className="ml-1 text-gray-600">(ignoré par FLUX)</span>
            )}
          </label>
          <textarea
            id="neg"
            className={`${inputCls} p-3 resize-y min-h-[4rem]`}
            placeholder="Ce qu'il faut éviter…"
            value={form.negativePrompt}
            onChange={(e) => set('negativePrompt', e.target.value)}
          />
        </div>

        {/* Model Selector */}
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <label htmlFor="model" className="text-xs font-medium text-gray-400">Modèle</label>
            <button
              type="button"
              onClick={() => setShowBrowser(true)}
              className="flex items-center gap-1 text-[11px] font-medium text-purple-400 hover:text-purple-300"
            >
              <Plus className="h-3 w-3" /> Ajouter un modèle
            </button>
          </div>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <select
                id="model"
                className={selectCls}
                value={form.modelId}
                onChange={(e) => handleModelChange(e.target.value)}
              >
                {models.length === 0 && <option value="">Chargement…</option>}
                {(() => {
                  const curated = models.filter((m) => m.source === 'curated')
                  const downloaded = models.filter((m) => m.source === 'downloaded')
                  const optionLabel = (m: ImageModel) => {
                    let label = m.name
                    if (m.status === 'downloading') label += ` (téléchargement ${m.progress ?? 0}%)`
                    else if (m.status === 'error') label += ' (erreur)'
                    else if (!m.compatible) label += ' — VRAM insuffisante'
                    return label
                  }
                  return (
                    <>
                      {curated.length > 0 && (
                        <optgroup label="Recommandés">
                          {curated.map((m) => (
                            <option key={m.id} value={m.id}>{optionLabel(m)}</option>
                          ))}
                        </optgroup>
                      )}
                      {downloaded.length > 0 && (
                        <optgroup label="Téléchargés">
                          {downloaded.map((m) => (
                            <option key={m.id} value={m.id} disabled={m.status === 'downloading'}>
                              {optionLabel(m)}
                            </option>
                          ))}
                        </optgroup>
                      )}
                    </>
                  )
                })()}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-3 h-4 w-4 text-gray-500" />
            </div>
            {selectedModel?.source === 'downloaded' && (
              <button
                onClick={handleDeleteModel}
                className="shrink-0 rounded-xl border border-gray-800 bg-gray-900 px-2.5 text-gray-500 hover:text-red-300"
                title="Supprimer ce modèle du disque"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
          {downloadingVals.length > 0 && (
            <span className="flex items-center gap-1.5 self-start rounded-full bg-purple-500/15
              border border-purple-500/30 px-2 py-0.5 text-[10px] text-purple-300">
              <Loader2 className="h-3 w-3 animate-spin" />
              Téléchargement de {downloadingVals.length} modèle(s)…{' '}
              {Math.round(downloadingVals.reduce((a, b) => a + b, 0) / downloadingVals.length)}%
            </span>
          )}
          {selectedModel && (
            <div className="flex flex-wrap items-center gap-1">
              {selectedModel.gated && (
                <span className="flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10
                  px-2 py-0.5 text-[10px] text-amber-300" title="Nécessite HUGGINGFACE_TOKEN + licence acceptée">
                  <Lock className="h-2.5 w-2.5" /> accès restreint
                </span>
              )}
              {(selectedModel.tags ?? []).filter(isUsefulTag).slice(0, 3).map((t) => (
                <span key={t} className="rounded-full bg-purple-500/20 border border-purple-500/40
                  px-2 py-0.5 text-[10px] text-purple-300 font-medium">{t}</span>
              ))}
              {selectedModel.status === 'error' && (
                <span className="text-[10px] text-red-400">{selectedModel.error_message}</span>
              )}
            </div>
          )}
          {selectedModel?.description && (
            <p className="text-[11px] leading-snug text-gray-500">{selectedModel.description}</p>
          )}
        </div>

        {/* Sampler */}
        <div className="flex flex-col gap-1">
          <label htmlFor="sampler" className="text-xs font-medium text-gray-400">Sampler</label>
          <div className="relative">
            <select id="sampler" className={selectCls} value={form.sampler}
              onChange={(e) => set('sampler', e.target.value)}>
              {samplers.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-3 h-4 w-4 text-gray-500" />
          </div>
        </div>

        {/* Steps Slider */}
        <div className="flex flex-col gap-1">
          <div className="flex justify-between">
            <label htmlFor="steps" className="text-xs font-medium text-gray-400">Étapes</label>
            <span className="text-xs text-purple-400 font-mono">{form.steps}</span>
          </div>
          <input id="steps" type="range" min={1} max={150} value={form.steps}
            onChange={(e) => set('steps', Number(e.target.value))}
            className="w-full accent-purple-500 cursor-pointer" />
        </div>

        {/* CFG Scale Slider */}
        <div className="flex flex-col gap-1">
          <div className="flex justify-between">
            <label htmlFor="cfg" className="text-xs font-medium text-gray-400">CFG (fidélité au prompt)</label>
            <span className="text-xs text-purple-400 font-mono">{form.cfgScale.toFixed(1)}</span>
          </div>
          <input id="cfg" type="range" min={0} max={30} step={0.5} value={form.cfgScale}
            onChange={(e) => set('cfgScale', Number(e.target.value))}
            className="w-full accent-purple-500 cursor-pointer" />
        </div>

        {/* Size */}
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-gray-400">Taille</span>
            <div className="flex gap-1">
              {ASPECTS.map((a) => (
                <button key={a.label} type="button" onClick={() => applyAspect(a.w, a.h)}
                  className="rounded-md border border-gray-800 px-1.5 py-0.5 text-[10px] text-gray-400 hover:border-purple-500 hover:text-purple-300">
                  {a.label}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {(['width', 'height'] as const).map((key) => (
              <div key={key} className="relative">
                <select aria-label={key === 'width' ? 'Largeur' : 'Hauteur'} className={selectCls}
                  value={form[key]} onChange={(e) => set(key, Number(e.target.value))}>
                  {sizeOptions(form[key]).map((s) => (
                    <option key={s} value={s}>{key === 'width' ? 'L' : 'H'} {s}px</option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2 top-3 h-3.5 w-3.5 text-gray-500" />
              </div>
            ))}
          </div>
        </div>

        {/* Seed + count */}
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="seed" className="text-xs font-medium text-gray-400">
              Seed <span className="text-gray-600">(-1 = aléatoire)</span>
            </label>
            <div className="flex gap-1">
              <input id="seed" type="number" min={-1} max={MAX_SEED} className={`${inputCls} min-w-0 flex-1`}
                value={form.seed}
                onChange={(e) => {
                  const v = Math.trunc(Number(e.target.value))
                  set('seed', Number.isFinite(v) ? Math.min(MAX_SEED, Math.max(-1, v)) : -1)
                }} />
              <button type="button" onClick={() => set('seed', -1)} title="Seed aléatoire"
                className="shrink-0 rounded-xl border border-gray-800 bg-gray-900 px-2 text-gray-400 hover:text-purple-300">
                <Dices className="h-4 w-4" />
              </button>
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="num" className="text-xs font-medium text-gray-400">Nombre d'images</label>
            <div className="relative">
              <select id="num" className={selectCls} value={form.numImages}
                onChange={(e) => set('numImages', Number(e.target.value))}>
                {NUM_IMAGES_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-3 h-4 w-4 text-gray-500" />
            </div>
          </div>
        </div>

        {/* LoRA */}
        <div className="flex flex-col gap-1">
          <label htmlFor="lora" className="text-xs font-medium text-gray-400">
            LoRA <span className="text-gray-600">(dépôt HF, optionnel)</span>
          </label>
          <input id="lora" className={inputCls} placeholder="ex. ostris/super-cereal-sdxl-lora"
            value={form.lora} onChange={(e) => set('lora', e.target.value)} />
        </div>

        {/* Generate Button */}
        <button
          className="sticky bottom-0 mt-1 flex w-full items-center justify-center gap-2 rounded-xl bg-purple-600
            hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed
            px-4 py-3 text-sm font-semibold text-white transition-colors shadow-lg shadow-black/40"
          onClick={handleGenerate}
          disabled={!canGenerate}
          title={selectedModel && selectedModel.status !== 'ready' ? "Ce modèle n'est pas prêt" : undefined}
        >
          {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
          {submitting ? 'Envoi…' : activeCount > 0 ? `Générer (${activeCount} en cours)` : 'Générer'}
        </button>
      </aside>

      {/* ── Right Panel ── */}
      <main className="flex-1 md:overflow-y-auto">
        <h2 className="mb-3 text-sm font-semibold text-gray-400">Historique</h2>
        {jobs.length === 0 ? (
          <div className="flex h-48 flex-col items-center justify-center gap-3 rounded-xl
            border border-dashed border-gray-800 text-gray-600">
            {jobsLoading ? <Loader2 className="h-8 w-8 animate-spin" /> : <ImageIcon className="h-10 w-10" />}
            {!jobsLoading && <p className="text-sm">Aucune génération — lancez votre première image</p>}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3">
              {jobs.map((job) => (
                <JobCard
                  key={job.job_id}
                  job={job}
                  modelName={modelNames[job.model_id]}
                  onUpdate={updateJob}
                  onRemove={removeJob}
                  onReuse={reuseJob}
                  onOpenImage={openImage}
                />
              ))}
            </div>
            {hasMore && (
              <div className="mt-4 flex justify-center">
                <button
                  onClick={() => loadJobs(jobs.length)}
                  disabled={jobsLoading}
                  className="flex items-center gap-2 rounded-lg border border-gray-800 px-4 py-2 text-xs text-gray-300 hover:bg-gray-900 disabled:opacity-50"
                >
                  {jobsLoading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  Charger plus
                </button>
              </div>
            )}
          </>
        )}
      </main>

      <HFModelBrowser
        open={showBrowser}
        onClose={() => setShowBrowser(false)}
        onDownloadStarted={handleDownloadStarted}
      />

      {lightbox && (
        <Lightbox
          images={lightbox.job.full_images}
          index={lightbox.index}
          onIndexChange={(index) => setLightbox((lb) => (lb ? { ...lb, index } : lb))}
          onClose={() => setLightbox(null)}
          caption={`${lightbox.job.prompt} — seed ${lightbox.job.seed}`}
        />
      )}
    </div>
  )
}
