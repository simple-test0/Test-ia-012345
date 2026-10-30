import { useEffect, useRef, useState } from 'react'
import { ImagePlus, X } from 'lucide-react'
import { toast } from '../ui/toast'

const MAX_SIDE = 2048

/** Read an image file/blob, downscale it to ≤ 2048 px and return a data URL. */
export async function imageToDataUrl(blob: Blob): Promise<string> {
  const bitmap = await createImageBitmap(blob)
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(bitmap.width * scale)
  canvas.height = Math.round(bitmap.height * scale)
  canvas.getContext('2d')!.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  bitmap.close()
  // JPEG keeps the upload small; quality 0.92 is visually lossless here.
  return canvas.toDataURL('image/jpeg', 0.92)
}

interface InitImagePickerProps {
  value: string | null
  onChange: (dataUrl: string | null) => void
  strength: number
  onStrengthChange: (v: number) => void
}

/** img2img source: click, drag & drop or paste (Ctrl+V) an image. */
export default function InitImagePicker({ value, onChange, strength, onStrengthChange }: InitImagePickerProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const load = async (blob: Blob | null | undefined) => {
    if (!blob) return
    if (!blob.type.startsWith('image/')) {
      toast.error("Ce fichier n'est pas une image.")
      return
    }
    try {
      onChange(await imageToDataUrl(blob))
    } catch {
      toast.error("Impossible de lire cette image.")
    }
  }

  // Paste an image from the clipboard anywhere on the page.
  const loadRef = useRef(load)
  loadRef.current = load
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const item = Array.from(e.clipboardData?.items ?? []).find((i) => i.type.startsWith('image/'))
      if (item) {
        e.preventDefault()
        loadRef.current(item.getAsFile())
        toast.info('Image collée comme source (img2img)')
      }
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [])

  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-gray-400">
        Image source <span className="text-gray-600">(img2img, optionnel)</span>
      </span>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          load(e.target.files?.[0])
          e.target.value = ''
        }}
      />
      {value ? (
        <div className="flex gap-3 rounded-xl border border-gray-800 bg-gray-900 p-2">
          <div className="relative shrink-0">
            <img src={value} alt="Image source" className="h-20 w-20 rounded-lg object-cover" />
            <button
              onClick={() => onChange(null)}
              className="absolute -right-1.5 -top-1.5 rounded-full bg-gray-800 p-0.5 text-gray-300 hover:bg-red-600 hover:text-white"
              title="Retirer l'image source"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="flex flex-1 flex-col justify-center gap-1">
            <div className="flex justify-between">
              <label htmlFor="strength" className="text-[11px] text-gray-400">Force de transformation</label>
              <span className="text-xs font-mono text-purple-400">{strength.toFixed(2)}</span>
            </div>
            <input
              id="strength"
              type="range" min={0.05} max={1} step={0.05} value={strength}
              onChange={(e) => onStrengthChange(Number(e.target.value))}
              className="w-full accent-purple-500 cursor-pointer"
            />
            <span className="text-[10px] text-gray-600">
              Bas = proche de l'original · Haut = très différent
            </span>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            load(e.dataTransfer.files?.[0])
          }}
          className={`flex items-center justify-center gap-2 rounded-xl border border-dashed px-3 py-3 text-xs transition-colors
            ${dragging ? 'border-purple-500 bg-purple-500/10 text-purple-300' : 'border-gray-700 text-gray-500 hover:border-purple-500 hover:text-purple-300'}`}
        >
          <ImagePlus className="h-4 w-4" />
          Glisser, coller (Ctrl+V) ou choisir une image
        </button>
      )}
    </div>
  )
}
