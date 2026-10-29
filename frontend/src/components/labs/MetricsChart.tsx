import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export interface EpochMetric {
  epoch: number
  train_loss?: number
  val_loss?: number
  train_acc?: number
  val_acc?: number
}

/** Loss / accuracy curves per epoch. */
export default function MetricsChart({ data }: { data: EpochMetric[] }) {
  if (data.length < 2) return null
  return (
    <div className="h-40 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" />
          <XAxis dataKey="epoch" stroke="#6b7280" fontSize={10} tickLine={false} />
          <YAxis yAxisId="loss" stroke="#6b7280" fontSize={10} tickLine={false} />
          <YAxis yAxisId="acc" orientation="right" domain={[0, 1]} hide />
          <Tooltip
            contentStyle={{ background: '#111827', border: '1px solid #374151', fontSize: 11, borderRadius: 8 }}
            labelFormatter={(e) => `epoch ${e}`}
          />
          <Legend wrapperStyle={{ fontSize: 10 }} iconSize={8} />
          <Line yAxisId="loss" type="monotone" dataKey="train_loss" name="train loss" stroke="#a78bfa" dot={false} strokeWidth={2} isAnimationActive={false} />
          <Line yAxisId="loss" type="monotone" dataKey="val_loss" name="val loss" stroke="#f472b6" dot={false} strokeWidth={2} isAnimationActive={false} />
          <Line yAxisId="acc" type="monotone" dataKey="val_acc" name="val acc" stroke="#34d399" dot={false} strokeWidth={1.5} strokeDasharray="4 2" isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
