"""
Bot de Twitter / X para FutVersus. MVP.

Modos (--mode):
  prematch   Pronostico ~4h antes del kickoff. Throttle: >=30 min entre tweets de este tipo.
  postmortem Resultado vs prediccion para partidos finalizados. Throttle: 1 por run (=15 min).
             Reglas:
               - acertado  -> postear siempre
               - ajustado  -> postear siempre
               - no_acertado -> postear 1 de cada 2 (estado contador)
  lesiones   Alerta cuando aparece un equipo nuevo en wc2026_ajustes_lesiones.json
             que no posteamos antes.
  all        Corre los 3 modos en orden (lesiones primero, luego post, luego pre).

Modos auxiliares:
  --dry-run  No postea, solo imprime los tweets generados.
  --since-minutes N   Reescribe el "ahora" como N min en el futuro (testing).

Estado persistente: data/twitter_state.json
  {
    "last_prematch_at": "2026-06-11T18:30:00Z",
    "prematch_posted": {"74": "1837456784...", ...},     # partido_id -> tweet_id
    "postmortem_posted": {"74": {"tweet_id": "...", "klass": "acertado"}, ...},
    "postmortem_miss_counter": 3,                         # contador para "1 de cada 2 no_acertados"
    "lesion_snapshot": [{"jugador": "Lamine Yamal", "equipo_id": 124, "severidad": "danger"}, ...],
    "lesion_posted_keys": ["124|Lamine Yamal", ...]
  }

Variables de entorno necesarias para postear:
  TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET
  SUPABASE_URL, SUPABASE_SERVICE_KEY (heredado de supabase_writer)
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import urllib.parse

from . import twitter_templates as tt
from .supabase_writer import sb_get


STATE_PATH = Path("data/twitter_state.json")
LESIONES_AJUSTES_PATH = Path("data/wc2026_ajustes_lesiones.json")
INSIGHTS_PATH = Path("web/data/insights.json")

# Cooldown para lesiones nuevas: deben aparecer en el JSON de ajustes durante
# >=N horas antes de postearse. Esto evita postear ruido transitorio (una
# alerta puntual que despues se vetea o desaparece del proximo insights).
# Como el workflow `mundial` corre cada 6h y regenera ajustes_lesiones,
# 6h = una segunda confirmacion del modelo + tiempo para veto manual.
LESION_COOLDOWN_HOURS = 6.0

# Ventana de pre-match: postea entre 0.5h y 8h antes del kickoff.
# Originalmente apuntabamos a "4h antes ideal", pero GitHub Actions throttle los
# crons de */15 (a veces demoran 1-4h). Con ventana de 8h tenemos margen para
# que aunque el cron se demore, el tweet salga antes del kickoff.
# Regla original de Facu: "mejor antes que despues, nunca despues del kickoff".
PREMATCH_TARGET_H = 8.0     # ventana superior: hasta 8h antes
PREMATCH_MIN_BEFORE_H = 0.5  # corte 30 min antes minimo

# Throttle entre tweets pre-match (para no saturar cuando hay varios partidos simultaneos)
PREMATCH_THROTTLE_MIN = 30

# Liga 7 = Selecciones (Mundial). Mientras dura el Mundial, solo cubrimos esto.
LIGA_MUNDIAL = 7

# Fecha de fin del Mundial. Despues de esto, el bot deberia cambiar a clubes.
# (Se puede ajustar; por ahora hardcoded a la fecha tope esperada del Mundial 2026.)
MUNDIAL_END = "2026-07-20"


# ─────────────────────────────────────────────────────────────
# Estado
# ─────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"[bot] WARN: {STATE_PATH} corrupto, arranco de cero")
    return {
        "last_prematch_at": None,
        "prematch_posted": {},
        "postmortem_posted": {},
        "postmortem_miss_counter": 0,
        "lesion_snapshot": [],
        "lesion_posted_keys": [],
        # COOLDOWN: lesiones detectadas pero aun no posteadas.
        # {"eq_id|jugador": {"first_seen_at": iso, "delta_pp": float}}
        # Una lesion no se postea hasta que pase LESION_COOLDOWN_HOURS desde
        # first_seen_at Y siga apareciendo en wc2026_ajustes_lesiones.json.
        # Si dentro del cooldown se va del JSON, se cancela sin postear.
        "lesion_pending": {},
    }


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                          encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# Cliente Twitter (tweepy)
# ─────────────────────────────────────────────────────────────

def get_twitter_client():
    """Devuelve un cliente tweepy.Client (API v2) usando user-context auth.
    Lanza excepcion si faltan keys."""
    import tweepy  # import diferido: tests/dry-run no requieren tweepy instalado
    keys = {
        "consumer_key":        os.getenv("TWITTER_API_KEY"),
        "consumer_secret":     os.getenv("TWITTER_API_SECRET"),
        "access_token":        os.getenv("TWITTER_ACCESS_TOKEN"),
        "access_token_secret": os.getenv("TWITTER_ACCESS_SECRET"),
    }
    missing = [k for k, v in keys.items() if not v]
    if missing:
        raise RuntimeError(f"Faltan env vars de Twitter: {missing}")
    return tweepy.Client(**keys)


def post_tweet(text: str, dry_run: bool = False) -> Optional[str]:
    """Postea el texto. En dry_run lo imprime y devuelve un id ficticio."""
    text = tt.truncate_safe(text)
    print(f"\n┌─── TWEET ({len(text)} chars) ───")
    for line in text.splitlines():
        print(f"│ {line}")
    print("└─────────────")
    if dry_run:
        return f"dryrun-{int(datetime.now(timezone.utc).timestamp())}"
    client = get_twitter_client()
    resp = client.create_tweet(text=text)
    tweet_id = str(resp.data["id"])
    print(f"[bot] OK posted id={tweet_id}")
    return tweet_id


# ─────────────────────────────────────────────────────────────
# Helpers comunes
# ─────────────────────────────────────────────────────────────

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_to_dt(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def equipos_index() -> dict[int, str]:
    """id -> nombre, solo Mundial (liga 7) por ahora."""
    rows = sb_get(f"equipos?select=id,nombre&liga_id=eq.{LIGA_MUNDIAL}")
    return {int(r["id"]): r["nombre"] for r in rows}


# ─────────────────────────────────────────────────────────────
# Modo: PREMATCH
# ─────────────────────────────────────────────────────────────

def run_prematch(state: dict, dry_run: bool, now: datetime) -> int:
    """Postea como mucho 1 tweet de pre-match.
    Selecciona el partido con kickoff mas cercano dentro de la ventana ideal
    [now+0.5h, now+4h]. Si hay varios elegibles, postea el mas cercano y deja
    los otros para los siguientes runs (espaciado natural >=30 min).
    """
    # Throttle: si el ultimo prematch fue hace <30 min, salir.
    last_at = state.get("last_prematch_at")
    if last_at:
        delta_min = (now - iso_to_dt(last_at)).total_seconds() / 60
        if delta_min < PREMATCH_THROTTLE_MIN:
            print(f"[prematch] skip: ultimo tweet hace {delta_min:.1f}min "
                  f"(<{PREMATCH_THROTTLE_MIN}min)")
            return 0

    eq = equipos_index()
    # Pronosticos + partido en un solo round-trip via embed.
    # PostgREST exige URL-encode en datetimes (el '+' de timezone rompe el parser).
    lo = urllib.parse.quote(now.isoformat())
    hi = urllib.parse.quote((now + timedelta(hours=PREMATCH_TARGET_H)).isoformat())
    rows = sb_get(
        "partidos?select=id,fecha,equipo_local_id,equipo_visitante_id,"
        "pronosticos(prob_local,prob_empate,prob_visitante)"
        f"&estado=eq.programado&liga_id=eq.{LIGA_MUNDIAL}"
        f"&fecha=lte.{hi}"
        f"&fecha=gte.{lo}"
        "&order=fecha"
    )
    if not rows:
        print("[prematch] no hay partidos en ventana [now, now+5h]")
        return 0

    posted: dict = state.setdefault("prematch_posted", {})

    candidates = []
    for r in rows:
        pid = int(r["id"])
        if str(pid) in posted:
            continue
        pr = r.get("pronosticos")
        if isinstance(pr, list):
            pr = pr[0] if pr else None
        if not pr:
            continue
        kickoff = iso_to_dt(r["fecha"])
        delta_h = (kickoff - now).total_seconds() / 3600
        if delta_h < PREMATCH_MIN_BEFORE_H:
            # Demasiado pegado al kickoff (o pasado), saltear
            continue
        candidates.append((kickoff, pid, r, pr, delta_h))

    if not candidates:
        print(f"[prematch] {len(rows)} partidos en ventana, ninguno postable "
              "(ya posteado o sin pronostico)")
        return 0

    # Postear el mas cercano al kickoff (kickoff mas temprano).
    candidates.sort(key=lambda x: x[0])
    kickoff, pid, r, pr, delta_h = candidates[0]
    h_name = eq.get(int(r["equipo_local_id"]), f"#{r['equipo_local_id']}")
    a_name = eq.get(int(r["equipo_visitante_id"]), f"#{r['equipo_visitante_id']}")

    text = tt.tweet_prematch(
        home_name=h_name, away_name=a_name,
        prob_local=float(pr["prob_local"] or 0),
        prob_empate=float(pr["prob_empate"] or 0),
        prob_visitante=float(pr["prob_visitante"] or 0),
        kickoff_iso_utc=r["fecha"], partido_id=pid,
    )
    print(f"[prematch] partido_id={pid} {h_name} vs {a_name} "
          f"(kickoff en {delta_h:.1f}h, +{len(candidates)-1} en cola)")
    tweet_id = post_tweet(text, dry_run=dry_run)
    if tweet_id:
        posted[str(pid)] = tweet_id
        state["last_prematch_at"] = now.isoformat()
    return 1


# ─────────────────────────────────────────────────────────────
# Modo: POSTMORTEM
# ─────────────────────────────────────────────────────────────

def run_postmortem(state: dict, dry_run: bool, now: datetime) -> int:
    """Postea como mucho 1 tweet de post-mortem por run (=cada 15 min).
    Reglas:
      - acertado/ajustado: postear siempre
      - no_acertado: postear 1 de cada 2 (contador en state)
    Toma el partido finalizado mas antiguo aun no posteado.
    """
    eq = equipos_index()
    rows = sb_get(
        "partidos?select=id,fecha,equipo_local_id,equipo_visitante_id,"
        "goles_local,goles_visitante,"
        "pronosticos(prob_local,prob_empate,prob_visitante)"
        f"&estado=eq.finalizado&liga_id=eq.{LIGA_MUNDIAL}"
        "&goles_local=not.is.null&goles_visitante=not.is.null"
        "&order=fecha.asc"
    )
    posted: dict = state.setdefault("postmortem_posted", {})

    # Ordenamos por fecha asc -> el mas viejo no posteado va primero
    for r in rows:
        pid = int(r["id"])
        if str(pid) in posted:
            continue
        pr = r.get("pronosticos")
        if isinstance(pr, list):
            pr = pr[0] if pr else None
        if not pr:
            continue

        pH = float(pr.get("prob_local") or 0)
        pD = float(pr.get("prob_empate") or 0)
        pA = float(pr.get("prob_visitante") or 0)
        gL = int(r["goles_local"])
        gV = int(r["goles_visitante"])
        klass = tt.classify_result(pH, pD, pA, gL, gV)

        # Filtro "1 de cada 2 no_acertados"
        if klass == "no_acertado":
            cnt = int(state.get("postmortem_miss_counter", 0))
            state["postmortem_miss_counter"] = cnt + 1
            # cnt % 2 == 0 -> primero, postear; cnt % 2 == 1 -> saltear
            if cnt % 2 == 1:
                # Lo marcamos posteado igual (no queremos verlo de nuevo en futuros runs)
                posted[str(pid)] = {"tweet_id": None, "klass": klass, "skipped": True}
                print(f"[postmortem] skip no_acertado partido_id={pid} (contador={cnt})")
                continue

        h_name = eq.get(int(r["equipo_local_id"]), f"#{r['equipo_local_id']}")
        a_name = eq.get(int(r["equipo_visitante_id"]), f"#{r['equipo_visitante_id']}")
        text = tt.tweet_postmortem(
            home_name=h_name, away_name=a_name,
            prob_local=pH, prob_empate=pD, prob_visitante=pA,
            goles_local=gL, goles_visitante=gV, partido_id=pid,
        )
        print(f"[postmortem] partido_id={pid} {h_name} {gL}-{gV} {a_name} [{klass}]")
        tweet_id = post_tweet(text, dry_run=dry_run)
        posted[str(pid)] = {"tweet_id": tweet_id, "klass": klass}
        return 1  # solo 1 por run

    print("[postmortem] nada nuevo para postear")
    return 0


# ─────────────────────────────────────────────────────────────
# Modo: LESIONES
# ─────────────────────────────────────────────────────────────

def run_lesiones(state: dict, dry_run: bool, now: datetime) -> int:
    """Postea lesiones del JSON wc2026_ajustes_lesiones.json con COOLDOWN.

    Flujo:
    1. Parseamos el JSON actual y construimos `current_set` con todas las
       lesiones detectadas en este run.
    2. Limpiamos `lesion_pending`: si una lesion pendiente YA NO esta en
       current_set, se cancela (era ruido transitorio).
    3. Para cada lesion en current_set:
       a. Si ya esta en `lesion_posted_keys`: nada que hacer.
       b. Si esta en `lesion_pending` y paso el cooldown: candidata a postear.
       c. Si esta en `lesion_pending` pero NO paso el cooldown: esperar.
       d. Si NO esta en pending ni en posted: agregar a pending.
    4. Postear maximo 1 candidata por run.
    """
    if not LESIONES_AJUSTES_PATH.exists():
        print("[lesiones] no existe data/wc2026_ajustes_lesiones.json")
        return 0
    aj = json.loads(LESIONES_AJUSTES_PATH.read_text(encoding="utf-8"))

    eq = equipos_index()
    posted_keys = set(state.get("lesion_posted_keys", []))
    pending: dict = state.setdefault("lesion_pending", {})
    new_count = 0

    # ── Paso 1: construir current_set desde el JSON ─────────
    seen_team_player: set[tuple[int, str]] = set()
    # current[key] = (eq_id, jugador, total_pp, eq_name)
    current: dict[str, tuple[int, str, float, str]] = {}
    for pid, ent in (aj or {}).items():
        for reason in ent.get("reasons", []):
            # Buscar equipo en texto: el primer token suele ser el nombre.
            eq_id = None
            for tid, tname in eq.items():
                if reason.startswith(tname + " sin "):
                    eq_id = tid
                    break
            if eq_id is None:
                continue
            try:
                jugadores_part = reason.split(" sin ", 1)[1]
                jugadores_str = jugadores_part.rsplit(" (-", 1)[0]
                pp_str = jugadores_part.rsplit(" (-", 1)[1].rstrip("pp)")
                total_pp = float(pp_str)
            except (IndexError, ValueError):
                continue
            for j in [x.strip() for x in jugadores_str.split(",")]:
                key = f"{eq_id}|{j}"
                if (eq_id, j) in seen_team_player:
                    continue
                seen_team_player.add((eq_id, j))
                current[key] = (eq_id, j, total_pp, eq.get(eq_id, "?"))

    # ── Paso 2: limpiar pending de items que ya no estan en el JSON ─────
    cancelled = []
    for key in list(pending.keys()):
        if key not in current:
            cancelled.append(key)
            del pending[key]
    if cancelled:
        print(f"[lesiones] CANCELADAS (ya no en JSON): {cancelled}")

    # ── Paso 3: clasificar items entre nuevos / esperando / listos ─────
    listas: list[tuple[int, str, float, str]] = []
    nuevas: list[str] = []
    esperando: list[str] = []
    for key, item in current.items():
        if key in posted_keys:
            continue
        if key in pending:
            first_seen = iso_to_dt(pending[key]["first_seen_at"])
            edad_h = (now - first_seen).total_seconds() / 3600
            if edad_h >= LESION_COOLDOWN_HOURS:
                listas.append(item)
            else:
                esperando.append(f"{item[3]}/{item[1]} ({edad_h:.1f}h)")
        else:
            # Lesion nueva: agregar a pending con timestamp ahora.
            pending[key] = {
                "first_seen_at": now.isoformat(),
                "delta_pp": item[2],
            }
            nuevas.append(f"{item[3]}/{item[1]}")

    if nuevas:
        print(f"[lesiones] NUEVAS (esperando cooldown {LESION_COOLDOWN_HOURS:.0f}h): {nuevas}")
    if esperando:
        print(f"[lesiones] EN COOLDOWN: {esperando}")

    if not listas:
        if not current:
            print("[lesiones] sin ajustes activos")
        else:
            print(f"[lesiones] ninguna paso el cooldown todavia (total en JSON: {len(current)})")
        return 0

    # ── Paso 4: postear 1 por run (la primera lista por orden de aparicion) ─
    eq_id, jugador, total_pp, eq_name = listas[0]
    sev = "danger" if total_pp >= 3.0 else "warning"
    text = tt.tweet_lesion(
        jugador=jugador, equipo_name=eq_name,
        severidad=sev, delta_pp=total_pp,
    )
    print(f"[lesiones] {eq_name} <- {jugador} ({sev}, -{total_pp:.1f}pp) "
          f"[+{len(listas)-1} en cola, cooldown OK]")
    tweet_id = post_tweet(text, dry_run=dry_run)
    if tweet_id:
        posted_keys.add(f"{eq_id}|{jugador}")
        # Sacar de pending (ya posteada)
        pending.pop(f"{eq_id}|{jugador}", None)
        new_count += 1
        state["lesion_posted_keys"] = sorted(posted_keys)

    if dry_run and len(listas) > 1:
        print(f"\n[lesiones] (dry-run) {len(listas)-1} mas se postearian en runs siguientes:")
        for it in listas[1:]:
            sev_q = "danger" if it[2] >= 3.0 else "warning"
            print(f"  - {it[3]} <- {it[1]} ({sev_q}, -{it[2]:.1f}pp)")

    return new_count


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["prematch", "postmortem", "lesiones", "all"],
                   default="all")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--reset-state", action="store_true",
                   help="Borra data/twitter_state.json antes de correr (cuidado)")
    p.add_argument("--at", default=None,
                   help="Override del 'ahora' (ISO UTC). Solo para testing local.")
    args = p.parse_args()

    if args.reset_state and STATE_PATH.exists():
        print(f"[bot] borrando {STATE_PATH}")
        STATE_PATH.unlink()

    state = load_state()
    now = iso_to_dt(args.at) if args.at else now_utc()
    print(f"[bot] mode={args.mode} dry_run={args.dry_run} now={now.isoformat()}")

    # Cortocircuito: si estamos despues del Mundial, no posteamos partidos de
    # seleccion. En esa fase habria que apuntar a clubes (no implementado en MVP).
    if now.date().isoformat() > MUNDIAL_END:
        print(f"[bot] WARN: Mundial terminado ({MUNDIAL_END}). MVP solo cubre Mundial.")

    total = 0
    if args.mode in ("lesiones", "all"):
        total += run_lesiones(state, args.dry_run, now)
    if args.mode in ("postmortem", "all"):
        total += run_postmortem(state, args.dry_run, now)
    if args.mode in ("prematch", "all"):
        total += run_prematch(state, args.dry_run, now)

    print(f"\n[bot] tweets posteados en este run: {total}")
    if not args.dry_run:
        save_state(state)


if __name__ == "__main__":
    main()
