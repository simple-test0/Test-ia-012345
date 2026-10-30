import { useHardwareInfo } from '../../hooks/useHardwareInfo'
import { Cpu, MemoryStick, WifiOff, Apple } from 'lucide-react'

export default function HardwareBadge() {
  const { hardware, offline } = useHardwareInfo(5000)

  if (offline) {
    return (
      <span className="flex items-center gap-1 text-xs text-amber-400" title="Le backend ne répond pas">
        <WifiOff size={12} /> Backend hors ligne
      </span>
    )
  }
  if (!hardware) {
    return <span className="text-xs text-gray-600">Détection du matériel…</span>
  }

  const primaryGpu = hardware.gpus?.[0]
  const ramPct = hardware.ram_total_mb
    ? Math.round((hardware.ram_used_mb / hardware.ram_total_mb) * 100)
    : 0

  return (
    <div className="flex items-center gap-3 text-xs text-gray-400">
      {primaryGpu ? (
        <span className="hidden sm:flex items-center gap-1" title="Mémoire GPU utilisée">
          <Cpu size={12} className="text-purple-400" />
          <span className="max-w-[160px] truncate">{primaryGpu.name}</span> —{' '}
          <span className="text-emerald-400">
            {(primaryGpu.vram_used_mb / 1024).toFixed(1)}
            <span className="text-gray-600">/{(primaryGpu.vram_total_mb / 1024).toFixed(1)} GB</span>
          </span>
        </span>
      ) : hardware.accelerator === 'mps' ? (
        <span className="hidden sm:flex items-center gap-1" title="GPU Apple Silicon (Metal)">
          <Apple size={12} className="text-purple-400" /> Apple GPU (MPS)
        </span>
      ) : (
        <span className="hidden sm:flex items-center gap-1" title="Aucun GPU détecté : calcul sur CPU (plus lent)">
          <Cpu size={12} className="text-gray-500" /> CPU uniquement
        </span>
      )}
      <span className="flex items-center gap-1" title={`${hardware.ram_used_mb} / ${hardware.ram_total_mb} MB`}>
        <MemoryStick size={12} className="text-blue-400" />
        <span className={ramPct > 85 ? 'text-red-400' : ramPct > 70 ? 'text-amber-400' : 'text-emerald-400'}>
          {ramPct}%
        </span>
        <span className="text-gray-600">RAM</span>
      </span>
    </div>
  )
}
