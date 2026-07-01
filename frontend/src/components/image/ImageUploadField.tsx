import { useRef } from 'react'
import { ImagePlus, X } from 'lucide-react'

interface ImageUploadFieldProps {
  label: string
  hint?: string
  value: string | null // base64 data URL
  onChange: (dataUrl: string | null) => void
}

const MAX_FILE_BYTES = 20 * 1024 * 1024 // keep in sync with backend limit

export default function ImageUploadField({ label, hint, value, onChange }: ImageUploadFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = (file: File | undefined) => {
    if (!file) return
    if (file.size > MAX_FILE_BYTES) {
      alert('Image trop volumineuse (max 20 Mo)')
      return
    }
    const reader = new FileReader()
    reader.onload = () => onChange(reader.result as string)
    reader.readAsDataURL(file)
  }

  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-gray-400">{label}</label>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(e) => {
          handleFile(e.target.files?.[0])
          e.target.value = ''
        }}
      />
      {value ? (
        <div className="relative">
          <img
            src={value}
            alt={label}
            className="w-full max-h-48 rounded-xl border border-gray-800 object-contain bg-gray-900"
          />
          <button
            type="button"
            onClick={() => onChange(null)}
            className="absolute right-2 top-2 rounded-full bg-gray-950/80 p-1.5 text-gray-300
              hover:text-white hover:bg-gray-900 border border-gray-700"
            aria-label="Retirer l'image"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="flex h-24 w-full flex-col items-center justify-center gap-1.5 rounded-xl
            border border-dashed border-gray-700 bg-gray-900/50 text-gray-500
            hover:border-purple-500 hover:text-purple-400 transition-colors"
        >
          <ImagePlus className="h-6 w-6" />
          <span className="text-xs">Choisir une image (PNG, JPEG, WebP)</span>
        </button>
      )}
      {hint && <p className="text-[10px] text-gray-600">{hint}</p>}
    </div>
  )
}
