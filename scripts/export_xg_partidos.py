"""
scripts/export_xg_partidos.py
Exporta a CSV los partidos del Mundial con probabilidades del modelo y xG
esperados parseados del campo `pronosticos.notas` (formato 'xG esperado: H-A').

Salida: data/exports/xg_partidos_mundial.csv (y .json para programatico).
"""
from __future__ import annotations
import csv
import json
import os
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "exports"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_CSV  = OUT_DIR / "xg_partidos_mundial.csv"
OUT_JSON = OUT_DIR / "xg_partidos_mundial.json"

SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_SERVICE_KEY"]


def sb_get(path: str) -> list[dict]:
    url = f"{SB_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, headers={
        "apikey": SB_KEY,
        "Authorization": f"Bearer {SB_KEY}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def parse_xg(notas: str) -> tuple[float | None, float | None]:
    """Parsea 'xG esperado: 1.69-0.35' del campo notas.

    Regex usa `\d+\.?\d*` (no `[\d.]+`) para no agarrar el punto final
    de la oracion siguiente. Devuelve floats o (None, None)."""
    if not notas:
        return None, None
    m = re.search(r"xG[^0-9]*(\d+\.?\d*)\s*-\s*(\d+\.?\d*)", notas, re.IGNORECASE)
    if not m:
        return None, None
    try:
        return float(m.group(1)), float(m.group(2))
    except ValueError:
        return None, None


def fmt_hour_ar(iso_utc: str) -> str:
    """ISO UTC -> 'HH:MM' en hora ART (UTC-3)."""
    s = iso_utc.replace("Z", "+00:00") if iso_utc.endswith("Z") else iso_utc
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ar = dt.astimezone(timezone(timedelta(hours=-3)))
    return ar.strftime("%H:%M")


def main() -> None:
    print("[xg-export] leyendo partidos del Mundial...", flush=True)
    rows = sb_get(
        "partidos?select=id,fecha,grupo,estado,"
        "equipo_local:equipo_local_id(nombre,abreviacion),"
        "equipo_visitante:equipo_visitante_id(nombre,abreviacion),"
        "pronosticos(prob_local,prob_empate,prob_visitante,notas,"
        "factor_localidad,factor_forma,factor_h2h,factor_tabla,factor_bajas,factor_goles)"
        "&liga_id=eq.7&estado=eq.programado&order=fecha&limit=200"
    )
    print(f"[xg-export] {len(rows)} partidos programados", flush=True)

    out_rows = []
    for r in rows:
        h = (r.get("equipo_local") or {}).get("nombre", "?")
        a = (r.get("equipo_visitante") or {}).get("nombre", "?")
        h_abbr = (r.get("equipo_local") or {}).get("abreviacion", "")
        a_abbr = (r.get("equipo_visitante") or {}).get("abreviacion", "")
        fecha = r.get("fecha", "")
        grupo = r.get("grupo", "") or ""

        pr = r.get("pronosticos")
        if isinstance(pr, list):
            pr = pr[0] if pr else None
        if not pr:
            continue

        pH = float(pr.get("prob_local") or 0)
        pD = float(pr.get("prob_empate") or 0)
        pA = float(pr.get("prob_visitante") or 0)
        xg_h, xg_a = parse_xg(pr.get("notas") or "")

        # Outcome predicho por el modelo (top-1)
        if pH >= pD and pH >= pA:
            top1 = "Local"
        elif pA >= pH and pA >= pD:
            top1 = "Visitante"
        else:
            top1 = "Empate"

        out_rows.append({
            "partido_id": r.get("id"),
            "fecha_utc": fecha,
            "fecha_ART": fecha[:10] if fecha else "",
            "hora_ART": fmt_hour_ar(fecha) if fecha else "",
            "grupo": grupo,
            "equipo_local": h,
            "abrev_local": h_abbr,
            "equipo_visitante": a,
            "abrev_visitante": a_abbr,
            "prob_local_pct":     round(pH, 1),
            "prob_empate_pct":    round(pD, 1),
            "prob_visitante_pct": round(pA, 1),
            "top1": top1,
            "xG_local":  xg_h if xg_h is not None else "",
            "xG_visitante": xg_a if xg_a is not None else "",
            "xG_total":  round((xg_h + xg_a), 2) if (xg_h is not None and xg_a is not None) else "",
            "factor_localidad": pr.get("factor_localidad"),
            "factor_forma":     pr.get("factor_forma"),
            "factor_h2h":       pr.get("factor_h2h"),
            "factor_tabla":     pr.get("factor_tabla"),
            "factor_bajas":     pr.get("factor_bajas"),
            "factor_goles":     pr.get("factor_goles"),
        })

    # CSV (UTF-8 con BOM para que Excel lo abra bien con acentos)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        if out_rows:
            writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
            writer.writeheader()
            writer.writerows(out_rows)
    print(f"[xg-export] CSV -> {OUT_CSV} ({len(out_rows)} filas)", flush=True)

    # JSON
    with OUT_JSON.open("w", encoding="utf-8") as f:
        json.dump({
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "total_partidos": len(out_rows),
            "fuente": "FutVersus model (Dixon-Coles + Elo + XGBoost + mercado)",
            "partidos": out_rows,
        }, f, indent=2, ensure_ascii=False)
    print(f"[xg-export] JSON -> {OUT_JSON}", flush=True)


if __name__ == "__main__":
    main()
