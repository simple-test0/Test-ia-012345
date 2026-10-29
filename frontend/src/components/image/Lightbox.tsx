import { useEffect } from 'react'
import { ChevronLeft, ChevronRight, Download, X } from 'lucide-react'
import { withToken } from '../../api/client'

interface LightboxProps {
  images: string[] // full-resolution URLs
  index: number
  onIndexChange: (i: number) => void
  onClose: () => void
  caption?: string
}

export default function Lightbox({ images, index, onIndexChange, onClose, caption }: LightboxProps) {
  const count = images.length
  const prev = () => onIndexChange((index - 1 + count) % count)
  const next = () => onIndexChange((index + 1) % count)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowLeft' && count > 1) prev()
      else if (e.key === 'ArrowRight' && count > 1) next()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, count])

  if (count === 0) return null
  const src = withToken(images[index])
  const fileName = images[index].split('/').pop()?.split('?')[0] ?? 'image.png'

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black/90 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div className="absolute right-4 top-4 flex gap-2" onClick={(e) => e.stopPropagation()}>
        <a
          href={src}
          download={fileName}
          className="flex items-center gap-1.5 rounded-lg bg-gray-800/80 px-3 py-2 text-xs text-gray-100 hover:bg-gray-700"
          title="Télécharger (PNG pleine résolution)"
        >
          <Download className="h-4 w-4" /> Télécharger
        </a>
        <button
          onClick={onClose}
          className="rounded-lg bg-gray-800/80 p-2 text-gray-100 hover:bg-gray-700"
          title="Fermer (Échap)"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {count > 1 && (
        <>
          <button
            onClick={(e) => { e.stopPropagation(); prev() }}
            className="absolute left-3 top-1/2 -translate-y-1/2 rounded-full bg-gray-800/70 p-2 text-white hover:bg-gray-700"
            title="Précédente (←)"
          >
            <ChevronLeft className="h-6 w-6" />
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); next() }}
            className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full bg-gray-800/70 p-2 text-white hover:bg-gray-700"
            title="Suivante (→)"
          >
            <ChevronRight className="h-6 w-6" />
          </button>
        </>
      )}

      <img
        src={src}
        alt={caption ?? 'Image générée'}
        className="max-h-[85vh] max-w-full rounded-lg object-contain shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      />
      {(caption || count > 1) && (
        <p className="mt-3 max-w-3xl text-center text-xs text-gray-400" onClick={(e) => e.stopPropagation()}>
          {count > 1 && <span className="mr-2 text-gray-500">{index + 1}/{count}</span>}
          {caption}
        </p>
      )}
    </div>
  )
}
