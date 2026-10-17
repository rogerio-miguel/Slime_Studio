// Fundos dos controles e dos menus da barra de controles da página do anime e
// do player. Os dois visuais existem lado a lado de propósito: trocar o de um
// grupo é mudar uma linha da seção "Escolha por grupo". Os valores são strings
// literais (o Tailwind só gera classes que aparecem inteiras no código).

// Visual anterior dos menus.
export const FUNDO_ANTIGO = 'bg-[#0f0f10]';
// Fundo da cápsula da ilha (`FUNDO_DA_ILHA` em `hooks/useSinopseNaCapsula.js`).
// `COR_DA_ILHA` é a mesma cor como valor CSS, pra quem pinta por `style` (painel
// da Galeria): manter igual ao `FUNDO_DA_ILHA`, que precisa ser literal pro
// Tailwind.
export const COR_DA_ILHA = '#0d0d0d';
export const FUNDO_DA_ILHA = 'bg-[#0d0d0d]';
// Fundo do painel da sinopse na ilha (`hooks/useSinopseNaCapsula.js`,
// `FUNDO_PAINEL_PADRAO`): azulado, 6% de transparência.
export const FUNDO_DA_SINOPSE = 'bg-[rgb(10_12_16/0.94)]';

// --- Escolha por grupo ---
// Pílula de fonte, alternador grade/lista, botão de ordem e botão ⋯.
export const FUNDO_DOS_CONTROLES = FUNDO_DA_SINOPSE;
// Menus que abrem: temporada, ações e painel da fonte.
export const FUNDO_DOS_MENUS = FUNDO_ANTIGO;
// Menus que saem da ilha da navbar (seletor de seções, filtros): mesma cor dela.
export const FUNDO_DOS_MENUS_DA_ILHA = FUNDO_DA_ILHA;
// Menu de configurações do player.
export const FUNDO_DO_MENU_DO_PLAYER = FUNDO_DA_SINOPSE;

export const CLASSE_PAINEL_FLUTUANTE = `overflow-hidden rounded-2xl border border-border-chrome ${FUNDO_DOS_MENUS} shadow-xl shadow-black/50`;
