// Uma função por endpoint confirmado no código-fonte do backend (Fase 3) —
// tradução de campos camelCase (uso no frontend) <-> snake_case (contrato
// HTTP) fica só aqui, nunca espalhada pelas páginas/componentes.
import { requisitar } from './cliente.js';
import { invalidar } from './invalidacao.js';

// `aquecer` (opt-in) liga a carona fire-and-forget do backend — sondagem da
// fonte real + aquecimento de `status_lancamento` via AniList/Kitsu. Só a
// Galeria (rota `/animes`, catálogo completo com os badges) passa `true`; a
// Home chama sem a flag e não paga esse custo a cada abertura.
export function listarAnimes({ aquecer = false } = {}) {
  return requisitar(aquecer ? '/api/animes?aquecer=true' : '/api/animes');
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

// Busca livre na biblioteca de metadados (AniList) — alimenta a busca da Home.
// Mesmo formato de item do feed "em alta" (`{ titulo_romaji, capa_url,
// banner_url, anilist_id, anime_id, generos, capa_cor, ... }`); `anime_id` vem
// preenchido quando aquela temporada já está no catálogo local.
export function buscarAnimes(titulo) {
  return requisitar(`/api/animes/buscar?titulo=${encodeURIComponent(titulo)}`);
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

// Busca ao vivo em sites de extração (DialogoDeTrocaDeFonte): varre todos os
// domínios/versões e devolve a UNIÃO das fontes onde o anime existe. Resolve
// para `{ resultados, fontes }`: `resultados` são os candidatos achatados,
// `fontes` é o status de cada site consultado (`{ dominio, indisponivel,
// motivo }`) — distingue "busquei e não achei nada" de "não consegui nem
// tentar" (cooldown/erro).
export function buscarEmFontes(titulo) {
  return requisitar(`/api/animes/buscar-fontes?titulo=${encodeURIComponent(titulo)}`);
}

export function marcarAssistido(episodioId) {
  return requisitar(`/api/episodios/${episodioId}/assistido`, { metodo: 'POST' }).then((resultado) => {
    invalidar('episodios');
    return resultado;
  });
}

// Botão "Marcar como assistido" da página do anime — marca em lote todo
// episódio já capturado que ainda não tem `assistido_em`, E cria (sem Job)
// um episódio pra cada número que a fonte ativa lista e o usuário nunca
// capturou (ver `api/servicos/jobs.py::marcar_todos_assistidos`). `versao`
// mesmo papel de `listarEpisodiosRemotos`/`criarJobSite` — decide qual fonte
// resolver pro segundo passo (`PaginaDoAnime.jsx::versaoPedida`).
export function marcarTodosAssistidos(animeId, versao) {
  const query = versao ? `?versao=${encodeURIComponent(versao)}` : '';
  return requisitar(`/api/admin/animes/${animeId}/marcar-todos-assistidos${query}`, {
    metodo: 'POST',
  }).then((resultado) => {
    invalidar('episodios');
    return resultado;
  });
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
  }).then((resultado) => {
    invalidar('episodios');
    return resultado;
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
  return requisitar(`/api/episodios/${episodioId}/liberar`, { metodo: 'POST', manterVivo }).then(
    (resultado) => {
      invalidar('episodios');
      return resultado;
    }
  );
}

// `anilistId`/`kitsuId`/`capaUrl`/`sinopse`/`bannerUrl`/`capaCor`/`generos`/
// `tituloIngles` são opcionais (materialização de item do feed "em alta" —
// Fase 4 da Inicio) — ausentes, `JSON.stringify` os omite do corpo (mesmo
// comportamento já usado por `ano` acima) e o backend enriquece por título em
// best-effort (`api/rotas/animes.py`); qualquer campo de metadado presente no
// payload faz o backend pular esse enriquecimento (curto-circuito em
// `CriarAnimeRequest`).
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
  tituloIngles,
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
      titulo_ingles: tituloIngles,
    },
  }).then((resultado) => {
    invalidar('animes');
    return resultado;
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
  return requisitar(`/api/admin/animes/${animeId}`, { metodo: 'DELETE' }).then((resultado) => {
    invalidar('animes');
    return resultado;
  });
}
