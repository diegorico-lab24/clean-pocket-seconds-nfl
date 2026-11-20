#!/bin/sh
# Verifica datos y dependencias del proyecto. Uso: sh setup.sh [--check]
# Termina con "TODO OK" y codigo 0 solo si todas las revisiones pasan.

ROOT=$(cd "$(dirname "$0")" && pwd)
DATA="$ROOT/data"
ERRORS=0

ok()   { printf '[ OK ] %s\n' "$1"; }
fail() { printf '[FALTA] %s\n' "$1"; ERRORS=$((ERRORS + 1)); }

case "${1:-}" in
  ""|--check) ;;
  *) echo "Uso: sh setup.sh [--check]"; exit 2 ;;
esac

echo "== 1. Archivos CSV en data/ =="
for f in games.csv plays.csv players.csv pffScoutingData.csv; do
  if [ -s "$DATA/$f" ]; then ok "data/$f"; else fail "data/$f (no existe o esta vacio)"; fi
done

echo "== 2. Python =="
PY=""
for cand in python3 python py; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import sys; sys.exit(0)" >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done
if [ -n "$PY" ]; then ok "interprete: $PY ($($PY --version 2>&1))"; else fail "python (python3/python/py) no encontrado"; fi

echo "== 3. Librerias Python =="
if [ -n "$PY" ]; then
  for mod in fastapi uvicorn pandas boto3; do
    if "$PY" -c "import $mod" >/dev/null 2>&1; then ok "$mod"; else fail "$mod (pip install $mod)"; fi
  done
fi

echo "== 4. Node y npm =="
for tool in node npm; do
  if command -v "$tool" >/dev/null 2>&1; then ok "$tool ($($tool --version 2>&1 | head -n 1))"; else fail "$tool no instalado"; fi
done

echo "== 5. games.csv vs data/tracking/ =="
if [ -n "$PY" ] && "$PY" -c "import pandas" >/dev/null 2>&1 && [ -s "$DATA/games.csv" ]; then
  if DATA_DIR="$DATA" "$PY" - <<'PYEOF'
import os, sys
import pandas as pd

data = os.environ["DATA_DIR"]
games = pd.read_csv(os.path.join(data, "games.csv"))
if games.empty:
    print("[FALTA] games.csv esta vacio"); sys.exit(1)
if "gameId" not in games.columns:
    print("[FALTA] games.csv no tiene la columna gameId"); sys.exit(1)

ids = sorted(games["gameId"].astype(str).unique())
print(f"[ OK ] games.csv: {len(games)} filas, {len(ids)} gameId unicos")

tdir = os.path.join(data, "tracking")
present = {f[len("tracking_"):-len(".csv")] for f in os.listdir(tdir)
           if f.startswith("tracking_") and f.endswith(".csv")} if os.path.isdir(tdir) else set()

missing = [g for g in ids if g not in present]
extra = sorted(present - set(ids))
bad = []
for g in ids:
    if g in missing:
        continue
    path = os.path.join(tdir, f"tracking_{g}.csv")
    try:
        df = pd.read_csv(path, usecols=["gameId"])
        if df.empty:
            bad.append((g, "vacio"))
        elif set(df["gameId"].astype(str).unique()) != {g}:
            bad.append((g, "gameId interno no coincide"))
    except Exception as e:
        bad.append((g, f"ilegible: {type(e).__name__}: {e}"))

n_ok = len(ids) - len(missing) - len(bad)
print(f"[ OK ] tracking validos: {n_ok}/{len(ids)}")
for g in missing: print(f"[FALTA] tracking_{g}.csv")
for g, why in bad: print(f"[FALTA] tracking_{g}.csv corrupto ({why})")
for g in extra: print(f"[AVISO] tracking_{g}.csv no aparece en games.csv")
sys.exit(1 if (missing or bad) else 0)
PYEOF
  then :; else ERRORS=$((ERRORS + 1)); fi
else
  fail "no se pudo ejecutar la revision de games.csv (falta python, pandas o games.csv)"
fi

echo
if [ "$ERRORS" -eq 0 ]; then
  echo "TODO OK"
else
  echo "Revisiones fallidas: $ERRORS"
  exit 1
fi
