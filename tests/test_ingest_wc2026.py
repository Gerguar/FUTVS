from src.ingest_wc2026 import find_existing_match


def _row(pid: int, fecha: str, home: int = 111, away: int = 112) -> dict:
    return {
        "id": pid,
        "fecha": fecha,
        "equipo_local_id": home,
        "equipo_visitante_id": away,
    }


def test_matches_same_fixture_when_kickoff_changes():
    existing = [_row(74, "2026-06-11T19:00:00Z")]

    match = find_existing_match(
        existing,
        home_id=111,
        away_id=112,
        fecha_iso="2026-06-11T22:00:00Z",
    )

    assert match["id"] == 74


def test_does_not_match_same_teams_weeks_later():
    existing = [_row(74, "2026-06-11T19:00:00Z")]

    match = find_existing_match(
        existing,
        home_id=111,
        away_id=112,
        fecha_iso="2026-07-05T19:00:00Z",
    )

    assert match is None


def test_chooses_nearest_fixture_and_respects_claimed_ids():
    existing = [
        _row(74, "2026-06-11T19:00:00Z"),
        _row(75, "2026-06-14T19:00:00Z"),
    ]

    nearest = find_existing_match(
        existing,
        home_id=111,
        away_id=112,
        fecha_iso="2026-06-14T18:00:00Z",
    )
    fallback = find_existing_match(
        existing,
        home_id=111,
        away_id=112,
        fecha_iso="2026-06-14T18:00:00Z",
        claimed_ids={75},
    )

    assert nearest["id"] == 75
    assert fallback["id"] == 74
