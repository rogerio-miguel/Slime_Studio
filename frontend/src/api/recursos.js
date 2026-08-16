// Uma função por endpoint confirmado no código-fonte do backend (Fase 3) —
// tradução de campos camelCase (uso no frontend) <-> snake_case (contrato
// HTTP) fica só aqui, nunca espalhada pelas páginas/componentes.
import { requisitar } from './cliente.js';

export function listarAnimes() {
  return requisitar('/api/animes');
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

export function criarAnime({ titulo, ano }) {
  return requisitar('/api/admin/animes', { metodo: 'POST', corpo: { titulo, ano } });
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
