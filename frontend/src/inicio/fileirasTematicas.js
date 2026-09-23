// Derivações puras do endpoint `GET /api/animes/fileiras-tematicas` para as
// fileiras temáticas da home. Sem React, sem imports de `../api/`: recebe o
// array cru do endpoint e devolve um array NOVO — nunca muta a entrada.
// Mesma disciplina de ./fileiras.js.

// Rótulo PT de cada `chave` conhecida (`backend/integrations/registro.py::
// FILEIRAS_TEMATICAS`). Fonte única de tradução — nada de string solta em
// paginas/Inicio.jsx. Refeitos do zero em 2026-09-20, inspirados na curadoria
// do discover da Crunchyroll (título com apelo em vez do nome cru do gênero).
export const ROTULOS_DE_FILEIRA = {
  acao_sem_parar: 'Ação sem parar',
  isekai: 'Isekai: outro mundo te espera',
  misterio_pra_desvendar: 'Mistério pra desvendar',
  so_rir_pra_nao_chorar: 'Só rir pra não chorar',
  terror_que_tira_o_sono: 'Terror que tira o sono',
  gigantes_de_aco: 'Gigantes de aço',
  adrenalina_no_esporte: 'Adrenalina no esporte',
  fantasia_alem_do_real: 'Fantasia além do real',
  vida_cotidiana_sem_pressa: 'Vida cotidiana, sem pressa',
  prepare_o_lenco: 'Prepare o lenço',
};

// Traduz e recorta o array cru do endpoint. Duas responsabilidades que só
// fazem sentido juntas aqui:
//   1. Descarta qualquer fileira cuja `chave` não tenha rótulo conhecido —
//      proteção intencional: o backend pode evoluir `FILEIRAS_TEMATICAS` sem
//      o frontend acompanhar no mesmo commit, e uma fileira sem rótulo PT não
//      deve vazar pra tela com a chave crua.
//   2. Corta `itens` para `maxItensPorFileira` — a query do backend já traz
//      até 50 itens por fileira de propósito (margem pro corte), o corte de
//      exibição em si é responsabilidade desta camada (frontend), não do
//      backend.
export function rotularFileiras(fileiras, { maxItensPorFileira = 20 } = {}) {
  return (fileiras ?? [])
    .filter((fileira) => ROTULOS_DE_FILEIRA[fileira.chave] != null)
    .map((fileira) => ({
      chave: fileira.chave,
      rotulo: ROTULOS_DE_FILEIRA[fileira.chave],
      itens: (fileira.itens ?? []).slice(0, maxItensPorFileira),
    }));
}
