# README del paquete de Handover

Este folder contiene todo lo necesario para que una nueva sesion de Claude
(o un colaborador nuevo) pueda agarrar el proyecto FutPronostico sin perderse.

## Archivos en orden de upload

1. **`01_HANDOVER.md`** — Documento narrativo principal. Visi[o]n general, decisiones,
   cuentas, schema, roadmap.
2. **`02_CODE_PYTHON.md`** — Codigo Python completo (18 modulos de `src/`).
3. **`03_CODE_WORKFLOWS.md`** — Workflows YAML, requirements, configs.
4. **`04_CODE_WEB.md`** — HTML del frontend (~93 KB).
5. **`05_DATA_SUPABASE.md`** — Schema de Supabase + queries de ejemplo.
6. **`06_DOCS.md`** — README + SUPABASE_SETUP del proyecto.

## Como usarlos

Abri nueva conversacion en Claude, subi los 6 archivos arriba (de a uno o en grupo
si tu cliente lo permite), y arranca con:

> Soy [usuario]. Te paso el contexto completo del proyecto FutPronostico via los
> archivos adjuntos. Empezamos desde aca. Mi pendiente inmediato es: ...

Claude va a tener todo el contexto.

## Tamanos aproximados

(Generados automaticamente por `generate_handover.py`)
