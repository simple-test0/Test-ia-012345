import { memo, useEffect, useRef, useState } from 'react'
import { Ban, Copy, ImageIcon, Loader2, RotateCcw, Trash2 } from 'lucide-react'
import { cancelJob, deleteJob, getJob, type ImageJob, type JobStatus } from '../../api/image'
import { errorMessage, withToken, wsUrl } from '../../api/client'
import { useWebSocket } from '../../hooks/useWebSocket'
import { toast } from '../ui/toast'

const STATUS_STYLES: Record<JobStatus, string> = {
  queued: 'bg-yellow-500/20 text-yellow-300 border border-yellow-500/40',
  running: 'bg-blue-500/20 text-blue-300 border border-blue-500/40',
  completed: 'bg-green-500/20 text-green-300 border border-green-500/40',
  failed: 'bg-red-500/20 text-red-300 border border-red-500/40',
  cancelled: 'bg-gray-500/20 text-gray-300 border border-gray-500/40',
}

const STATUS_LABELS: Record<JobStatus, string> = {
  queued: 'en file',
  running: 'en cours',
  completed: 'terminé',
  failed: 'échec',
  cancelled: 'annulé',
}

const isActive = (s: JobStatus) => s === 'queued' || s === 'running'

interface WsEvent {
  type: string
  step?: number
  total_steps?: number
  preview?: string | null
  position?: number
  images?: string[]
  full_images?: string[]
  message?: string
  seed?: number
  duration_ms?: number
}

/** Live progress for a queued/running job: WebSocket + polling safety net. */
function useJobTracker(job: ImageJob, onUpdate: (patch: Partial<ImageJob>) => void) {
  const [step, setStep] = useState(0)
  const [totalSteps, setTotalSteps] = useState(job.steps)
  const [preview, setPreview] = useState<string | null>(null)
  const active = isActive(job.status)
  const onUpdateRef = useRef(onUpdate)
  onUpdateRef.current = onUpdate

  const resync = () => {
    getJob(job.job_id)
      .then((fresh) => {
        if (fresh.status !== job.status || fresh.queue_position !== job.queue_position) {
          onUpdateRef.current(fresh)
        }
      })
      .catch(() => {})
  }

  const { connected } = useWebSocket(active ? wsUrl(`/ws/image/${job.job_id}`) : null, {
    onOpen: resync, // catch up on anything missed while disconnected
    onMessage: (raw) => {
      const evt = raw as WsEvent
      switch (evt.type) {
        case 'queued':
          onUpdateRef.current({ status: 'queued', queue_position: evt.position })
          break
        case 'started':
          onUpdateRef.current({ status: 'running', queue_position: null })
          break
        case 'step':
          if (job.status !== 'running') onUpdateRef.current({ status: 'running', queue_position: null })
          setStep(evt.step ?? 0)
          if (evt.total_steps) setTotalSteps(evt.total_steps)
          if (evt.preview) setPreview(evt.preview)
          break
        case 'completed':
          onUpdateRef.current({
            status: 'completed',
            images: evt.images ?? [],
            full_images: evt.full_images ?? [],
            seed: evt.seed ?? job.seed,
            duration_ms: evt.duration_ms,
          })
          break
        case 'error':
          onUpdateRef.current({ status: 'failed', error_message: evt.message })
          toast.error(`Génération échouée : ${evt.message ?? 'erreur inconnue'}`)
          break
        case 'cancelled':
          onUpdateRef.current({ status: 'cancelled' })
          break
        case 'warning':
          if (evt.message) toast.info(evt.message)
          break
      }
    },
  })

  // Safety net: if the socket is down, poll (cheap: no image data in the payload).
  useEffect(() => {
    if (!active || connected) return
    const t = setInterval(resync, 4000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, connected, job.status])

  return { step, totalSteps, preview }
}

interface JobCardProps {
  job: ImageJob
  modelName?: string
  onUpdate: (jobId: string, patch: Partial<ImageJob>) => void
  onRemove: (jobId: string) => void
  onReuse: (job: ImageJob) => void
  onOpenImage: (job: ImageJob, index: number) => void
}

function JobCard({ job, modelName, onUpdate, onRemove, onReuse, onOpenImage }: JobCardProps) {
  const { step, totalSteps, preview } = useJobTracker(job, (patch) => onUpdate(job.job_id, patch))
  const [busy, setBusy] = useState(false)
  const pct = totalSteps > 0 ? Math.round((step / totalSteps) * 100) : 0

  const handleCancel = async () => {
    setBusy(true)
    try {
      await cancelJob(job.job_id)
      if (job.status === 'queued') onUpdate(job.job_id, { status: 'cancelled' })
      else toast.info('Annulation demandée — arrêt à la prochaine étape.')
    } catch (e) {
      toast.error(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async () => {
    if (!window.confirm('Supprimer cette génération et ses images ?')) return
    setBusy(true)
    try {
      await deleteJob(job.job_id)
      onRemove(job.job_id)
    } catch (e) {
      toast.error(errorMessage(e))
      setBusy(false)
    }
  }

  const copyPrompt = () => {
    navigator.clipboard?.writeText(job.prompt).then(
      () => toast.success('Prompt copié'),
      () => toast.error('Copie impossible'),
    )
  }

  return (
    <div className="group rounded-xl bg-gray-900 border border-gray-800 p-3 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs text-gray-300 line-clamp-2 flex-1" title={job.prompt}>{job.prompt}</p>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${STATUS_STYLES[job.status]}`}>
          {STATUS_LABELS[job.status]}
        </span>
      </div>

      {job.status === 'queued' && (
        <p className="flex items-center gap-1.5 text-xs text-yellow-400">
          <Loader2 className="h-3 w-3 animate-spin" />
          {job.queue_position ? `En file — position ${job.queue_position}` : 'En file…'}
        </p>
      )}

      {job.status === 'running' && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-gray-400">
            <span>{step > 0 ? `Étape ${step} / ${totalSteps}` : 'Chargement du modèle…'}</span>
            <span>{pct}%</span>
          </div>
          <div className="h-2 w-full rounded-full bg-gray-700 overflow-hidden">
            <div
              className={`h-2 rounded-full bg-purple-500 transition-all duration-300 ${step === 0 ? 'animate-pulse w-full opacity-30' : ''}`}
              style={step > 0 ? { width: `${pct}%` } : undefined}
            />
          </div>
          {preview && (
            <img src={preview} alt="Aperçu" className="w-full rounded-lg object-contain opacity-80" />
          )}
        </div>
      )}

      {job.status === 'completed' && job.images.length > 0 && (
        <div className={`grid gap-1 ${job.images.length === 1 ? 'grid-cols-1' : 'grid-cols-2'}`}>
          {job.images.map((img, i) => (
            <button
              key={img}
              onClick={() => onOpenImage(job, i)}
              className="overflow-hidden rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500"
              title="Agrandir"
            >
              <img
                src={withToken(img)}
                alt={`Image ${i + 1}`}
                loading="lazy"
                decoding="async"
                className="w-full object-cover aspect-square bg-gray-800 transition-transform hover:scale-105"
              />
            </button>
          ))}
        </div>
      )}

      {job.status === 'completed' && job.images.length === 0 && (
        <div className="flex h-24 items-center justify-center rounded-lg bg-gray-800">
          <ImageIcon className="h-8 w-8 text-gray-600" />
        </div>
      )}

      {job.status === 'failed' && (
        <p className="rounded-lg bg-red-500/10 px-2 py-1.5 text-[11px] text-red-300 break-words">
          {job.error_message || 'La génération a échoué.'}
        </p>
      )}

      <div className="flex items-center justify-between gap-2 text-[10px] text-gray-600">
        <span className="truncate" title={`seed ${job.seed}`}>
          {modelName ?? job.model_id} · {job.width}×{job.height}
          {job.duration_ms ? ` · ${(job.duration_ms / 1000).toFixed(1)}s` : ''}
        </span>
        <div className="flex shrink-0 items-center gap-1 opacity-70 group-hover:opacity-100 transition-opacity">
          {isActive(job.status) ? (
            <button
              onClick={handleCancel}
              disabled={busy}
              className="rounded p-1 text-gray-400 hover:bg-gray-800 hover:text-red-300 disabled:opacity-40"
              title="Annuler"
            >
              <Ban className="h-3.5 w-3.5" />
            </button>
          ) : (
            <>
              <button onClick={() => onReuse(job)} className="rounded p-1 text-gray-400 hover:bg-gray-800 hover:text-purple-300"
                title="Réutiliser ces réglages (même seed)">
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
              <button onClick={copyPrompt} className="rounded p-1 text-gray-400 hover:bg-gray-800 hover:text-purple-300"
                title="Copier le prompt">
                <Copy className="h-3.5 w-3.5" />
              </button>
              <button onClick={handleDelete} disabled={busy}
                className="rounded p-1 text-gray-400 hover:bg-gray-800 hover:text-red-300 disabled:opacity-40"
                title="Supprimer">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export default memo(JobCard)
