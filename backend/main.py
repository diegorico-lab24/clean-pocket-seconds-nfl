"""API: ¿Cuántos segundos tiene tu QB antes de que colapse la bolsa?

Ejecutar desde backend/:  py -m uvicorn main:app --port 8000
"""
from __future__ import annotations

import json
import math
import os
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import pocket

STATE: dict[str, Any] = {}
BEDROCK_MODEL = "amazon.nova-lite-v1:0"
MIN_TEAM_PLAYS = 50
MIN_RUSH_SNAPS = 100


# ---------------------------------------------------------------- utilidades
def clean(v):
    """Convierte tipos numpy/NaN a JSON nativo."""
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else round(f, 3)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def records(df: pd.DataFrame) -> list[dict]:
    return [clean(r) for r in df.to_dict(orient="records")]


def player_name(nfl_id) -> Optional[str]:
    if nfl_id is None or (isinstance(nfl_id, float) and math.isnan(nfl_id)):
        return None
    return STATE["names"].get(int(nfl_id))


# ---------------------------------------------------------------- resúmenes
def build_summary(m: pd.DataFrame, pff: pd.DataFrame, players: pd.DataFrame) -> dict:
    kpis = {
        "playsAnalyzed": len(m),
        "avgCleanPocketSeconds": m.cleanPocketSeconds.mean(),
        "medianCleanPocketSeconds": m.cleanPocketSeconds.median(),
        "avgTimeToThrow": m.timeToEnd.mean(),
        "collapseRate": m.collapsed.mean(),
        "avgPocketCollapseScore": m.pocketCollapseScore.mean(),
        "pffPressureRate": m.pffPressure.mean(),
        "pressureWhenCollapsed": m.loc[m.collapsed, "pffPressure"].mean(),
        "pressureWhenClean": m.loc[~m.collapsed, "pffPressure"].mean(),
        "sackRateCollapsed": (m.loc[m.collapsed, "passResult"] == "S").mean(),
        "sackRateClean": (m.loc[~m.collapsed, "passResult"] == "S").mean(),
        "threatRadius": pocket.THREAT_RADIUS,
    }

    pa = m.groupby("pff_playAction").agg(
        plays=("playId", "count"), avgCleanPocketSeconds=("cleanPocketSeconds", "mean"),
        avgTimeToThrow=("timeToEnd", "mean"), collapseRate=("collapsed", "mean"),
        pressureRate=("pffPressure", "mean"), avgPocketCollapseScore=("pocketCollapseScore", "mean"),
        avgYards=("playResult", "mean"),
    ).reset_index()
    pa["label"] = pa.pff_playAction.map({0: "Sin Play-Action", 1: "Play-Action"})

    ol = m.groupby("possessionTeam").agg(
        plays=("playId", "count"), avgCleanPocketSeconds=("cleanPocketSeconds", "mean"),
        collapseRate=("collapsed", "mean"), avgPocketCollapseScore=("pocketCollapseScore", "mean"),
        pressureRate=("pffPressure", "mean"), beatenPerPlay=("pffBeaten", "mean"),
        sacks=("pffSacks", "sum"),
    ).reset_index().rename(columns={"possessionTeam": "team"})
    ol = ol[ol.plays >= MIN_TEAM_PLAYS].sort_values("avgCleanPocketSeconds", ascending=False)

    defense = m.groupby("defensiveTeam").agg(
        plays=("playId", "count"), avgCleanPocketSeconds=("cleanPocketSeconds", "mean"),
        collapseRate=("collapsed", "mean"), pressureRate=("pffPressure", "mean"),
    ).reset_index().rename(columns={"defensiveTeam": "team"}).sort_values("avgCleanPocketSeconds")

    rush = pff[pff.pff_role == "Pass Rush"].fillna({"pff_hurry": 0, "pff_hit": 0, "pff_sack": 0})
    rs = rush.groupby("nflId").agg(
        rushSnaps=("playId", "count"), hurries=("pff_hurry", "sum"),
        hits=("pff_hit", "sum"), sacks=("pff_sack", "sum"),
        team_pos=("pff_positionLinedUp", lambda s: s.mode().iat[0] if not s.mode().empty else None),
    )
    br = m[m.collapsed].groupby("breachRusherId").agg(
        breaches=("playId", "count"), avgBreachSecond=("cleanPocketSeconds", "mean"))
    rs = rs.join(br).fillna({"breaches": 0})
    rs = rs[rs.rushSnaps >= MIN_RUSH_SNAPS].copy()
    rs["breachRate"] = rs.breaches / rs.rushSnaps
    rs["pressureRate"] = (rs.hurries + rs.hits + rs.sacks) / rs.rushSnaps
    rs = rs.join(players.set_index("nflId")[["displayName", "officialPosition"]]).reset_index()
    rs = rs.sort_values("breachRate", ascending=False)

    by_result = m.groupby("passResult").agg(
        plays=("playId", "count"), avgCleanPocketSeconds=("cleanPocketSeconds", "mean"),
        collapseRate=("collapsed", "mean")).reset_index()

    bins = np.arange(0, 6.5, 0.5)
    hist = pd.cut(m.cleanPocketSeconds.clip(upper=6.0), bins=bins, include_lowest=True, right=False)
    dist = m.groupby(hist, observed=False).agg(
        plays=("playId", "count"), collapsed=("collapsed", "sum")).reset_index()
    dist["bucket"] = [f"{b.left:.1f}-{b.right:.1f}" for b in dist.cleanPocketSeconds]
    dist = dist.drop(columns="cleanPocketSeconds")

    return clean({
        "kpis": kpis,
        "playAction": records(pa),
        "offensiveLines": {"best": records(ol.head(10)), "worst": records(ol.tail(10).iloc[::-1]),
                           "all": records(ol)},
        "defenses": records(defense),
        "passRushers": {"best": records(rs.head(10)), "worst": records(rs.tail(10).iloc[::-1])},
        "byPassResult": records(by_result),
        "cleanPocketDistribution": records(dist),
        "survival_curve": pocket.survival_curves(m),
        "teams": sorted(m.possessionTeam.dropna().unique().tolist()),
    })


# ---------------------------------------------------------------- app
@asynccontextmanager
async def lifespan(_: FastAPI):
    games, plays, players, pff = pocket.load_base()
    metrics = pocket.get_metrics(pff, plays)
    STATE.update(games=games, plays=plays, players=players, pff=pff, metrics=metrics,
                 names=dict(zip(players.nflId.astype(int), players.displayName)))
    metrics["breachRusherName"] = metrics.breachRusherId.map(player_name)
    STATE["metrics_idx"] = metrics.set_index(["gameId", "playId"]).sort_index()
    STATE["pff_idx"] = pff.set_index(["gameId", "playId"]).sort_index()
    STATE["summary"] = build_summary(metrics, pff, players)
    yield


app = FastAPI(title="Clean Pocket Seconds API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "plays": len(STATE.get("metrics", []))}


@app.get("/api/summary")
def summary():
    return STATE["summary"]


PLAY_COLS = ["gameId", "playId", "possessionTeam", "defensiveTeam", "passResult", "pff_playAction",
             "quarter", "down", "yardsToGo", "playDescription", "cleanPocketSeconds", "timeToEnd",
             "collapsed", "pocketCollapseScore", "minDistance", "breachRusherName", "pffPressure",
             "pffHurries", "pffHits", "pffSacks", "pffBeaten", "endEvent"]
SORTABLE = {"cleanPocketSeconds", "pocketCollapseScore", "timeToEnd", "minDistance"}


@app.get("/api/plays")
def list_plays(
    team: Optional[str] = Query(None, description="Equipo ofensivo (possessionTeam)"),
    defense: Optional[str] = Query(None, description="Equipo defensivo"),
    passResult: Optional[str] = Query(None, pattern="^(C|I|S|IN|R)$"),
    collapsed: Optional[bool] = None,
    sort: str = "pocketCollapseScore",
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    m = STATE["metrics"]
    if team:
        m = m[m.possessionTeam == team.upper()]
    if defense:
        m = m[m.defensiveTeam == defense.upper()]
    if passResult:
        m = m[m.passResult == passResult]
    if collapsed is not None:
        m = m[m.collapsed == collapsed]
    if sort not in SORTABLE:
        raise HTTPException(400, f"sort debe ser uno de {sorted(SORTABLE)}")
    m = m.sort_values(sort, ascending=(order == "asc"))
    return {"total": len(m), "offset": offset, "limit": limit,
            "plays": records(m[PLAY_COLS].iloc[offset:offset + limit])}


@lru_cache(maxsize=12)
def load_tracking(game_id: int) -> pd.DataFrame:
    path = pocket.TRACKING_DIR / f"tracking_{game_id}.csv"
    if not path.exists():
        raise HTTPException(404, "Partido no encontrado")
    return pd.read_csv(path, usecols=["playId", "nflId", "frameId", "jerseyNumber", "team",
                                      "playDirection", "x", "y", "s", "event"])


def play_row(game_id: int, play_id: int) -> pd.Series:
    try:
        return STATE["metrics_idx"].loc[(game_id, play_id)]
    except KeyError:
        raise HTTPException(404, "Jugada no encontrada")


@app.get("/api/play/{game_id}/{play_id}")
def play_detail(game_id: int, play_id: int):
    return Response(content=play_detail_json(game_id, play_id), media_type="application/json")


@lru_cache(maxsize=256)
def play_detail_json(game_id: int, play_id: int) -> bytes:
    return json.dumps(build_play_detail(game_id, play_id), separators=(",", ":")).encode()


def build_play_detail(game_id: int, play_id: int) -> dict:
    row = play_row(game_id, play_id)
    tr = load_tracking(game_id)
    tr = tr[tr.playId == play_id]
    roles = STATE["pff_idx"].loc[(game_id, play_id)].reset_index()[
        ["nflId", "pff_role", "pff_positionLinedUp", "pff_hurry", "pff_hit", "pff_sack",
         "pff_beatenByDefender"]]

    snap, end = int(row.snapFrame), int(row.endFrame)
    dist = pocket.rusher_distances(tr.assign(playId=play_id), roles[["nflId", "pff_role"]].assign(playId=play_id))
    dist = dist.set_index("frameId")

    frames = []
    for fid, f in tr.groupby("frameId", sort=True):
        ball = f[f.nflId.isna()]
        ppl = f.dropna(subset=["nflId"])
        ev = f.event.dropna()
        d = dist.loc[fid] if fid in dist.index else None
        frames.append({
            "frameId": int(fid),
            "t": round((fid - snap) * pocket.FRAME_SEC, 1),
            "event": ev.iat[0] if len(ev) else None,
            "ball": [ball.x.iat[0], ball.y.iat[0]] if len(ball) else None,
            "players": [[int(n), x, y] for n, x, y in zip(ppl.nflId, ppl.x, ppl.y)],
            "pocketRadius": None if d is None else d.dist,
            "closestRusherId": None if d is None else int(d.nflId),
        })

    meta = tr.dropna(subset=["nflId"]).drop_duplicates("nflId")[["nflId", "jerseyNumber", "team"]]
    meta = meta.merge(roles, on="nflId", how="left")
    meta = meta.merge(STATE["players"][["nflId", "displayName", "officialPosition"]], on="nflId", how="left")
    play = STATE["plays"].set_index(["gameId", "playId"]).loc[(game_id, play_id)]
    los = play.absoluteYardlineNumber
    return clean({
        "gameId": game_id, "playId": play_id,
        "description": play.playDescription,
        "possessionTeam": play.possessionTeam, "defensiveTeam": play.defensiveTeam,
        "passResult": play.passResult, "playAction": int(play.pff_playAction),
        "coverage": play.pff_passCoverage, "down": play.down, "yardsToGo": play.yardsToGo,
        "lineOfScrimmage": los, "playDirection": tr.playDirection.iat[0] if len(tr) else None,
        "snapFrame": snap, "endFrame": end, "endEvent": row.endEvent,
        "threatRadius": pocket.THREAT_RADIUS,
        "metrics": {
            "cleanPocketSeconds": row.cleanPocketSeconds, "timeToEnd": row.timeToEnd,
            "collapsed": bool(row.collapsed),
            "collapseSecond": row.cleanPocketSeconds if row.collapsed else None,
            "collapseFrame": None if pd.isna(row.breachFrame) else int(row.breachFrame),
            "breachRusherId": row.breachRusherId, "breachRusherName": row.breachRusherName,
            "pocketCollapseScore": row.pocketCollapseScore, "minDistance": row.minDistance,
            "timeInsideRadius": row.timeInsideRadius,
            "pffHurries": row.pffHurries, "pffHits": row.pffHits, "pffSacks": row.pffSacks,
            "pffBeaten": row.pffBeaten,
        },
        "players": records(meta),
        "frames": frames,
    })


# ---------------------------------------------------------------- análisis IA
class AnalyzeRequest(BaseModel):
    gameId: int
    playId: int


def play_context(game_id: int, play_id: int) -> dict:
    row = play_row(game_id, play_id)
    m = STATE["metrics"]
    team = m[m.possessionTeam == row.possessionTeam]
    roles = STATE["pff_idx"].loc[(game_id, play_id)].reset_index()
    names = STATE["names"]
    beaten = [names.get(int(n), str(n)) for n in roles[roles.pff_beatenByDefender == 1].nflId]
    pressers = [names.get(int(n), str(n)) for n in roles[
        (roles[["pff_hurry", "pff_hit", "pff_sack"]].fillna(0).sum(axis=1) > 0)].nflId]
    qb = roles[roles.pff_role == "Pass"].nflId
    return clean({
        "jugada": row.playDescription, "ofensiva": row.possessionTeam, "defensiva": row.defensiveTeam,
        "qb": names.get(int(qb.iat[0])) if len(qb) else None,
        "down": row.down, "yardas_por_avanzar": row.yardsToGo, "resultado": row.passResult,
        "play_action": bool(row.pff_playAction), "cobertura": row.pff_passCoverage,
        "segundos_bolsa_limpia": row.cleanPocketSeconds, "tiempo_hasta_pase": row.timeToEnd,
        "colapso": bool(row.collapsed), "rusher_que_rompio": row.breachRusherName,
        "pocket_collapse_score": row.pocketCollapseScore, "distancia_minima": row.minDistance,
        "rushers": row.rushers, "bloqueadores": row.blockers,
        "pff_hurries": row.pffHurries, "pff_hits": row.pffHits, "pff_sacks": row.pffSacks,
        "bloqueadores_vencidos": beaten, "defensores_con_presion": pressers,
        "promedio_equipo_cps": team.cleanPocketSeconds.mean(),
        "promedio_liga_cps": m.cleanPocketSeconds.mean(),
    })


def fallback_analysis(c: dict) -> str:
    cps, liga, eq = c["segundos_bolsa_limpia"], c["promedio_liga_cps"], c["promedio_equipo_cps"]
    diff = cps - liga
    lines = [
        f"{c['ofensiva']} vs {c['defensiva']}: {c['qb'] or 'el QB'} tuvo {cps:.1f} s de bolsa limpia "
        f"({'+' if diff >= 0 else ''}{diff:.1f} s frente al promedio de la liga de {liga:.2f} s; "
        f"su equipo promedia {eq:.2f} s).",
    ]
    if c["colapso"]:
        lines.append(f"La bolsa colapsó: {c['rusher_que_rompio'] or 'un pass rusher'} entró al radio de "
                     f"{pocket.THREAT_RADIUS} yardas en el segundo {cps:.1f}, y el QB soltó el balón "
                     f"(o fue capturado) a los {c['tiempo_hasta_pase']:.1f} s.")
    else:
        lines.append(f"Ningún rusher entró al radio de {pocket.THREAT_RADIUS} yardas; la distancia mínima fue "
                     f"{c['distancia_minima']:.1f} yardas y el pase salió a los {c['tiempo_hasta_pase']:.1f} s.")
    lines.append(f"La defensa mandó {c['rushers']} rushers contra {c['bloqueadores']} bloqueadores"
                 f"{' con Play-Action' if c['play_action'] else ''} y cobertura {c['cobertura'] or 'N/D'}.")
    pff = []
    if c["pff_sacks"]:
        pff.append(f"{c['pff_sacks']} sack")
    if c["pff_hits"]:
        pff.append(f"{c['pff_hits']} golpe(s)")
    if c["pff_hurries"]:
        pff.append(f"{c['pff_hurries']} hurry")
    if pff:
        lines.append(f"PFF acredita {', '.join(pff)} a {', '.join(c['defensores_con_presion'])}.")
    if c["bloqueadores_vencidos"]:
        lines.append(f"Bloqueadores vencidos según PFF: {', '.join(c['bloqueadores_vencidos'])}.")
    if c["colapso"] and cps < 2.0:
        lines.append("Recomendación: la presión llegó antes de 2 s; conviene un plan de pase rápido "
                     "(rutas cortas, lectura en 3 pasos) o ayuda extra de TE/RB en protección.")
    elif c["colapso"]:
        lines.append("Recomendación: la protección aguantó lo suficiente para una lectura completa; "
                     "el ajuste está en el ritmo del QB para soltar antes del colapso.")
    else:
        lines.append("Recomendación: la línea ganó la jugada; este esquema de protección se puede repetir "
                     "contra este frente defensivo.")
    return " ".join(lines)


def bedrock_analysis(c: dict) -> str:
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        config=Config(read_timeout=25, connect_timeout=5, retries={"max_attempts": 1}),
    )
    prompt = (
        "Eres un coordinador ofensivo de la NFL. Con estos datos de tracking y PFF, escribe en español "
        "un análisis táctico breve (máximo 6 oraciones) de la protección de la bolsa: qué pasó, quién "
        "falló o ganó, y una recomendación concreta. Datos: " + str(c)
    )
    resp = client.converse(
        modelId=BEDROCK_MODEL,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 500, "temperature": 0.4},
    )
    return resp["output"]["message"]["content"][0]["text"]


@app.post("/api/analyze-play")
def analyze_play(req: AnalyzeRequest):
    c = play_context(req.gameId, req.playId)
    has_creds = bool(os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"))
    if has_creds:
        try:
            return {"source": "bedrock", "model": BEDROCK_MODEL, "analysis": bedrock_analysis(c), "context": c}
        except Exception as e:  # noqa: BLE001 - cualquier fallo cae al análisis local
            return {"source": "fallback", "reason": f"Bedrock no disponible: {type(e).__name__}",
                    "analysis": fallback_analysis(c), "context": c}
    return {"source": "fallback", "reason": "Sin credenciales AWS en variables de entorno",
            "analysis": fallback_analysis(c), "context": c}
