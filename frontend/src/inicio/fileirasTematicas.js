// Derivações puras do endpoint `GET /api/animes/fileiras-tematicas` para as
// fileiras temáticas da home. Sem React, sem imports de `../api/`: recebe o
// array cru do endpoint e devolve um array NOVO — nunca muta a entrada.
// Mesma disciplina de ./fileiras.js.

// Rótulo PT de cada `chave` conhecida (`backend/integrations/registro.py::
// FILEIRAS_TEMATICAS`). Fonte única de tradução — nada de string solta em
// paginas/Inicio.jsx.
export const ROTULOS_DE_FILEIRA = {
  isekai: 'Isekai',
  familia_encontrada: 'Família encontrada',
  amor_nao_correspondido: 'Amor não correspondido',
  batalha_real: 'Battle royale',
  diferenca_de_idade: 'Diferença de idade',
  reencarnacao: 'Reencarnação',
  jogos_mortais: 'Jogos mortais',
  morando_juntos: 'Morando juntos',
  casais_secretos: 'Relacionamento secreto',
  vila_nao_tao_vila: 'Era pra ser a vilã',
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
