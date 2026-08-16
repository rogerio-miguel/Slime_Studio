// Cliente HTTP fino sobre `fetch` nativo. Same-origin via proxy do Vite
// (vite.config.js `server.proxy`) — o cookie HttpOnly de sessão viaja
// automaticamente em requisições same-origin, sem precisar de
// `credentials: 'include'` cross-origin nem mexer em `player/fonteHls.js`
// (que já seta `video.crossOrigin = 'anonymous'`, motivo do proxy existir).
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

export class NaoAutenticado extends ErroDeApi {
  constructor(detail) {
    super(401, detail);
    this.name = 'NaoAutenticado';
  }
}

let tratadorDeSessaoExpirada = null;

// Registrado uma vez por `SessaoContexto.jsx` no mount — permite reagir a um
// 401 vindo de qualquer profundidade (REST aqui, ou o close 1008 do
// `/ws/admin` via `useEventosDeJobs.js`) sem prop drilling do estado de
// sessão até cada chamador.
export function definirTratadorDeSessaoExpirada(callback) {
  tratadorDeSessaoExpirada = callback;
}

// Exportado à parte de `definirTratadorDeSessaoExpirada` pra quem só precisa
// DISPARAR o fluxo de sessão expirada (ex. `useEventosDeJobs.js` no 1008) sem
// precisar importar estado de sessão nenhum.
export function notificarSessaoExpirada() {
  tratadorDeSessaoExpirada?.();
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
export async function requisitar(caminho, { metodo = 'GET', corpo } = {}) {
  const resposta = await fetch(caminho, {
    method: metodo,
    credentials: 'same-origin',
    headers: corpo !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: corpo !== undefined ? JSON.stringify(corpo) : undefined,
  });

  if (resposta.status === 401) {
    const detail = await corpoDeErro(resposta);
    notificarSessaoExpirada();
    throw new NaoAutenticado(detail);
  }

  if (!resposta.ok) {
    throw new ErroDeApi(resposta.status, await corpoDeErro(resposta));
  }

  if (resposta.status === 204) return null;
  return resposta.json();
}
