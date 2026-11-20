"""Cálculo de Clean Pocket Seconds (CPS) y Pocket Collapse Score (PCS).

Para cada jugada, entre el snap y el pase (o sack), se mide cuadro por cuadro
(0.1 s por frame) la distancia del Pass Rush más cercano al QB (pff_role == "Pass").
CPS = segundos desde el snap hasta que un defensor entra al radio de amenaza
(< 2.5 yardas). Si nadie entra, CPS = tiempo total hasta el pase.
"""
from __future__ import annotations

import os
import pickle
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TRACKING_DIR = DATA_DIR / "tracking"
CACHE_DIR = Path(__file__).resolve().parent / "cache"
CACHE_FILE = CACHE_DIR / "pocket_metrics_v1.pkl"

FRAME_SEC = 0.1
THREAT_RADIUS = 2.5
SNAP_EVENTS = {"ball_snap", "autoevent_ballsnap"}
END_EVENTS = {
    "pass_forward", "autoevent_passforward", "qb_sack", "qb_strip_sack",
    "pass_shovel", "run", "fumble",
}


def load_base():
    games = pd.read_csv(DATA_DIR / "games.csv")
    plays = pd.read_csv(DATA_DIR / "plays.csv")
    players = pd.read_csv(DATA_DIR / "players.csv")
    pff = pd.read_csv(DATA_DIR / "pffScoutingData.csv")
    return games, plays, players, pff


def play_windows(events: pd.DataFrame, last_frames: pd.Series) -> pd.DataFrame:
    """Frame de snap y de fin (pase/sack) por jugada."""
    snap = events[events.event.isin(SNAP_EVENTS)].groupby("playId").frameId.min().rename("snapFrame")
    win = pd.DataFrame({"lastFrame": last_frames}).join(snap)
    win["snapFrame"] = win["snapFrame"].fillna(1).astype(int)
    end = events[events.event.isin(END_EVENTS)].merge(win[["snapFrame"]], left_on="playId", right_index=True)
    end = end[end.frameId > end.snapFrame].sort_values("frameId").groupby("playId").first()
    win = win.join(end[["frameId", "event"]].rename(columns={"frameId": "endFrame", "event": "endEvent"}))
    win["endEvent"] = win["endEvent"].fillna("end_of_tracking")
    win["endFrame"] = win["endFrame"].fillna(win["lastFrame"]).astype(int)
    return win


def rusher_distances(track: pd.DataFrame, roles: pd.DataFrame) -> pd.DataFrame:
    """Distancia mínima QB - Pass Rush más cercano por (playId, frameId)."""
    tt = track.dropna(subset=["nflId"]).merge(roles, on=["playId", "nflId"], how="inner")
    qb = tt[tt.pff_role == "Pass"][["playId", "frameId", "x", "y"]]
    ru = tt[tt.pff_role == "Pass Rush"][["playId", "frameId", "nflId", "x", "y"]]
    m = ru.merge(qb, on=["playId", "frameId"], suffixes=("", "_qb"))
    if m.empty:
        return pd.DataFrame(columns=["playId", "frameId", "nflId", "dist"])
    m["dist"] = np.hypot(m.x - m.x_qb, m.y - m.y_qb)
    idx = m.groupby(["playId", "frameId"]).dist.idxmin()
    return m.loc[idx, ["playId", "frameId", "nflId", "dist"]].reset_index(drop=True)


def compute_game(args) -> pd.DataFrame:
    game_id, roles = args
    track = pd.read_csv(
        TRACKING_DIR / f"tracking_{game_id}.csv",
        usecols=["playId", "nflId", "frameId", "x", "y", "event"],
    )
    events = track.dropna(subset=["event"])[["playId", "frameId", "event"]].drop_duplicates()
    win = play_windows(events, track.groupby("playId").frameId.max())
    pf = rusher_distances(track, roles).merge(win[["snapFrame", "endFrame"]], left_on="playId", right_index=True)
    pf = pf[(pf.frameId >= pf.snapFrame) & (pf.frameId <= pf.endFrame)]

    inside = pf[pf.dist < THREAT_RADIUS].sort_values("frameId")
    breach = inside.groupby("playId").first()[["frameId", "nflId"]].rename(
        columns={"frameId": "breachFrame", "nflId": "breachRusherId"})
    agg = pf.groupby("playId").agg(minDistance=("dist", "min"), framesTracked=("frameId", "count"))
    agg["framesInside"] = inside.groupby("playId").size()

    out = win.join(agg, how="inner").join(breach)
    out["framesInside"] = out["framesInside"].fillna(0).astype(int)
    out["timeToEnd"] = (out.endFrame - out.snapFrame) * FRAME_SEC
    out["collapsed"] = out.breachFrame.notna()
    out["cleanPocketSeconds"] = np.where(
        out.collapsed, (out.breachFrame - out.snapFrame) * FRAME_SEC, out.timeToEnd)
    out["timeInsideRadius"] = out.framesInside * FRAME_SEC
    out["gameId"] = game_id
    return out.reset_index()


def compute_all(pff: pd.DataFrame, plays: pd.DataFrame) -> pd.DataFrame:
    roles = pff[["gameId", "playId", "nflId", "pff_role"]]
    tasks = [(int(g), grp.drop(columns="gameId")) for g, grp in roles.groupby("gameId")]
    workers = max(1, min(8, (os.cpu_count() or 2) - 1))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        parts = list(ex.map(compute_game, tasks))
    m = pd.concat(parts, ignore_index=True)

    # Cruce con PFF: presión acreditada a defensores y bloqueadores vencidos.
    p = pff.fillna({"pff_hurry": 0, "pff_hit": 0, "pff_sack": 0, "pff_beatenByDefender": 0})
    pfa = p.groupby(["gameId", "playId"]).agg(
        pffHurries=("pff_hurry", "sum"), pffHits=("pff_hit", "sum"),
        pffSacks=("pff_sack", "sum"), pffBeaten=("pff_beatenByDefender", "sum"),
        rushers=("pff_role", lambda r: int((r == "Pass Rush").sum())),
        blockers=("pff_role", lambda r: int((r == "Pass Block").sum())),
    ).reset_index()
    m = m.merge(pfa, on=["gameId", "playId"], how="left")
    for c in ["pffHurries", "pffHits", "pffSacks", "pffBeaten"]:
        m[c] = m[c].fillna(0).astype(int)
    m["pffPressure"] = (m.pffHurries + m.pffHits + m.pffSacks) > 0

    # Pocket Collapse Score (0-100): 60% tiempo bajo amenaza + 40% intensidad PFF.
    t = m.timeToEnd.where(m.timeToEnd > 0, np.nan)
    inside_share = (m.timeInsideRadius / t).clip(0, 1).fillna(0)
    intensity = ((m.pffHurries + 1.5 * m.pffHits + 2 * m.pffSacks) / 2).clip(0, 1)
    m["pocketCollapseScore"] = (60 * inside_share + 40 * intensity).round(1)

    cols = ["gameId", "playId", "possessionTeam", "defensiveTeam", "passResult", "pff_playAction",
            "playDescription", "quarter", "down", "yardsToGo", "pff_passCoverage", "dropBackType",
            "offenseFormation", "playResult"]
    m = m.merge(plays[cols], on=["gameId", "playId"], how="left")
    return m


def get_metrics(pff: pd.DataFrame, plays: pd.DataFrame) -> pd.DataFrame:
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "rb") as fh:
            return pickle.load(fh)
    m = compute_all(pff, plays)
    CACHE_DIR.mkdir(exist_ok=True)
    with open(CACHE_FILE, "wb") as fh:
        pickle.dump(m, fh)
    return m


# ---------------------------------------------------------------- Kaplan-Meier
KM_T_MAX = 4.5
FORMATIONS = ["SHOTGUN", "SINGLEBACK", "EMPTY", "I_FORM", "PISTOL"]


def kaplan_meier(durations, events, t_max: float = KM_T_MAX) -> dict:
    """Estimador de Kaplan-Meier S(t) en una malla de 0.1 s.

    durations: segundos hasta el colapso (evento) o hasta el pase/sack sin colapso (censura).
    events: True si la bolsa colapsó. Las jugadas censuradas en t siguen en riesgo en t
    (convención estándar: los eventos en t ocurren antes que las censuras en t).
    """
    k = np.rint(np.asarray(durations, dtype=float) / FRAME_SEC).astype(int)
    e = np.asarray(events, dtype=bool)
    n_steps = int(round(t_max / FRAME_SEC))
    size = max(int(k.max()) if len(k) else 0, n_steps) + 1
    deaths = np.bincount(k[e], minlength=size)
    at_risk = np.bincount(k, minlength=size)[::-1].cumsum()[::-1]  # duración >= t
    hazard = np.divide(deaths, at_risk, out=np.zeros(size), where=at_risk > 0)
    surv = np.cumprod(1.0 - hazard)
    below = np.nonzero(surv <= 0.5)[0]
    return {
        "n": int(len(k)),
        "events": int(e.sum()),
        "medianSeconds": round(below[0] * FRAME_SEC, 1) if len(below) else None,
        "t": [round(i * FRAME_SEC, 1) for i in range(n_steps + 1)],
        "survival": [float(s) for s in surv[: n_steps + 1]],
        "atRisk": [int(a) for a in at_risk[: n_steps + 1]],
    }


def survival_curves(m: pd.DataFrame) -> dict:
    """Curvas S(t) de bolsa limpia por Play-Action y por formación ofensiva."""
    def series(groups: list[tuple[str, pd.DataFrame]]) -> dict:
        fits = [(label, kaplan_meier(g.cleanPocketSeconds, g.collapsed)) for label, g in groups if len(g)]
        grid = fits[0][1]["t"] if fits else []
        data = [{"t": t, **{label: round(f["survival"][i], 4) for label, f in fits}} for i, t in enumerate(grid)]
        meta = [{"label": label, "n": f["n"], "events": f["events"], "censored": f["n"] - f["events"],
                 "medianSeconds": f["medianSeconds"],
                 "survivalAt2_5": round(f["survival"][grid.index(2.5)], 4)} for label, f in fits]
        return {"series": meta, "data": data}

    return {
        "tMax": KM_T_MAX,
        "step": FRAME_SEC,
        "threshold": 2.5,
        "overall": series([("Todas", m)]),
        "playAction": series([("Sin Play-Action", m[m.pff_playAction == 0]),
                              ("Play-Action", m[m.pff_playAction == 1])]),
        "formation": series([(f, m[m.offenseFormation == f]) for f in FORMATIONS]),
    }


if __name__ == "__main__":
    import time

    t0 = time.time()
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
    _, plays_df, _, pff_df = load_base()
    res = get_metrics(pff_df, plays_df)
    print(f"{len(res)} jugadas procesadas en {time.time() - t0:.1f} s -> {CACHE_FILE}")
    print(res[["cleanPocketSeconds", "timeToEnd", "pocketCollapseScore", "minDistance"]].describe().round(2))
    print("colapso:", round(res.collapsed.mean(), 3), "| presion PFF:", round(res.pffPressure.mean(), 3))
    print(res.endEvent.value_counts())
