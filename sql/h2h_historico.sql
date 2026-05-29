-- Tabla de head-to-head histórico agregado para el comparador.
-- Una fila por par de equipos (orden canónico equipo_a_id < equipo_b_id).
-- victorias/goleadas/empates son acumulados de todos los enfrentamientos.
create table if not exists h2h_historico (
  id             bigint generated always as identity primary key,
  equipo_a_id    int not null references equipos(id) on delete cascade,
  equipo_b_id    int not null references equipos(id) on delete cascade,
  victorias_a    int not null default 0,
  victorias_b    int not null default 0,
  empates        int not null default 0,
  goleadas_a     int not null default 0,   -- victorias de A por 4+ goles
  goleadas_b     int not null default 0,   -- victorias de B por 4+ goles
  partidos       int not null default 0,
  fuente         text,                     -- 'couk' (clubes) | 'martj42' (selecciones)
  actualizado_at timestamptz default now(),
  unique (equipo_a_id, equipo_b_id)
);

-- El comparador lee con la anon key.
alter table h2h_historico disable row level security;
