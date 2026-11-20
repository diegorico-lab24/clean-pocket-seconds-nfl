import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, type PlayRow, type RusherRow, type Summary, type TeamRow } from "./api";
import FieldViewer from "./FieldViewer";
import SurvivalCard from "./SurvivalCard";

const RESULTS: Record<string, string> = { C: "Completo", I: "Incompleto", S: "Sack", IN: "Intercepción", R: "Scramble" };
const pct = (v: number | null | undefined) => (v == null ? "–" : `${(v * 100).toFixed(1)}%`);
const sec = (v: number | null | undefined) => (v == null ? "–" : `${v.toFixed(2)} s`);
const tooltipStyle = { background: "#0f172a", border: "1px solid #334155", color: "#e2e8f0" };

export default function App() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [team, setTeam] = useState("");
  const [result, setResult] = useState("");
  const [sort, setSort] = useState("pocketCollapseScore");
  const [plays, setPlays] = useState<PlayRow[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<{ gameId: number; playId: number } | null>(null);

  useEffect(() => {
    api.summary().then(setSummary).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    const params: Record<string, string> = { sort, order: sort === "cleanPocketSeconds" ? "asc" : "desc", limit: "40" };
    if (team) params.team = team;
    if (result) params.passResult = result;
    api
      .plays(params)
      .then((r) => {
        setPlays(r.plays);
        setTotal(r.total);
        if (r.plays.length && !selected) setSelected({ gameId: r.plays[0].gameId, playId: r.plays[0].playId });
      })
      .catch((e: Error) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [team, result, sort]);

  if (error) return <div className="app"><div className="panel error">Error conectando con el backend: {error}. ¿Está corriendo en el puerto 8000?</div></div>;
  if (!summary) return <div className="app"><div className="panel muted">Cargando métricas de 8,557 jugadas…</div></div>;

  const k = summary.kpis;
  const ol = summary.offensiveLines.all;
  const leagueAvg = k.avgCleanPocketSeconds;

  return (
    <div className="app">
      <header>
        <div>
          <div className="eyebrow">NFL Big Data Bowl · Semanas 1-8 · 2021</div>
          <h1>¿Cuántos segundos tiene tu QB antes de que colapse la bolsa?</h1>
          <p className="muted">
            Clean Pocket Seconds: tiempo desde el snap hasta que el Pass Rush más cercano entra a menos de {k.threatRadius} yardas del QB, medido cada 0.1 s y cruzado con PFF.
          </p>
        </div>
      </header>

      <section className="kpis">
        <Kpi label="Jugadas analizadas" value={k.playsAnalyzed.toLocaleString("es-MX")} />
        <Kpi label="Bolsa limpia promedio" value={sec(k.avgCleanPocketSeconds)} sub={`mediana ${sec(k.medianCleanPocketSeconds)}`} />
        <Kpi label="Tiempo hasta el pase" value={sec(k.avgTimeToThrow)} />
        <Kpi label="Bolsas colapsadas" value={pct(k.collapseRate)} tone="bad" />
        <Kpi label="Presión PFF si colapsa" value={pct(k.pressureWhenCollapsed)} sub={`vs ${pct(k.pressureWhenClean)} con bolsa limpia`} />
        <Kpi label="Sacks si colapsa" value={pct(k.sackRateCollapsed)} sub={`vs ${pct(k.sackRateClean)} sin colapso`} tone="bad" />
      </section>

      <section className="grid two">
        <div className="panel">
          <h2>Protección por línea ofensiva</h2>
          <p className="muted small">Segundos de bolsa limpia promedio. Línea punteada = promedio de la liga.</p>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={ol} margin={{ left: -10, right: 10 }}>
              <CartesianGrid stroke="#1e293b" vertical={false} />
              <XAxis dataKey="team" tick={{ fill: "#94a3b8", fontSize: 10 }} interval={0} angle={-60} textAnchor="end" height={45} />
              <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} domain={[0, "auto"]} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => `${v.toFixed(2)} s`} />
              <Bar dataKey="avgCleanPocketSeconds" name="Bolsa limpia (s)">
                {ol.map((r) => (
                  <Cell key={r.team} fill={r.avgCleanPocketSeconds >= leagueAvg ? "#22c55e" : "#ef4444"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="panel">
          <h2>Impacto del Play-Action</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={summary.playAction.map((r) => ({ ...r, collapsePct: r.collapseRate * 100, pressurePct: r.pressureRate * 100 }))}>
              <CartesianGrid stroke="#1e293b" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: "#94a3b8" }} />
              <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => v.toFixed(1)} />
              <Legend />
              <Bar dataKey="collapsePct" name="% colapso" fill="#ef4444" />
              <Bar dataKey="pressurePct" name="% presión PFF" fill="#f97316" />
            </BarChart>
          </ResponsiveContainer>
          <table>
            <thead><tr><th></th><th>Jugadas</th><th>Bolsa limpia</th><th>Hasta pase</th><th>PCS</th><th>Yardas</th></tr></thead>
            <tbody>
              {summary.playAction.map((r) => (
                <tr key={r.label}>
                  <td>{r.label}</td><td>{r.plays}</td><td>{sec(r.avgCleanPocketSeconds)}</td>
                  <td>{sec(r.avgTimeToThrow)}</td><td>{r.avgPocketCollapseScore.toFixed(1)}</td><td>{r.avgYards.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid two">
        <div className="panel">
          <h2>Distribución de segundos de bolsa limpia</h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={summary.cleanPocketDistribution.map((d) => ({ ...d, clean: d.plays - d.collapsed }))}>
              <CartesianGrid stroke="#1e293b" vertical={false} />
              <XAxis dataKey="bucket" tick={{ fill: "#94a3b8", fontSize: 10 }} />
              <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend />
              <Bar dataKey="collapsed" stackId="a" name="Colapsó" fill="#ef4444" />
              <Bar dataKey="clean" stackId="a" name="Nunca colapsó" fill="#22c55e" />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="panel">
          <h2>Resultado del pase vs bolsa</h2>
          <table>
            <thead><tr><th>Resultado</th><th>Jugadas</th><th>Bolsa limpia</th><th>% colapso</th></tr></thead>
            <tbody>
              {summary.byPassResult.map((r) => (
                <tr key={r.passResult}>
                  <td>{RESULTS[r.passResult] ?? r.passResult}</td><td>{r.plays}</td>
                  <td>{sec(r.avgCleanPocketSeconds)}</td><td>{pct(r.collapseRate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid">
        <SurvivalCard curve={summary.survival_curve} />
      </section>

      <section className="grid four">
        <TeamTable title="Mejores líneas ofensivas" rows={summary.offensiveLines.best} tone="good" />
        <TeamTable title="Peores líneas ofensivas" rows={summary.offensiveLines.worst} tone="bad" />
        <RusherTable title="Pass rushers más letales" rows={summary.passRushers.best} tone="bad" />
        <RusherTable title="Pass rushers menos efectivos" rows={summary.passRushers.worst} tone="good" />
      </section>

      <section className="grid viewer-grid">
        <div className="panel catalog">
          <h2>Catálogo de jugadas <span className="muted small">({total.toLocaleString("es-MX")})</span></h2>
          <div className="filters">
            <select value={team} onChange={(e) => setTeam(e.target.value)}>
              <option value="">Todas las ofensivas</option>
              {summary.teams.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <select value={result} onChange={(e) => setResult(e.target.value)}>
              <option value="">Todos los resultados</option>
              {Object.entries(RESULTS).map(([k2, v]) => <option key={k2} value={k2}>{v}</option>)}
            </select>
            <select value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="pocketCollapseScore">Mayor colapso (PCS)</option>
              <option value="cleanPocketSeconds">Menos bolsa limpia</option>
              <option value="timeToEnd">Más tiempo hasta el pase</option>
            </select>
          </div>
          <div className="play-list">
            {plays.map((p) => {
              const active = selected?.gameId === p.gameId && selected.playId === p.playId;
              return (
                <button key={`${p.gameId}-${p.playId}`} className={`play-item ${active ? "active" : ""}`}
                  onClick={() => setSelected({ gameId: p.gameId, playId: p.playId })}>
                  <div className="play-top">
                    <b>{p.possessionTeam}</b> vs {p.defensiveTeam} · Q{p.quarter} · {p.down}ª&{p.yardsToGo}
                    <span className={`pill ${p.collapsed ? "bad" : "good"}`}>{p.cleanPocketSeconds.toFixed(1)} s</span>
                  </div>
                  <div className="small muted ellipsis">{p.playDescription}</div>
                  <div className="small">
                    PCS {p.pocketCollapseScore.toFixed(0)} · {RESULTS[p.passResult ?? ""] ?? "–"}
                    {p.pff_playAction ? " · PA" : ""}{p.breachRusherName ? ` · ${p.breachRusherName}` : ""}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
        {selected ? <FieldViewer gameId={selected.gameId} playId={selected.playId} /> : <div className="panel muted">Elige una jugada</div>}
      </section>

      <footer className="small muted">
        PCS (Pocket Collapse Score, 0-100) = 60% del tiempo con un rusher dentro de {k.threatRadius} yd + 40% intensidad PFF (hurry, hit ×1.5, sack ×2).
        Fuente: NFL Next Gen Stats y PFF.
      </footer>
    </div>
  );
}

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "good" | "bad" }) {
  return (
    <div className={`panel kpi ${tone ?? ""}`}>
      <div className="small muted">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="small muted">{sub}</div>}
    </div>
  );
}

function TeamTable({ title, rows, tone }: { title: string; rows: TeamRow[]; tone: "good" | "bad" }) {
  return (
    <div className="panel">
      <h3 className={tone}>{title}</h3>
      <table>
        <thead><tr><th>Equipo</th><th>Bolsa</th><th>Colapso</th><th>Sacks</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.team}><td>{r.team}</td><td>{sec(r.avgCleanPocketSeconds)}</td><td>{pct(r.collapseRate)}</td><td>{r.sacks}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RusherTable({ title, rows, tone }: { title: string; rows: RusherRow[]; tone: "good" | "bad" }) {
  return (
    <div className="panel">
      <h3 className={tone}>{title}</h3>
      <table>
        <thead><tr><th>Jugador</th><th>Rompe</th><th>Seg.</th><th>H/G/S</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.nflId}>
              <td title={`${r.rushSnaps} rush snaps`}>{r.displayName} <span className="muted small">{r.officialPosition}</span></td>
              <td>{pct(r.breachRate)}</td>
              <td>{r.avgBreachSecond != null ? r.avgBreachSecond.toFixed(1) : "–"}</td>
              <td>{r.hurries}/{r.hits}/{r.sacks}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
