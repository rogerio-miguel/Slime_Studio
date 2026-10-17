import { dataChaveDeEstreia } from './fileiras.js';

// Busca, filtro, gêneros e ordem do catálogo (`paginas/Galeria.jsx`), sobre as
// franquias já agrupadas (inicio/franquia.js). Derivações puras, client-side,
// que nunca mutam a entrada. O painel de filtros da ilha
// (components/ilha/RegiaoDoPainelDeFiltros.jsx) usa as mesmas funções pra
// contar quantos animes cada gênero deixaria na grade.

export const ORDEM_PADRAO = 'titulo-asc';
export const OPCOES_DE_ORDEM = [
  { valor: 'titulo-asc', rotulo: 'A–Z', curto: 'A–Z' },
  { valor: 'titulo-desc', rotulo: 'Z–A', curto: 'Z–A' },
  { valor: 'recentes', rotulo: 'Adicionados recentemente', curto: 'Recentes' },
  { valor: 'estreia', rotulo: 'Estreia mais recente', curto: 'Estreia' },
];

// "Próximas estreias" é o `status_lancamento` `nao_lancado`: o filtro tem ordem
// FIXA (data da temporada futura, a mesma da fileira da Home) e some a seleção
// de ordem do painel.
export const FILTRO_PROXIMAS_ESTREIAS = 'status:nao_lancado';

const porTitulo = (a, b) => a.titulo.localeCompare(b.titulo, 'pt-BR');
// Sem data vai pro fim; empate cai no título (ordem estável entre reloads).
const comNuloNoFim = (valorDe, sentido) => (a, b) => {
  const va = valorDe(a);
  const vb = valorDe(b);
  if (va === vb) return porTitulo(a, b);
  if (va == null) return 1;
  if (vb == null) return -1;
  return va < vb ? -sentido : sentido;
};

const COMPARADORES = {
  'titulo-asc': porTitulo,
  'titulo-desc': (a, b) => porTitulo(b, a),
  recentes: comNuloNoFim((franquia) => franquia.adicionado_em, -1),
  estreia: comNuloNoFim((franquia) => franquia.estreia_em, -1),
};

const instanteDaEstreia = (franquia) => {
  const chave = dataChaveDeEstreia(franquia.temporadaFutura ?? franquia);
  return Number.isFinite(chave) ? chave : null;
};

const porDataDaTemporadaFutura = comNuloNoFim(instanteDaEstreia, 1);

// "Em lançamento" também tem ordem FIXA: quem lança o próximo episódio mais
// cedo vem primeiro. Data já passada (ep que saiu e o dado ainda não foi
// renovado) ou ausente vai pro fim — não é "o mais perto".
export const FILTRO_EM_LANCAMENTO = 'status:em_lancamento';

export const temOrdemFixa = (filtro) =>
  filtro === FILTRO_PROXIMAS_ESTREIAS || filtro === FILTRO_EM_LANCAMENTO;

// Instante do próximo episódio ainda por vir (o mais cedo entre as temporadas em
// lançamento) ou `null`.
function instanteDoProximoEpisodio(franquia, agora) {
  const futuros = franquia.proximosEpisodiosEm
    .map((data) => new Date(data).getTime())
    .filter((instante) => instante >= agora);
  return futuros.length > 0 ? Math.min(...futuros) : null;
}

const porProximoEpisodio = (agora) =>
  comNuloNoFim((franquia) => instanteDoProximoEpisodio(franquia, agora), 1);

// Agrupa franquias JÁ ordenadas pelo filtro de ordem fixa em dias locais, na
// mesma ordem; quem não tem data cai no último grupo (`data: null`).
export function agruparPorDiaDoFiltro(franquias, filtro) {
  const agora = Date.now();
  const instanteDe =
    filtro === FILTRO_PROXIMAS_ESTREIAS
      ? instanteDaEstreia
      : (franquia) => instanteDoProximoEpisodio(franquia, agora);
  const grupos = new Map();
  for (const franquia of franquias) {
    const instante = instanteDe(franquia);
    const data = instante == null ? null : new Date(instante);
    const chave = data ? `${data.getFullYear()}-${data.getMonth()}-${data.getDate()}` : 'sem-data';
    if (!grupos.has(chave)) grupos.set(chave, { chave, data, itens: [] });
    grupos.get(chave).itens.push(franquia);
  }
  return [...grupos.values()];
}

export function ordenarFranquias(lista, ordem, filtro) {
  let comparador = COMPARADORES[ordem];
  if (filtro === FILTRO_PROXIMAS_ESTREIAS) comparador = porDataDaTemporadaFutura;
  else if (filtro === FILTRO_EM_LANCAMENTO) comparador = porProximoEpisodio(Date.now());
  return [...lista].sort(comparador);
}

// `filtro` decide o eixo pelo prefixo (`status:`/`assistido:`/`novos:`); status
// bate se QUALQUER temporada da franquia bate, assistido e novos usam o agregado
// da franquia inteira. `generos` (Set) soma ao filtro: precisa ter TODOS.
export function filtrarFranquias(franquias, { termo = '', filtro = '', generos }) {
  let lista = franquias;
  if (termo) {
    lista = lista.filter((franquia) =>
      franquia.titulosDaFranquia.some((titulo) => titulo.toLowerCase().includes(termo)),
    );
  }
  if (filtro.startsWith('status:')) {
    const status = filtro.slice('status:'.length);
    lista = lista.filter((franquia) => franquia.statusDaFranquia.includes(status));
  } else if (filtro.startsWith('assistido:')) {
    const assistido = filtro.slice('assistido:'.length) === 'sim';
    lista = lista.filter((franquia) => franquia.assistido === assistido);
  } else if (filtro === 'novos:sim') {
    lista = lista.filter((franquia) => franquia.episodios_novos > 0);
  }
  if (generos?.size > 0) {
    lista = lista.filter((franquia) => [...generos].every((g) => franquia.generos.includes(g)));
  }
  return lista;
}

// Quantos animes sobrariam ao marcar cada gênero (somado aos já marcados). Pra
// um gênero já marcado é o tamanho da grade atual.
export function contarPorGenero(franquias, { termo, filtro, generos }, listaDeGeneros) {
  const base = filtrarFranquias(franquias, { termo, filtro });
  const contagens = new Map();
  for (const genero of listaDeGeneros) {
    const marcados = new Set(generos);
    marcados.add(genero);
    contagens.set(genero, filtrarFranquias(base, { generos: marcados }).length);
  }
  return contagens;
}
