"""
Sincronización de partidos próximos con Supabase.

Flujo:
1. Lee matches.parquet (resultado del ingest).
2. Filtra partidos con status SCHEDULED/TIMED y kickoff en los próximos N días.
3. Para cada partido:
   a. Asegura que ambos equipos existan en `equipos` (los crea si faltan).
   b. Asegura que el partido exista en `partidos` (lo crea si falta).
4. Archiva los partidos antiguos: `estado=programado` con fecha > 7 días en el
   pasado → pasan a `estado=finalizado` (para que no aparezcan en la web).

El identificador estable que usamos para joinear con el modelo es el SLUG
canónico del equipo (definido en team_normalize.py). Cada equipo en Supabase
tiene un slug derivado de canonical(nombre).
"""
from __future__ import annotations
import argparse
import urllib.parse
from datetime import timedelta
import pandas as pd

from .config import PATHS
from .team_normalize import canonical
from .supabase_writer import (sb_get, sb_post, sb_patch,
                              LEAGUE_ALIAS, SUPABASE_TO_SLUG)


class SupabaseSync:
    """Cache de equipos + helpers para sync."""

    def __init__(self):
        self.slug_to_id: dict[str, int] = {}
        self.id_to_slug: dict[int, str] = {}
        self.equipos_sin_escudo: set[int] = set()  # ids con escudo_url=null
        self._load_existing_equipos()

    def _load_existing_equipos(self) -> None:
        rows = sb_get("equipos?select=id,nombre,escudo_url")
        for e in rows:
            slug = canonical(e["nombre"])
            eid = int(e["id"])
            self.slug_to_id[slug] = eid
            self.id_to_slug[eid] = slug
            if not e.get("escudo_url"):
                self.equipos_sin_escudo.add(eid)
        # Aseguramos los hardcodeados (por si el nombre en Supabase difiere mucho)
        for sid, slug in SUPABASE_TO_SLUG.items():
            self.slug_to_id.setdefault(slug, sid)
            self.id_to_slug.setdefault(sid, slug)
        print(f"[sync] cache de equipos: {len(self.slug_to_id)} entradas "
              f"({len(self.equipos_sin_escudo)} sin escudo)")

    def ensure_equipo(self, slug: str, fd_name: str, liga_id: int,
                      escudo_url: str | None,
                      dry_run: bool) -> int | None:
        if slug in self.slug_to_id:
            eid = self.slug_to_id[slug]
            # Si existe pero no tiene escudo y ahora tenemos uno, actualizar
            if eid in self.equipos_sin_escudo and escudo_url:
                if dry_run:
                    print(f"  [dry-run] update escudo equipo id={eid}: {escudo_url}")
                else:
                    try:
                        sb_patch(f"equipos?id=eq.{eid}", {"escudo_url": escudo_url})
                        self.equipos_sin_escudo.discard(eid)
                        print(f"  + escudo actualizado: {slug:25} id={eid}")
                    except Exception as e:
                        print(f"  ! error update escudo {slug}: {e}")
            return eid

        payload = {
            "nombre": fd_name,
            "abreviacion": slug.upper().replace("_", "")[:5],
            "liga_id": liga_id,
            "color_prim": "#1f2937",
            "color_sec": "#ffffff",
            "escudo_url": escudo_url,
        }
        if dry_run:
            print(f"  [dry-run] crear equipo: {slug} -> {payload}")
            return None
        try:
            res = sb_post("equipos", [payload], prefer="return=representation")
            new_id = int(res[0]["id"])
            self.slug_to_id[slug] = new_id
            self.id_to_slug[new_id] = slug
            print(f"  + equipo creado: {slug:25} -> id={new_id}  ({fd_name})"
                  f"  escudo={'si' if escudo_url else 'no'}")
            return new_id
        except Exception as e:
            print(f"  ! error creando equipo {slug}: {e}")
            return None

    def find_partido_id(self, home_id: int, away_id: int,
                        fecha_iso: str) -> int | None:
        fecha_dt = pd.to_datetime(fecha_iso, utc=True)
        lo = (fecha_dt - timedelta(hours=6)).isoformat()
        hi = (fecha_dt + timedelta(hours=6)).isoformat()
        q = urllib.parse.urlencode({
            "select": "id",
            "equipo_local_id": f"eq.{home_id}",
            "equipo_visitante_id": f"eq.{away_id}",
            "fecha": f"gte.{lo}",
        })
        rows = sb_get(f"partidos?{q}&fecha=lte.{urllib.parse.quote(hi)}")
        return int(rows[0]["id"]) if rows else None

    def upsert_partido(self, home_id: int, away_id: int, fecha_iso: str,
                       liga_id: int, temporada: str,
                       dry_run: bool) -> tuple[int | None, bool]:
        """Devuelve (partido_id, created_bool)."""
        existing = self.find_partido_id(home_id, away_id, fecha_iso)
        if existing:
            return existing, False
        payload = {
            "equipo_local_id": home_id,
            "equipo_visitante_id": away_id,
            "fecha": fecha_iso,
            "liga_id": liga_id,
            "temporada": temporada or "2025/26",
            "estado": "programado",
        }
        if dry_run:
            print(f"  [dry-run] crear partido: {home_id} vs {away_id} @ {fecha_iso[:16]}")
            return None, True
        try:
            res = sb_post("partidos", [payload], prefer="return=representation")
            new_id = int(res[0]["id"])
            return new_id, True
        except Exception as e:
            print(f"  ! error creando partido: {e}")
            return None, False

    def archive_past_partidos(self, dry_run: bool) -> int:
        """Marca como finalizado los partidos `programado` con fecha pasada."""
        cutoff = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=2)).isoformat()
        q = urllib.parse.urlencode({
            "select": "id,fecha",
            "estado": "eq.programado",
            "fecha": f"lt.{cutoff}",
        })
        rows = sb_get(f"partidos?{q}")
        if not rows:
            return 0
        ids = [r["id"] for r in rows]
        if dry_run:
            print(f"  [dry-run] archivar {len(ids)} partidos pasados: {ids}")
            return len(ids)
        ids_str = ",".join(str(i) for i in ids)
        sb_patch(f"partidos?id=in.({ids_str})", {"estado": "finalizado"})
        print(f"  + archivados {len(ids)} partidos pasados: {ids}")
        return len(ids)


def sync_upcoming(horizon_days: int = 14, dry_run: bool = False,
                  only_leagues: list[str] | None = None) -> dict:
    df = pd.read_parquet(PATHS.matches)
    df["kickoff_ts_utc"] = pd.to_datetime(df["kickoff_ts_utc"], utc=True)
    now = pd.Timestamp.now(tz="UTC")
    end = now + pd.Timedelta(days=horizon_days)

    valid_status = df["status"].isin(["SCHEDULED", "TIMED"])
    in_window = (df["kickoff_ts_utc"] >= now - pd.Timedelta(hours=2)) & \
                 (df["kickoff_ts_utc"] <= end)
    has_teams = df["home_team_id"].notna() & df["away_team_id"].notna()
    upcoming = df[valid_status & in_window & has_teams].copy()

    if only_leagues:
        upcoming = upcoming[upcoming["competition_code"].isin(only_leagues)]

    # Ordenar por fecha y eliminar duplicados de mismo partido entre fuentes
    upcoming = upcoming.sort_values("kickoff_ts_utc")
    upcoming = upcoming.drop_duplicates(
        subset=["home_team_id", "away_team_id"],
        keep="first"
    )

    print(f"[sync] {len(upcoming)} partidos proximos (status=SCHEDULED/TIMED) "
          f"en los proximos {horizon_days} dias")

    sync = SupabaseSync()
    stats = {"created_equipos": 0, "created_partidos": 0, "existing_partidos": 0,
             "skipped_no_liga": 0, "skipped_no_equipo": 0, "errors": 0}

    for _, m in upcoming.iterrows():
        liga_id = LEAGUE_ALIAS.get(m["competition_code"])
        if not liga_id:
            stats["skipped_no_liga"] += 1
            continue
        try:
            n_before = len(sync.slug_to_id)
            home_id = sync.ensure_equipo(
                slug=m["home_team_id"],
                fd_name=m.get("home_team_name") or m["home_team_id"],
                liga_id=liga_id,
                escudo_url=(m.get("home_team_crest") if isinstance(m.get("home_team_crest"), str) else None),
                dry_run=dry_run,
            )
            away_id = sync.ensure_equipo(
                slug=m["away_team_id"],
                fd_name=m.get("away_team_name") or m["away_team_id"],
                liga_id=liga_id,
                escudo_url=(m.get("away_team_crest") if isinstance(m.get("away_team_crest"), str) else None),
                dry_run=dry_run,
            )
            stats["created_equipos"] += len(sync.slug_to_id) - n_before
            if not home_id or not away_id:
                stats["skipped_no_equipo"] += 1
                continue
            pid, created = sync.upsert_partido(
                home_id=home_id, away_id=away_id,
                fecha_iso=m["kickoff_ts_utc"].isoformat(),
                liga_id=liga_id,
                temporada=m.get("season", ""),
                dry_run=dry_run,
            )
            if created:
                stats["created_partidos"] += 1
                print(f"  + partido: {m['home_team_name']} vs {m['away_team_name']} "
                      f"@ {m['kickoff_ts_utc'].strftime('%Y-%m-%d %H:%M')}  "
                      f"(liga={m['competition_code']})")
            else:
                stats["existing_partidos"] += 1
        except Exception as e:
            print(f"  ! error: {e}")
            stats["errors"] += 1

    stats["archived"] = sync.archive_past_partidos(dry_run)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=14,
                    help="Dias hacia adelante para sincronizar partidos proximos")
    ap.add_argument("--dry-run", action="store_true",
                    help="Imprime que haria sin tocar Supabase")
    ap.add_argument("--leagues", default=None,
                    help="CSV de competition_codes (default: todos)")
    args = ap.parse_args()

    leagues = [s.strip() for s in args.leagues.split(",")] if args.leagues else None
    print(f"[sync] modo: horizon={args.horizon} dry_run={args.dry_run} leagues={leagues}")
    stats = sync_upcoming(args.horizon, args.dry_run, leagues)
    print(f"[sync] resumen: {stats}")


if __name__ == "__main__":
    main()
