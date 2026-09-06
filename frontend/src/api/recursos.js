// Uma função por endpoint confirmado no código-fonte do backend (Fase 3) —
// tradução de campos camelCase (uso no frontend) <-> snake_case (contrato
// HTTP) fica só aqui, nunca espalhada pelas páginas/componentes.
import { requisitar } from './cliente.js';

export function listarAnimes() {
  return requisitar('/api/animes');
}

export function listarAnimesEmAlta() {
  return requisitar('/api/animes/em-alta');
}

export function listarProximaTemporada() {
  return requisitar('/api/animes/proxima-temporada');
}

export function listarFileirasTematicas() {
  return requisitar('/api/animes/fileiras-tematicas');
}

export function obterAnime(animeId) {
  return requisitar(`/api/animes/${animeId}`);
}

export function listarEpisodios(animeId) {
  return requisitar(`/api/animes/${animeId}/episodios`);
}

// `{ dominio, episodios: [{ rotulo, numero }] }` — `dominio` é o site que
// resolveu a lista (exibido na página do anime pra o usuário notar quando a
// fonte "errada" foi usada); `numero` é `null` quando `rotulo` não é
// puramente numérico (ex. "Especial") — episódio aparece na lista mas ainda
// não é capturável. `versao` ("legendado"|"dublado") é enviada explicitamente
// pelo chamador agora (Fase 4 — antes o backend assumia "legendado" quando
// omitido; o frontend não depende mais desse default).
export function listarEpisodiosRemotos(animeId, versao) {
  const query = versao ? `?versao=${encodeURIComponent(versao)}` : '';
  return requisitar(`/api/admin/animes/${animeId}/episodios-remotos${query}`);
}

// Busca ao vivo em sites de extração (ainda não catalogado localmente).
// `escopo` espelha o parâmetro do backend (`padrao|todas`, default `padrao`):
// `padrao` é o motor sequencial de fonte única (Home, subseção "Resultados em
// outras fontes"); `todas` varre todos os domínios/versões numa única rodada
// de variante vencedora (DialogoDeTrocaDeFonte). Resolve para
// `{ resultados, fontes }` (não mais um array direto): `resultados` são os
// candidatos achatados de todas as fontes disponíveis, `fontes` é o status de
// cada site consultado (`{ dominio, indisponivel, motivo }`) — distingue
// "busquei e não achei nada" de "não consegui nem tentar" (cooldown/erro).
export function buscarEmFontes(titulo, escopo = 'padrao') {
  return requisitar(
    `/api/animes/buscar-fontes?titulo=${encodeURIComponent(titulo)}&escopo=${encodeURIComponent(escopo)}`
  );
}

export function marcarAssistido(episodioId) {
  return requisitar(`/api/episodios/${episodioId}/assistido`, { metodo: 'POST' });
}

// Fallback de refresh do player (PaginaDoPlayer.jsx) quando `location.state`
// não veio (acesso direto/refresh da URL) — também traz `progresso_s` pra
// retomar a reprodução de onde parou.
export function obterEpisodio(episodioId) {
  return requisitar(`/api/episodios/${episodioId}`);
}

// Disparado periodicamente pelo player (usePosicaoDeReproducao.js) enquanto
// o episódio ainda não cruzou o limiar de assistido — o backend recusa
// (422) segundos acima de 90% da duração, ramo que pertence a
// `marcarAssistido`/`liberarEpisodio`. `manterVivo` (`keepalive`) pelo mesmo
// motivo de `liberarEpisodio`: pode sair de dentro de um listener de
// `pagehide`.
export function salvarProgresso(episodioId, segundos, { manterVivo } = {}) {
  return requisitar(`/api/episodios/${episodioId}/progresso`, {
    metodo: 'POST',
    corpo: { segundos },
    manterVivo,
  });
}

// Prateleira "Continuar assistindo" da Inicio.
export function listarContinuarAssistindo() {
  return requisitar('/api/episodios/continuar-assistindo');
}

// Dispara na saída do player (PaginaDoPlayer.jsx) quando o episódio cruzou o
// limiar de assistido — apaga os arquivos em disco preservando o registro do
// catálogo (`assistido_em`, `url_fonte`, etc.). `manterVivo` (`keepalive`)
// porque este request costuma sair de dentro de um listener de `pagehide`,
// com a página já sendo descartada.
export function liberarEpisodio(episodioId, { manterVivo } = {}) {
  return requisitar(`/api/episodios/${episodioId}/liberar`, { metodo: 'POST', manterVivo });
}

// `anilistId`/`kitsuId`/`capaUrl`/`sinopse`/`bannerUrl`/`capaCor`/`generos` são
// opcionais (materialização de item do feed "em alta" — Fase 4 da Inicio) —
// ausentes, `JSON.stringify` os omite do corpo (mesmo comportamento já usado
// por `ano` acima) e o backend enriquece por título em best-effort
// (`api/rotas/animes.py`); qualquer campo de metadado presente no payload faz
// o backend pular esse enriquecimento (curto-circuito em `CriarAnimeRequest`).
export function criarAnime({
  titulo,
  ano,
  anilistId,
  kitsuId,
  capaUrl,
  sinopse,
  bannerUrl,
  capaCor,
  generos,
} = {}) {
  return requisitar('/api/admin/animes', {
    metodo: 'POST',
    corpo: {
      titulo,
      ano,
      anilist_id: anilistId,
      kitsu_id: kitsuId,
      capa_url: capaUrl,
      sinopse,
      banner_url: bannerUrl,
      capa_cor: capaCor,
      generos: generos,
    },
  });
}

export function criarJobSite({ animeId, numero, tipo, versao, duracaoEsperadaS }) {
  return requisitar('/api/admin/jobs', {
    metodo: 'POST',
    corpo: {
      modo: 'site',
      anime_id: animeId,
      numero,
      tipo,
      versao,
      duracao_esperada_s: duracaoEsperadaS,
    },
  });
}

// `versao` ("legendado"|"dublado"|null) é o round-trip do que `buscar-fontes`
// já informou sobre este candidato (`candidato.versao`) — o servidor
// re-deriva e valida sozinho, o frontend só repassa o que já sabe.
export function confirmarFonte(animeId, { dominio, identificador, tituloExibicao, url, versao }) {
  return requisitar(`/api/admin/animes/${animeId}/fontes/confirmar`, {
    metodo: 'POST',
    corpo: { dominio, identificador, titulo_exibicao: tituloExibicao, url, versao: versao ?? null },
  });
}

export function removerAnime(animeId) {
  return requisitar(`/api/admin/animes/${animeId}`, { metodo: 'DELETE' });
}
