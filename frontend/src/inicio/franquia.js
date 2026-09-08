// Agrupamento do catálogo por franquia (Fase 5) — o catálogo
// (`paginas/Galeria.jsx`) mostra 1 card por franquia, não 1 por temporada.
//
// Chave de agrupamento: `Anime.serie_ancora` (um `anilist_id` da T1,
// compartilhado por todas as temporadas da franquia — ver
// `backend/models/anime.py`). Quando NULL (franquia não resolvida pelo walk de
// `relations` da AniList), cai no slug do título SEM o marcador de temporada,
// espelhando `core/temporada.py::separar_temporada` + `core/texto.py::slugificar`
// do backend. É só um fallback: `scripts/backfill_serie.py` preenche
// `serie_ancora` para o grosso do catálogo.

// Espelha o subconjunto de `_REGEX_MARCADOR_TEMPORADA` de `core/temporada.py`
// que importa para agrupar (marcador no FIM do título, fronteira de token por
// `\s+`). Errar aqui só junta/separa card de franquia — nunca afeta captura.
const REGEX_MARCADOR_TEMPORADA =
  /\s+(?:season\s+\d+|\d+(?:st|nd|rd|th)\s+season|\d+\s*ª\s*temporada|temporada\s+\d+|part\s+\d+|cour\s+\d+|(?:ii|iii|iv)|\(tv\)|\(\d{4}\))\s*$/i;

// Descasca marcadores empilhados do fim ("... Season 3 Part 2") em laço — um
// `.replace` só alcança o mais à direita. Devolve o título original se sobrar
// vazio (título que era só marcador).
function tituloSemMarcadores(titulo) {
  let atual = titulo;
  let anterior = null;
  while (atual !== anterior) {
    anterior = atual;
    atual = atual.replace(REGEX_MARCADOR_TEMPORADA, '').trimEnd();
  }
  return atual === '' ? titulo : atual;
}

// Equivalente de `core/texto.py::slugificar` (NFKD + descarte de diacríticos +
// `[^a-z0-9]+` -> `-`).
function slugificar(texto) {
  return texto
    .normalize('NFKD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

export function chaveDeFranquia(anime) {
  if (anime.serie_ancora != null) return `ancora:${anime.serie_ancora}`;
  return `slug:${slugificar(tituloSemMarcadores(anime.titulo))}`;
}

// Agrupa uma lista de `AnimeSaida` (`GET /api/animes`) em franquias. Cada item
// devolvido é o ANIME REPRESENTANTE do grupo (maior `numero_temporada`, `NULL`
// conta como 0) — com `id`/`capa_path`/`status_lancamento`/`proximo_ep_em` da
// última temporada (navegação e arte apontam pra ela) — mais campos agregados da
// franquia inteira:
//   - `titulo`: título da última temporada, sem o marcador ("X Season 3" -> "X")
//     quando o card cobre mais de uma temporada.
//   - `episodios_novos`: soma de todas as temporadas (o badge só olha "> 0").
//   - `tem_episodios`: `true` se QUALQUER temporada tem episódio (decide o card
//     de estreia inerte).
//   - `generos`: união dos gêneros de todas as temporadas (filtro por gênero).
//   - `statusDaFranquia`: todos os `status_lancamento` distintos (filtro por
//     status — bate se qualquer temporada bate).
//   - `titulosDaFranquia`: títulos crus de todas as temporadas (busca textual).
//   - `idsDaFranquia`: ids de todas as temporadas (remoção da franquia inteira).
//   - `contagemDeTemporadas`: quantas temporadas no grupo.
export function agruparEmFranquias(animes) {
  const grupos = new Map();
  for (const anime of animes) {
    const chave = chaveDeFranquia(anime);
    const grupo = grupos.get(chave);
    if (grupo) grupo.push(anime);
    else grupos.set(chave, [anime]);
  }
  return [...grupos.values()].map(montarFranquia);
}

function montarFranquia(temporadas) {
  const representante = temporadas.reduce((maior, atual) =>
    (atual.numero_temporada ?? 0) > (maior.numero_temporada ?? 0) ? atual : maior
  );
  const varias = temporadas.length > 1;
  return {
    ...representante,
    titulo: varias ? tituloSemMarcadores(representante.titulo) : representante.titulo,
    episodios_novos: temporadas.reduce((soma, t) => soma + (t.episodios_novos ?? 0), 0),
    tem_episodios: temporadas.some((t) => t.tem_episodios),
    generos: [...new Set(temporadas.flatMap((t) => t.generos ?? []))],
    statusDaFranquia: [...new Set(temporadas.map((t) => t.status_lancamento).filter(Boolean))],
    titulosDaFranquia: temporadas.map((t) => t.titulo),
    idsDaFranquia: temporadas.map((t) => t.id),
    contagemDeTemporadas: temporadas.length,
  };
}
