import { traduzirGenero } from './generos.js';

// Derivações puras do feed `GET /api/animes/em-alta` para as fileiras da home.
// Sem React, sem imports de `../api/`: cada função recebe a lista do feed e
// devolve um array NOVO — nunca muta a entrada.

// Lista de gêneros que nunca viram fileira. Ponto único de ajuste: Ecchi fica
// FORA da exclusão (decisão do usuário), só Hentai é barrado.
export const GENEROS_EXCLUIDOS = ['Hentai'];

// (A fileira "Próximas estreias" NÃO sai daqui — o feed `em-alta` só lista o
// que já está no ar. Ela vem do endpoint próprio `GET /api/animes/proxima-
// temporada` e é consumida direto em paginas/Inicio.jsx. `ordenarPorEstreia`
// abaixo é só a ordenação dela — mora aqui por ser a mesma classe de derivação
// pura das outras fileiras desta página.)

// Data-chave de ordenação — só os dois sinais de DATA EXATA do texto exibido
// no card (`inicio/CartaoDeEstreia.jsx::textoDeEstreia`: proximo_ep_em >
// estreia_em), achatados num timestamp comparável. `ano`/`ano_estreia` sozinho
// (rótulo genérico "Estreia em 2026") NÃO vira chave de data aqui de propósito
// — um "1º de janeiro" implícito colocaria esses cards NA FRENTE de itens com
// data exata mais tarde no mesmo ano (ou em anos seguintes), que é o oposto do
// pedido: "estreia em <ano>" é a fileira toda que sabe MENOS, não mais cedo —
// cai no mesmo `Infinity` de quem não tem nenhum sinal, ficando sempre no
// final junto dos dois.
function dataChaveDeEstreia(item) {
  if (item.proximo_ep_em) {
    const data = new Date(item.proximo_ep_em);
    if (!Number.isNaN(data.getTime())) return data.getTime();
  }
  if (item.estreia_em) {
    // Sufixo `T00:00:00` pelo mesmo motivo de `textoDeEstreia`: cair na meia-
    // noite LOCAL, não UTC.
    const data = new Date(`${item.estreia_em}T00:00:00`);
    if (!Number.isNaN(data.getTime())) return data.getTime();
  }
  return Infinity;
}

// Ordena a fileira "Próximas estreias" por data crescente; os sem nenhuma data
// conhecida ficam no final. Reordena sozinha a cada novo `itens` (ex.: o warm
// de lançamento preenche `proximo_ep_em`/`estreia_em` de um item que antes só
// tinha o ano) — sem estado próprio, é derivação pura como as outras acima.
export function ordenarPorEstreia(itens) {
  return [...(itens ?? [])].sort((a, b) => dataChaveDeEstreia(a) - dataChaveDeEstreia(b));
}

// Top N da temporada. O feed já chega ordenado por trending/popularidade da
// AniList — NÃO adicionar sort aqui, é de propósito; só recorta os primeiros n.
export function topDaTemporada(itens, n = 10) {
  return (itens ?? []).slice(0, n);
}

// Uma fileira por gênero "quente" no feed atual. Conta em quantos itens cada
// gênero aparece (um item conta para cada gênero seu); descarta gêneros abaixo
// de `minimoPorFileira` e os de `excluir`; ordena por frequência desc com
// desempate alfabético pelo nome AniList (estável entre reloads); corta em
// `maxFileiras`. Cada fileira devolve os itens do feed com aquele gênero, na
// ordem original do feed.
export function fileirasPorGenero(
  itens,
  { maxFileiras = 3, minimoPorFileira = 6, excluir = GENEROS_EXCLUIDOS } = {},
) {
  const lista = itens ?? [];

  const frequencia = new Map();
  for (const item of lista) {
    for (const genero of item.generos ?? []) {
      frequencia.set(genero, (frequencia.get(genero) ?? 0) + 1);
    }
  }

  const excluidos = new Set(excluir);
  return [...frequencia.entries()]
    .filter(([genero, contagem]) => contagem >= minimoPorFileira && !excluidos.has(genero))
    .sort(([generoA, contA], [generoB, contB]) => contB - contA || generoA.localeCompare(generoB))
    .slice(0, maxFileiras)
    .map(([genero]) => ({
      genero,
      generoPt: traduzirGenero(genero),
      itens: lista.filter((item) => (item.generos ?? []).includes(genero)),
    }));
}
