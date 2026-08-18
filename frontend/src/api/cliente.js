// Cliente HTTP fino sobre `fetch` nativo. Same-origin via proxy do Vite
// (vite.config.js `server.proxy`) — necessário porque `player/fonteHls.js`
// seta `video.crossOrigin = 'anonymous'` no `<video>` que alimenta o hls.js;
// sem o proxy, o manifesto/segmentos HLS seriam cross-origin de verdade.
//
// Erro polimórfico do backend: `detail` é string na maioria dos casos, mas
// um objeto `{motivo, ...}` nos três 409 de domínio (fonte_ambigua,
// episodio_ja_existe, job_em_execucao) — normalizado aqui uma vez só, nunca
// reimplementado por chamador.

export class ErroDeApi extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : (detail?.motivo ?? 'erro de API'));
    this.name = 'ErroDeApi';
    this.status = status;
    this.detail = detail;
  }
}

async function corpoDeErro(resposta) {
  try {
    const dados = await resposta.json();
    return dados.detail ?? resposta.statusText ?? 'erro de API';
  } catch {
    return resposta.statusText || 'erro de API';
  }
}

// `corpo`, quando presente, vai serializado (objeto -> JSON) — chamador
// nunca faz JSON.stringify na mão. Sem timeout/AbortController de propósito:
// a criação de job em modo "site" é síncrona no servidor e pode levar até
// ~120s — um timeout curto aqui abortaria só o fetch do cliente, sem
// cancelar o trabalho já em andamento no backend (decisão do plano).
//
// `manterVivo` repassa `keepalive: true` ao `fetch` — necessário pros
// disparos fire-and-forget de saída de página (`liberarEpisodio`/
// `salvarProgresso` em `pagehide`, PaginaDoPlayer.jsx): sem isto o browser
// pode abortar o request no meio quando a página já está sendo descartada.
export async function requisitar(caminho, { metodo = 'GET', corpo, manterVivo = false } = {}) {
  const resposta = await fetch(caminho, {
    method: metodo,
    credentials: 'same-origin',
    headers: corpo !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: corpo !== undefined ? JSON.stringify(corpo) : undefined,
    keepalive: manterVivo,
  });

  if (!resposta.ok) {
    throw new ErroDeApi(resposta.status, await corpoDeErro(resposta));
  }

  if (resposta.status === 204) return null;
  return resposta.json();
}
