import { useState } from "react";
import {
  CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { SurvivalCurve } from "./api";

const COLORS = ["#38bdf8", "#f97316", "#22c55e", "#a855f7", "#facc15", "#ef4444"];
const tooltipStyle = { background: "#0f172a", border: "1px solid #334155", color: "#e2e8f0" };
type Mode = "playAction" | "formation";

export default function SurvivalCard({ curve }: { curve: SurvivalCurve }) {
  const [mode, setMode] = useState<Mode>("playAction");
  const group = curve[mode];

  return (
    <div className="panel">
      <div className="card-head">
        <h2>Curva de Supervivencia del Bolsillo (Kaplan-Meier)</h2>
        <div className="toggle">
          <button className={mode === "playAction" ? "active" : ""} onClick={() => setMode("playAction")}>Play-Action</button>
          <button className={mode === "formation" ? "active" : ""} onClick={() => setMode("formation")}>Formación Ofensiva</button>
        </div>
      </div>
      <p className="muted small">
        S(t) = probabilidad de que la bolsa siga limpia t segundos después del snap. Las jugadas en que el pase sale
        antes del colapso cuentan como censuradas por la derecha.
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={group.data} margin={{ left: -10, right: 16, top: 8 }}>
          <CartesianGrid stroke="#1e293b" />
          <XAxis dataKey="t" type="number" domain={[0, curve.tMax]} ticks={[0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5]}
            tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(v: number) => `${v}s`} />
          <YAxis domain={[0, 1]} tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} />
          <Tooltip contentStyle={tooltipStyle} labelFormatter={(t) => `t = ${Number(t).toFixed(1)} s`}
            formatter={(v: number) => `${(v * 100).toFixed(1)}%`} />
          <Legend />
          <ReferenceLine x={curve.threshold} stroke="#ef4444" strokeDasharray="5 4"
            label={{ value: `${curve.threshold} s`, fill: "#ef4444", fontSize: 11, position: "insideTopRight" }} />
          {group.series.map((s, i) => (
            <Line key={s.label} type="stepAfter" dataKey={s.label} stroke={COLORS[i % COLORS.length]}
              strokeWidth={2} dot={false} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <table>
        <thead><tr><th>Serie</th><th>Jugadas</th><th>Colapsos</th><th>Censuradas</th><th>S(2.5 s)</th><th>Mediana</th></tr></thead>
        <tbody>
          {group.series.map((s, i) => (
            <tr key={s.label}>
              <td><i className="dot" style={{ background: COLORS[i % COLORS.length] }} />{s.label}</td>
              <td>{s.n.toLocaleString("es-MX")}</td><td>{s.events.toLocaleString("es-MX")}</td>
              <td>{s.censored.toLocaleString("es-MX")}</td><td>{(s.survivalAt2_5 * 100).toFixed(1)}%</td>
              <td>{s.medianSeconds != null ? `${s.medianSeconds.toFixed(1)} s` : "> 4.5 s"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
