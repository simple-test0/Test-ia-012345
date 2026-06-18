import { useHardwareInfo } from '../../hooks/useHardwareInfo'
import { Cpu, MemoryStick } from 'lucide-react'

export default function HardwareBadge() {
  const { hardware } = useHardwareInfo(5000)

  if (!hardware) {
    return <span className="text-xs text-gray-600">No hardware info</span>
  }

  const gpus = (hardware.gpus as Array<Record<string, unknown>>) || []
  const primaryGpu = gpus[0]
  const ramUsedMb = (hardware.ram_used_mb as number) || 0
  const ramTotalMb = (hardware.ram_total_mb as number) || 0
  const ramPct = ramTotalMb > 0 ? Math.round((ramUsedMb / ramTotalMb) * 100) : 0

  return (
    <div className="flex items-center gap-3 text-xs text-gray-400">
      {primaryGpu && (
        <span className="flex items-center gap-1">
          <Cpu size={12} className="text-purple-400" />
          {primaryGpu.name as string} —{' '}
          <span className="text-emerald-400">
            {primaryGpu.vram_used_mb as number}
            <span className="text-gray-600">/{primaryGpu.vram_total_mb as number} MB</span>
          </span>
        </span>
      )}
      <span className="flex items-center gap-1">
        <MemoryStick size={12} className="text-blue-400" />
        <span className={ramPct > 80 ? 'text-amber-400' : 'text-emerald-400'}>{ramPct}%</span>
        <span className="text-gray-600">RAM</span>
      </span>
    </div>
  )
}
