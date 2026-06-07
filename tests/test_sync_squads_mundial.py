from src.sync_squads_mundial import (
    INACTIVE_PREFIX,
    active_notes,
    diff_squad,
    inactive_notes,
    paged_sb_get,
    players_match,
)


def test_players_match_by_normalized_name_and_birth_date():
    assert players_match(
        {"name": "Cristian Romero", "dateOfBirth": "1998-04-27"},
        {"nombre": "Christian Romero", "fecha_nac": "1998-04-27"},
    )
    assert players_match(
        {"name": "José Giménez", "dateOfBirth": "1995-01-20"},
        {"nombre": "Jose Maria Gimenez", "fecha_nac": "1995-01-20"},
    )


def test_diff_detects_single_clear_replacement():
    remote = [
        {"name": "Manuel Neuer", "dateOfBirth": "1986-03-27"},
        {"name": "Assan Ouédraogo", "dateOfBirth": "2006-05-09"},
    ]
    local = [
        {"nombre": "Manuel Neuer", "fecha_nac": "1986-03-27"},
        {"nombre": "Lennart Karl", "fecha_nac": "2008-02-22"},
    ]

    additions, removals = diff_squad(remote, local)

    assert [player["name"] for player in additions] == ["Assan Ouédraogo"]
    assert [player["nombre"] for player in removals] == ["Lennart Karl"]


def test_inactive_notes_are_reversible():
    marked = inactive_notes("Lesion confirmada", "Bayern Munich")

    assert marked.startswith(INACTIVE_PREFIX)
    assert active_notes(marked) == "Bayern Munich"


def test_paged_sb_get_does_not_drop_rows_after_first_page(monkeypatch):
    pages = {
        0: [{"id": index} for index in range(100)],
        100: [{"id": 189, "nombre": "Sudáfrica"}],
    }

    def fake_sb_get(path):
        offset = int(path.split("offset=")[1])
        return pages[offset]

    monkeypatch.setattr("src.sync_squads_mundial.sb_get", fake_sb_get)

    rows = paged_sb_get("equipos?select=id,nombre", page_size=100)

    assert len(rows) == 101
    assert rows[-1] == {"id": 189, "nombre": "Sudáfrica"}
