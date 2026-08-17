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

export function obterAnime(animeId) {
  return requisitar(`/api/animes/${animeId}`);
}

export function listarEpisodios(animeId) {
  return requisitar(`/api/animes/${animeId}/episodios`);
}

export function listarEpisodiosRemotos(animeId) {
  return requisitar(`/api/admin/animes/${animeId}/episodios-remotos`);
}

export function marcarAssistido(episodioId) {
  return requisitar(`/api/episodios/${episodioId}/assistido`, { metodo: 'POST' });
}

// `anilistId`/`kitsuId`/`capaUrl`/`sinopse` são opcionais (materialização de
// item do feed "em alta" — Fase 4 da Inicio) — ausentes, `JSON.stringify`
// os omite do corpo (mesmo comportamento já usado por `ano` acima) e o
// backend enriquece por título em best-effort (`api/rotas/animes.py`).
export function criarAnime({ titulo, ano, anilistId, kitsuId, capaUrl, sinopse } = {}) {
  return requisitar('/api/admin/animes', {
    metodo: 'POST',
    corpo: {
      titulo,
      ano,
      anilist_id: anilistId,
      kitsu_id: kitsuId,
      capa_url: capaUrl,
      sinopse,
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

export function confirmarFonte(animeId, { dominio, identificador, tituloExibicao, url }) {
  return requisitar(`/api/admin/animes/${animeId}/fontes/confirmar`, {
    metodo: 'POST',
    corpo: { dominio, identificador, titulo_exibicao: tituloExibicao, url },
  });
}

export function removerAnime(animeId) {
  return requisitar(`/api/admin/animes/${animeId}`, { metodo: 'DELETE' });
}
