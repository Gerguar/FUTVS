"""
Calcula ratings agregados por equipo a partir de `jugadores.rating` en Supabase.

Produce data/team_ratings.json con esta forma:

    {
      "real_madrid": {
        "attack_score":  85.3,   # ofensiva (top mediocampistas atacantes + top delanteros)
        "defense_score": 83.1,   # defensiva (top GK + top defensores + top mids defensivos)
        "top_xi_avg":    84.2,   # promedio del top 14 (XI titular + sustitutos clave)
        "n_players":     32
      },
      ...
    }

Los ratings son los OVR de EA FC 26 que ya cargamos via `player_ratings.py`.

Heuristicas:
- defense_score: peso 1*top_GK + 4*top_4_DEF + 3*top_3_MID_defensivos
  (asumimos que los MID con rating menor son mas defensivos; tomamos los 3 mas bajos del top 6 de MED)
- attack_score:  peso 3*top_3_MID_atacantes + 4*top_4_DEL
- top_xi_avg:    promedio de los 14 con mayor rating sin importar posicion

Estas heuristicas son simples pero capturan la idea de "calidad del XI" mejor que
un promedio global, sin requerir lineups confirmadas.
"""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .config import PATHS
from .team_normalize import canonical
from .supabase_writer import sb_get


TEAM_RATINGS_PATH = PATHS.matches.parent / "team_ratings.json"
VALID_POSITIONS = ("POR", "DEF", "MED", "DEL")


def _mean(xs: Iterable[float]) -> float | None:
    xs = list(xs)
    if not xs:
        return None
    return sum(xs) / len(xs)


def _paged_get(path: str, page: int = 1000) -> list[dict]:
    out: list[dict] = []
    sep = "&" if "?" in path else "?"
    offset = 0
    while True:
        chunk = sb_get(f"{path}{sep}limit={page}&offset={offset}")
        out.extend(chunk)
        if len(chunk) < page:
            return out
        offset += page


def compute_team_ratings() -> dict[str, dict]:
    """Lee equipos y jugadores de Supabase y devuelve dict slug -> ratings agregados."""
    # 1) equipos: id -> slug (canonical(nombre))
    equipos = _paged_get("equipos?select=id,nombre")
    id_to_slug = {int(e["id"]): canonical(e["nombre"]) for e in equipos}
    print(f"[team-ratings] equipos en Supabase: {len(id_to_slug)}")

    # 2) jugadores con rating (excluye nulos)
    jugadores = _paged_get(
        "jugadores?select=equipo_id,posicion,rating&rating=not.is.null"
    )
    print(f"[team-ratings] jugadores con rating: {len(jugadores)}")

    # 3) Agrupamos por equipo y posicion
    by_team: dict[int, dict[str, list[int]]] = defaultdict(
        lambda: {pos: [] for pos in VALID_POSITIONS}
    )
    for j in jugadores:
        eid = int(j["equipo_id"]) if j.get("equipo_id") else None
        if eid is None:
            continue
        pos = (j.get("posicion") or "MED").upper()
        if pos not in VALID_POSITIONS:
            pos = "MED"
        rating = j.get("rating")
        if rating is None:
            continue
        by_team[eid][pos].append(int(rating))

    # 4) Computamos agregados por equipo
    result: dict[str, dict] = {}
    for eid, by_pos in by_team.items():
        slug = id_to_slug.get(eid)
        if not slug:
            continue

        gks = sorted(by_pos["POR"], reverse=True)
        defs = sorted(by_pos["DEF"], reverse=True)
        mids = sorted(by_pos["MED"], reverse=True)
        fwds = sorted(by_pos["DEL"], reverse=True)

        # Top de cada posicion
        top_gk = gks[0] if gks else None
        top4_def = _mean(defs[:4])
        top4_fwd = _mean(fwds[:4])

        # MED split: los 3 con mayor rating son los "atacantes", los 3 con menor del top 6 los "defensivos".
        mid_top6 = mids[:6]
        n_mid = len(mid_top6)
        if n_mid >= 6:
            att_mids = mid_top6[:3]
            def_mids = mid_top6[3:6]
        elif n_mid >= 3:
            half = n_mid // 2
            att_mids = mid_top6[:half + (n_mid % 2)]
            def_mids = mid_top6[half + (n_mid % 2):]
        else:
            att_mids = mid_top6
            def_mids = mid_top6
        top_att_mid = _mean(att_mids)
        top_def_mid = _mean(def_mids)

        # defense_score: pondera GK + DEF + MID defensivos
        components = []
        weights = []
        if top_gk is not None:
            components.append(top_gk); weights.append(1)
        if top4_def is not None:
            components.append(top4_def); weights.append(4)
        if top_def_mid is not None:
            components.append(top_def_mid); weights.append(3)
        defense_score = (
            sum(c * w for c, w in zip(components, weights)) / sum(weights)
            if components else None
        )

        # attack_score: pondera MID atacantes + DEL
        components = []
        weights = []
        if top_att_mid is not None:
            components.append(top_att_mid); weights.append(3)
        if top4_fwd is not None:
            components.append(top4_fwd); weights.append(4)
        attack_score = (
            sum(c * w for c, w in zip(components, weights)) / sum(weights)
            if components else None
        )

        # top_xi_avg: top 14 sin filtrar por posicion
        all_ratings = sorted(
            (r for plist in by_pos.values() for r in plist), reverse=True
        )
        top_xi_avg = _mean(all_ratings[:14])

        result[slug] = {
            "attack_score": round(attack_score, 2) if attack_score is not None else None,
            "defense_score": round(defense_score, 2) if defense_score is not None else None,
            "top_xi_avg": round(top_xi_avg, 2) if top_xi_avg is not None else None,
            "n_players": sum(len(p) for p in by_pos.values()),
        }
    return result


def save_team_ratings(data: dict, path: Path = TEAM_RATINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def load_team_ratings(path: Path = TEAM_RATINGS_PATH) -> dict[str, dict]:
    """Lee data/team_ratings.json. Devuelve {} si no existe (features default a NaN)."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print-top", type=int, default=10,
                    help="Cuantos equipos top mostrar al final")
    args = ap.parse_args()

    print("[team-ratings] consultando Supabase...")
    data = compute_team_ratings()
    print(f"[team-ratings] {len(data)} equipos calculados")
    save_team_ratings(data)
    print(f"[team-ratings] guardado en {TEAM_RATINGS_PATH}")

    top = sorted(
        data.items(),
        key=lambda kv: (kv[1].get("top_xi_avg") or 0),
        reverse=True,
    )[: args.print_top]
    print(f"\nTop {args.print_top} por XI avg:")
    print(f"  {'slug':<22}  {'XI':>5}  {'ATK':>5}  {'DEF':>5}  n")
    for slug, r in top:
        xi = r.get("top_xi_avg") or 0
        atk = r.get("attack_score") or 0
        dfn = r.get("defense_score") or 0
        n = r.get("n_players") or 0
        print(f"  {slug:<22}  {xi:>5.1f}  {atk:>5.1f}  {dfn:>5.1f}  {n}")


if __name__ == "__main__":
    main()
