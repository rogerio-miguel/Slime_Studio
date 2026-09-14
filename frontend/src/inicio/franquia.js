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

// `tituloSemMarcadores` cobre os marcadores explícitos ("X Season 2", "X II").
// A AniList também nomeia temporada com um número solto no fim ("... desu 2"),
// que `tituloSemMarcadores` deixa passar de propósito — um dígito solto sem
// marcador de palavra na frente pode ser parte do nome ("Steins;Gate 0",
// "86", "91 Days"). Quando o `numero_temporada` da temporada é conhecido, dá
// pra tirar com segurança só o dígito que casa esse número (nunca o "0" de
// "Steins;Gate 0", que não é temporada 0). Usado no título exibido do card de
// franquia e do H1 da página do anime quando a franquia tem 2+ temporadas.
export function tituloBaseDeTemporada(titulo, numeroTemporada) {
  const base = tituloSemMarcadores(titulo);
  if (numeroTemporada == null) return base;
  const semNumero = base.replace(new RegExp(`\\s+0*${numeroTemporada}\\s*$`), '').trimEnd();
  return semNumero === '' ? base : semNumero;
}

// Instância única de módulo (recriar `Intl.*` por render é caro).
const fmtDataEstreia = new Intl.DateTimeFormat('pt-BR', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

// "2ª temporada estreia em 4 de outubro de 2026" (`curto: false`, default) ou
// "2ª temporada em 4 de outubro de 2026" (`curto: true`, card do catálogo —
// espaço menor, "estreia" é redundante ao lado do resto da legenda) a partir
// de `anime.proxima_temporada` (`AnimeSaida`/`AnimeDetalheSaida`) — a
// temporada seguinte da franquia que ainda não saiu. Com `estreia_em` (ISO
// `YYYY-MM-DD`, parse com `T00:00:00` pra cair na meia-noite LOCAL, evita o
// dia anterior por fuso) mostra a data completa; sem ela, degrada pro ano
// (`proxima.ano`). `null` = nada a anunciar. Usado no hero da página do
// anime (`paginas/PaginaDoAnime.jsx`) e no card do catálogo
// (`components/AnimeCard.jsx`) — mesma função, só a variante muda.
export function textoDeProximaTemporada(proxima, { curto = false } = {}) {
  if (!proxima) return null;
  const ordinal =
    proxima.numero_temporada != null ? `${proxima.numero_temporada}ª temporada` : proxima.titulo;
  const verbo = curto ? 'em' : 'estreia em';
  if (proxima.estreia_em) {
    const data = new Date(`${proxima.estreia_em}T00:00:00`);
    if (!Number.isNaN(data.getTime())) {
      return `${ordinal} ${verbo} ${fmtDataEstreia.format(data)}`;
    }
  }
  if (proxima.ano) return `${ordinal} ${verbo} ${proxima.ano}`;
  return null;
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
//   - `assistido`: `true` quando alguma temporada tem episódio E toda temporada
//     com episódio está `assistido` pelo backend (terminou de ver — todos os eps
//     da fonte vistos, sem buraco) — o card ganha a tag "Assistido".
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

// Uma temporada é "acessível" quando dá pra fazer algo com ela na página do
// anime: já tem episódio capturado, OU já saiu do estado "não lançado" (aí a
// PaginaDoAnime resolve fonte / enfileira captura). Uma T2 ainda `nao_lancado`
// e sem captura é só um bookmark de "Próximas estreias" — não pode ser a cara
// (nem o alvo de clique) da franquia se existe uma temporada anterior de
// verdade. Mesmo predicado que `paginas/Galeria.jsx` usa pra decidir
// CartaoDeEstreia inerte × AnimeCard navegável, só que por temporada.
function temporadaAcessivel(temporada) {
  return Boolean(temporada.tem_episodios) || temporada.status_lancamento !== 'nao_lancado';
}

function montarFranquia(temporadas) {
  const maisRecente = (maior, atual) =>
    (atual.numero_temporada ?? 0) > (maior.numero_temporada ?? 0) ? atual : maior;
  // Representa a última temporada ACESSÍVEL; só cai pra última em número
  // absoluto quando a franquia inteira ainda é estreia futura (aí o card
  // vira CartaoDeEstreia de propósito).
  const acessiveis = temporadas.filter(temporadaAcessivel);
  const representante = (acessiveis.length > 0 ? acessiveis : temporadas).reduce(maisRecente);
  const varias = temporadas.length > 1;
  const episodiosNovos = temporadas.reduce((soma, t) => soma + (t.episodios_novos ?? 0), 0);
  const temEpisodios = temporadas.some((t) => t.tem_episodios);
  return {
    ...representante,
    titulo: varias
      ? tituloBaseDeTemporada(representante.titulo, representante.numero_temporada)
      : representante.titulo,
    episodios_novos: episodiosNovos,
    tem_episodios: temEpisodios,
    // Franquia "assistida": tem conteúdo e TODA temporada com episódio já foi
    // terminada (o `assistido` do backend já exige "todos os eps da fonte
    // vistos", então aqui é só o `every`).
    assistido: temEpisodios && temporadas.every((t) => !t.tem_episodios || t.assistido),
    generos: [...new Set(temporadas.flatMap((t) => t.generos ?? []))],
    statusDaFranquia: [...new Set(temporadas.map((t) => t.status_lancamento).filter(Boolean))],
    titulosDaFranquia: temporadas.map((t) => t.titulo),
    idsDaFranquia: temporadas.map((t) => t.id),
    contagemDeTemporadas: temporadas.length,
  };
}
