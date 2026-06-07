"""Actualiza solo la seccion forma_reciente sin llamar a Claude."""
from __future__ import annotations

import json

from .generate_insights import OUT_INSIGHTS, build_forma_reciente


def refresh_forma() -> int:
    if not OUT_INSIGHTS.exists():
        print(f"[forma-insights] no existe {OUT_INSIGHTS}")
        return 0

    insights = json.loads(OUT_INSIGHTS.read_text(encoding="utf-8"))
    forma = build_forma_reciente()
    insights["forma_reciente"] = forma
    OUT_INSIGHTS.write_text(
        json.dumps(insights, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[forma-insights] {len(forma)} selecciones actualizadas")
    return len(forma)


if __name__ == "__main__":
    refresh_forma()
