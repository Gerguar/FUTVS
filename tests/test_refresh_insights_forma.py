import json

import src.refresh_insights_forma as refresh


def test_refresh_forma_preserves_other_insight_sections(tmp_path, monkeypatch):
    path = tmp_path / "insights.json"
    path.write_text(
        json.dumps({
            "generated_at_utc": "2026-06-07T06:00:00+00:00",
            "alertas": [{"texto": "Se conserva"}],
            "forma_reciente": [],
        }),
        encoding="utf-8",
    )
    forma = [{"nombre": "Argentina", "forma": ["W"] * 5, "gf": 10, "gc": 1}]

    monkeypatch.setattr(refresh, "OUT_INSIGHTS", path)
    monkeypatch.setattr(refresh, "build_forma_reciente", lambda: forma)

    assert refresh.refresh_forma() == 1

    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["forma_reciente"] == forma
    assert result["alertas"] == [{"texto": "Se conserva"}]
    assert result["generated_at_utc"] == "2026-06-07T06:00:00+00:00"
