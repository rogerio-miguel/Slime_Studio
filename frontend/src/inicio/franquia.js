// Agrupamento do catálogo por franquia (Fase 5) — o catálogo
// (`paginas/Galeria.jsx`) mostra 1 card por franquia, não 1 por temporada.
//
// Dois sinais unidos (union-find): duas temporadas são da mesma franquia se
// compartilham `Anime.serie_ancora` (walk de `relations` da AniList) OU o slug
// do título SEM o marcador de temporada. O segundo sinal existe porque o walk
// erra com OVA/ONA/split-cour no meio da cadeia (Fase 6): uma temporada fica com
// âncora, a irmã fica com `serie_ancora` NULL (ou outra âncora). Espelha
// `backend/core/franquia.py` + `_temporadas_irmas` de `api/rotas/animes.py`.

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

function slugDeFranquia(titulo) {
  return slugificar(tituloSemMarcadores(titulo));
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
  const pai = new Map();
  const acha = (no) => {
    if (!pai.has(no)) pai.set(no, no);
    while (pai.get(no) !== no) {
      pai.set(no, pai.get(pai.get(no)));
      no = pai.get(no);
    }
    return no;
  };
  const une = (a, b) => pai.set(acha(a), acha(b));

  for (const anime of animes) {
    const no = `id:${anime.id}`;
    acha(no);
    const slug = slugDeFranquia(anime.titulo);
    if (slug) une(no, `slug:${slug}`);
    if (anime.serie_ancora != null) une(no, `anc:${anime.serie_ancora}`);
  }

  const grupos = new Map();
  for (const anime of animes) {
    const raiz = acha(`id:${anime.id}`);
    const grupo = grupos.get(raiz);
    if (grupo) grupo.push(anime);
    else grupos.set(raiz, [anime]);
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
