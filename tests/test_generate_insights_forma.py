import src.generate_insights as insights


def test_forma_goles_use_only_latest_five_matches(monkeypatch):
    matches = []
    scores = [(1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (9, 9)]
    for day, (gf, gc) in enumerate(scores, start=1):
        matches.append({
            "id": day,
            "fecha": f"2026-06-{day:02d}T12:00:00",
            "goles_local": gf,
            "goles_visitante": gc,
            "equipo_local_id": 1,
            "equipo_visitante_id": 99,
        })

    def fake_sb_get(path):
        if path.startswith("partidos?"):
            return matches
        return [{
            "id": 1,
            "nombre": "Argentina",
            "escudo_url": "argentina.png",
            "liga_id": 7,
        }]

    monkeypatch.setattr(insights, "sb_get", fake_sb_get)

    result = insights.build_forma_reciente()

    argentina = result[0]
    assert argentina["forma"] == ["D", "W", "W", "W", "W"]
    assert argentina["gf"] == 23
    assert argentina["gc"] == 9
