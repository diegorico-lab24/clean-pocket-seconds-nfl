// Cliente tipado del backend. VITE_API_URL permite apuntar a otro host; por defecto usa el proxy de Vite.
const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

export interface Kpis {
  playsAnalyzed: number;
  avgCleanPocketSeconds: number;
  medianCleanPocketSeconds: number;
  avgTimeToThrow: number;
  collapseRate: number;
  avgPocketCollapseScore: number;
  pffPressureRate: number;
  pressureWhenCollapsed: number;
  pressureWhenClean: number;
  sackRateCollapsed: number;
  sackRateClean: number;
  threatRadius: number;
}

export interface TeamRow {
  team: string;
  plays: number;
  avgCleanPocketSeconds: number;
  collapseRate: number;
  avgPocketCollapseScore?: number;
  pressureRate: number;
  beatenPerPlay?: number;
  sacks?: number;
}

export interface RusherRow {
  nflId: number;
  displayName: string;
  officialPosition: string;
  rushSnaps: number;
  breaches: number;
  breachRate: number;
  avgBreachSecond: number | null;
  hurries: number;
  hits: number;
  sacks: number;
  pressureRate: number;
}

export interface PlayActionRow {
  label: string;
  plays: number;
  avgCleanPocketSeconds: number;
  avgTimeToThrow: number;
  collapseRate: number;
  pressureRate: number;
  avgPocketCollapseScore: number;
  avgYards: number;
}

export interface SurvivalSeriesMeta {
  label: string;
  n: number;
  events: number;
  censored: number;
  medianSeconds: number | null;
  survivalAt2_5: number;
}

export interface SurvivalGroup {
  series: SurvivalSeriesMeta[];
  data: ({ t: number } & Record<string, number>)[];
}

export interface SurvivalCurve {
  tMax: number;
  step: number;
  threshold: number;
  overall: SurvivalGroup;
  playAction: SurvivalGroup;
  formation: SurvivalGroup;
}

export interface Summary {
  survival_curve: SurvivalCurve;
  kpis: Kpis;
  playAction: PlayActionRow[];
  offensiveLines: { best: TeamRow[]; worst: TeamRow[]; all: TeamRow[] };
  defenses: TeamRow[];
  passRushers: { best: RusherRow[]; worst: RusherRow[] };
  byPassResult: { passResult: string; plays: number; avgCleanPocketSeconds: number; collapseRate: number }[];
  cleanPocketDistribution: { bucket: string; plays: number; collapsed: number }[];
  teams: string[];
}

export interface PlayRow {
  gameId: number;
  playId: number;
  possessionTeam: string;
  defensiveTeam: string;
  passResult: string | null;
  pff_playAction: number;
  quarter: number;
  down: number;
  yardsToGo: number;
  playDescription: string;
  cleanPocketSeconds: number;
  timeToEnd: number;
  collapsed: boolean;
  pocketCollapseScore: number;
  minDistance: number;
  breachRusherName: string | null;
  pffPressure: boolean;
}

export interface Frame {
  frameId: number;
  t: number;
  event: string | null;
  ball: [number, number] | null;
  players: [number, number, number][];
  pocketRadius: number | null;
  closestRusherId: number | null;
}

export interface PlayerMeta {
  nflId: number;
  jerseyNumber: number | null;
  team: string;
  pff_role: string | null;
  displayName: string | null;
  officialPosition: string | null;
}

export interface PlayDetail {
  gameId: number;
  playId: number;
  description: string;
  possessionTeam: string;
  defensiveTeam: string;
  passResult: string | null;
  playAction: number;
  coverage: string | null;
  down: number;
  yardsToGo: number;
  lineOfScrimmage: number;
  playDirection: string;
  snapFrame: number;
  endFrame: number;
  endEvent: string;
  threatRadius: number;
  metrics: {
    cleanPocketSeconds: number;
    timeToEnd: number;
    collapsed: boolean;
    collapseSecond: number | null;
    collapseFrame: number | null;
    breachRusherName: string | null;
    pocketCollapseScore: number;
    minDistance: number;
    timeInsideRadius: number;
    pffHurries: number;
    pffHits: number;
    pffSacks: number;
    pffBeaten: number;
  };
  players: PlayerMeta[];
  frames: Frame[];
}

export interface Analysis {
  source: "bedrock" | "fallback";
  model?: string;
  reason?: string;
  analysis: string;
}

async function get<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  summary: () => get<Summary>("/api/summary"),
  plays: (params: Record<string, string>) =>
    get<{ total: number; plays: PlayRow[] }>(`/api/plays?${new URLSearchParams(params)}`),
  play: (g: number, p: number) => get<PlayDetail>(`/api/play/${g}/${p}`),
  analyze: (gameId: number, playId: number) =>
    get<Analysis>("/api/analyze-play", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ gameId, playId }),
    }),
};
