import { useEffect, useMemo, useState } from "react";
import { api, type Analysis, type PlayDetail } from "./api";

const FIELD_W = 120;
const FIELD_H = 53.3;

function pocketColor(radius: number | null, threat: number): string {
  if (radius === null) return "#64748b";
  if (radius < threat) return "#ef4444";
  if (radius < threat + 1.5) return "#facc15";
  return "#22c55e";
}

export default function FieldViewer({ gameId, playId }: { gameId: number; playId: number }) {
  const [play, setPlay] = useState<PlayDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  useEffect(() => {
    setPlay(null);
    setAnalysis(null);
    setPlaying(false);
    setError(null);
    api
      .play(gameId, playId)
      .then((p) => {
        setPlay(p);
        const snapIdx = p.frames.findIndex((f) => f.frameId === p.snapFrame);
        setIdx(Math.max(0, snapIdx));
      })
      .catch((e: Error) => setError(e.message));
  }, [gameId, playId]);

  useEffect(() => {
    if (!playing || !play) return;
    const id = window.setInterval(() => {
      setIdx((i) => {
        if (i >= play.frames.length - 1) {
          setPlaying(false);
          return i;
        }
        return i + 1;
      });
    }, 100);
    return () => window.clearInterval(id);
  }, [playing, play]);

  const meta = useMemo(() => new Map((play?.players ?? []).map((p) => [p.nflId, p])), [play]);
  const qbId = useMemo(() => play?.players.find((p) => p.pff_role === "Pass")?.nflId, [play]);

  if (error) return <div className="panel error">No se pudo cargar la jugada: {error}</div>;
  if (!play) return <div className="panel muted">Cargando jugada…</div>;

  const frame = play.frames[idx];
  const qb = frame.players.find(([id]) => id === qbId);
  const inWindow = frame.frameId >= play.snapFrame && frame.frameId <= play.endFrame;
  const color = pocketColor(inWindow ? frame.pocketRadius : null, play.threatRadius);
  const collapsedNow = play.metrics.collapseFrame !== null && frame.frameId >= play.metrics.collapseFrame && inWindow;
  const tMin = play.frames[0].t;
  const tMax = play.frames[play.frames.length - 1].t;

  const runAnalysis = () => {
    setAnalyzing(true);
    api
      .analyze(gameId, playId)
      .then(setAnalysis)
      .catch((e: Error) => setAnalysis({ source: "fallback", analysis: `Error: ${e.message}` }))
      .finally(() => setAnalyzing(false));
  };

  return (
    <div className="panel viewer">
      <div className="viewer-head">
        <div>
          <h3>
            {play.possessionTeam} vs {play.defensiveTeam} · {play.down}ª y {play.yardsToGo}
            {play.playAction ? <span className="tag">Play-Action</span> : null}
            {play.coverage ? <span className="tag ghost">{play.coverage}</span> : null}
          </h3>
          <p className="muted small">{play.description}</p>
        </div>
        <div className="viewer-metrics">
          <Metric label="Bolsa limpia" value={`${play.metrics.cleanPocketSeconds.toFixed(1)} s`} />
          <Metric label="Hasta el pase" value={`${play.metrics.timeToEnd.toFixed(1)} s`} />
          <Metric
            label="Colapso"
            value={play.metrics.collapseSecond !== null ? `seg ${play.metrics.collapseSecond.toFixed(1)}` : "No"}
            tone={play.metrics.collapsed ? "bad" : "good"}
          />
          <Metric label="PCS" value={play.metrics.pocketCollapseScore.toFixed(0)} />
        </div>
      </div>

      <svg viewBox={`0 0 ${FIELD_W} ${FIELD_H}`} className="field">
        <rect x={0} y={0} width={FIELD_W} height={FIELD_H} fill="#0f3d24" />
        <rect x={0} y={0} width={10} height={FIELD_H} fill="#0b2e1b" />
        <rect x={110} y={0} width={10} height={FIELD_H} fill="#0b2e1b" />
        {Array.from({ length: 21 }, (_, i) => 10 + i * 5).map((x) => (
          <line key={x} x1={x} x2={x} y1={0} y2={FIELD_H} stroke="#ffffff" strokeOpacity={x % 10 === 0 ? 0.35 : 0.15} strokeWidth={0.15} />
        ))}
        {Array.from({ length: 9 }, (_, i) => 20 + i * 10).map((x) => (
          <text key={`n${x}`} x={x} y={4} className="yard-num">
            {x <= 60 ? x - 10 : 110 - x}
          </text>
        ))}
        <line x1={play.lineOfScrimmage} x2={play.lineOfScrimmage} y1={0} y2={FIELD_H} stroke="#38bdf8" strokeWidth={0.3} strokeDasharray="1 0.6" />

        {qb && inWindow && frame.pocketRadius !== null && (
          <>
            <circle cx={qb[1]} cy={qb[2]} r={Math.min(frame.pocketRadius, 15)} fill={color} fillOpacity={0.12} stroke={color} strokeWidth={0.25} />
            <circle cx={qb[1]} cy={qb[2]} r={play.threatRadius} fill="none" stroke="#ef4444" strokeOpacity={0.6} strokeWidth={0.15} strokeDasharray="0.6 0.4" />
          </>
        )}

        {frame.players.map(([id, x, y]) => {
          const m = meta.get(id);
          const offense = m?.team === play.possessionTeam;
          const isQb = id === qbId;
          const isClosest = inWindow && id === frame.closestRusherId;
          const fill = isQb ? "#f8fafc" : offense ? "#3b82f6" : m?.pff_role === "Pass Rush" ? "#f97316" : "#a855f7";
          return (
            <g key={id}>
              <circle cx={x} cy={y} r={0.9} fill={fill} stroke={isClosest ? "#ef4444" : "#0f172a"} strokeWidth={isClosest ? 0.35 : 0.12} />
              <text x={x} y={y + 0.35} className={`jersey ${isQb ? "dark" : ""}`}>
                {m?.jerseyNumber ?? ""}
              </text>
            </g>
          );
        })}
        {frame.ball && <ellipse cx={frame.ball[0]} cy={frame.ball[1]} rx={0.55} ry={0.35} fill="#a16207" stroke="#fde68a" strokeWidth={0.1} />}
      </svg>

      <div className="controls">
        <button onClick={() => (idx >= play.frames.length - 1 ? (setIdx(0), setPlaying(true)) : setPlaying(!playing))}>
          {playing ? "⏸ Pausa" : "▶ Play"}
        </button>
        <input
          type="range"
          min={0}
          max={play.frames.length - 1}
          value={idx}
          onChange={(e) => {
            setPlaying(false);
            setIdx(Number(e.target.value));
          }}
        />
        <span className="clock">
          {frame.t >= 0 ? "+" : ""}
          {frame.t.toFixed(1)} s <span className="muted small">({tMin.toFixed(1)} → {tMax.toFixed(1)})</span>
        </span>
        <span className="pocket-state" style={{ color }}>
          {!inWindow
            ? frame.frameId < play.snapFrame ? "Pre-snap" : "Balón fuera"
            : collapsedNow
              ? `¡Colapso! ${frame.pocketRadius?.toFixed(1)} yd`
              : `Radio ${frame.pocketRadius?.toFixed(1) ?? "–"} yd`}
        </span>
      </div>
      <div className="legend small muted">
        <span><i style={{ background: "#f8fafc" }} /> QB</span>
        <span><i style={{ background: "#3b82f6" }} /> Ofensiva</span>
        <span><i style={{ background: "#f97316" }} /> Pass Rush</span>
        <span><i style={{ background: "#a855f7" }} /> Cobertura</span>
        <span>Verde &gt; {(play.threatRadius + 1.5).toFixed(1)} yd · Amarillo · Rojo &lt; {play.threatRadius} yd</span>
        {play.metrics.breachRusherName && <span>Rompió la bolsa: <b>{play.metrics.breachRusherName}</b></span>}
      </div>

      <div className="analysis">
        <button className="primary" onClick={runAnalysis} disabled={analyzing}>
          {analyzing ? "Analizando…" : "🧠 Análisis táctico"}
        </button>
        {analysis && (
          <div className="analysis-box">
            <div className="small muted">
              Fuente: {analysis.source === "bedrock" ? `Amazon Bedrock (${analysis.model})` : `análisis local con datos${analysis.reason ? ` · ${analysis.reason}` : ""}`}
            </div>
            <p>{analysis.analysis}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  return (
    <div className={`metric ${tone ?? ""}`}>
      <div className="small muted">{label}</div>
      <div className="metric-value">{value}</div>
    </div>
  );
}
