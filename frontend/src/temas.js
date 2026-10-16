import { aplicarFavicon } from './faviconDoTema.js';

// Temas de accent. As cores de verdade moram em `index.css`
// (`:root[data-tema='...']`); `cor` aqui é só a amostra do menu e precisa
// acompanhar o `--color-neon` de cada bloco. Tema novo: um bloco no CSS + uma
// linha aqui.
export const TEMAS = [
  { id: 'azul', nome: 'Azul', cor: '#2080f0' },
  { id: 'roxo', nome: 'Roxo', cor: '#b026ff' },
  { id: 'laranja', nome: 'Laranja', cor: '#ff7518' },
];

export const TEMA_PADRAO = 'azul';
const CHAVE_DO_TEMA = 'slime.tema';

const temaPorId = (id) => TEMAS.find((tema) => tema.id === id);
const ehTemaValido = (id) => temaPorId(id) !== undefined;

// Valor salvo é entrada não confiável (storage editável, tema removido numa
// versão nova): id desconhecido cai no padrão em vez de aplicar um atributo
// sem bloco no CSS.
export function lerTemaSalvo() {
  try {
    const salvo = localStorage.getItem(CHAVE_DO_TEMA);
    return ehTemaValido(salvo) ? salvo : TEMA_PADRAO;
  } catch {
    return TEMA_PADRAO; // storage bloqueado (modo anônimo): vale só nesta sessão
  }
}

export function aplicarTema(id) {
  const tema = temaPorId(id) ?? temaPorId(TEMA_PADRAO);
  document.documentElement.dataset.tema = tema.id;
  aplicarFavicon(tema.cor);
}

export function salvarTema(id) {
  try {
    localStorage.setItem(CHAVE_DO_TEMA, id);
  } catch {
    // best-effort: falha de storage não pode quebrar a troca de tema
  }
}
