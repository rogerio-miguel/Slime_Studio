// Paths extraídos da Inter-Bold (a fonte do sistema mais próxima do stack
// sans padrão do Tailwind, mesmo peso do `font-bold` usado em STUDIO) via
// opentype.js — script descartável, não é dependência do projeto. Todos
// normalizados pro viewBox 0 0 24 24, MESMO sistema de coordenadas dos
// paths do `IconeClaquete` (LogoSlimeStudio.jsx), condição pra `flubber`
// interpolar sem reescalar nada no meio do morph.
//
// Todas as 6 letras de "STUDIO" viajam/mudam de forma (pedido do usuário,
// 2026-09-26: "fazer todas se misturar para formar o ícone" em vez de só
// 2 viajarem e as outras 4 ficarem paradas) — mas só 2 são "principais",
// cada uma com um pedaço do ícone só seu: T vira a LÂMINA, O vira a BASE
// (ver `LETRAS_VIAJANTES` em `LogoSlimeStudio.jsx`). As outras 4 se
// MISTURAM num dos dois destinos (S/U convergem pra lâmina junto com o T;
// D/I convergem pra base junto com o O) — várias letras terminando na
// MESMA forma final ao mesmo tempo é o que cria a ilusão de "juntar todo
// mundo pra formar o ícone", sem cada uma precisar de um pedaço próprio.
//
// O e D (a "barriga" fechada) têm furo (contracontorno da letra) — path
// fica com 2 subcaminhos. `flubber.interpolate` não entende hole de
// verdade, trata como um caminho só: risco visual aceito (pedido do
// usuário, 2026-09-25) de a transição passar por uma forma "com fenda" no
// meio do morph. S/U/T não têm hole (contorno único).
export const PATH_LETRA_O =
  'M8.14 17.93Q5.84 17.93 3.99 16.88Q2.14 15.82 1.07 13.82Q0 11.81 0 8.98Q0 6.13 1.07 4.12Q2.14 2.11 3.99 1.05Q5.84 0 8.14 0Q10.46 0 12.30 1.05Q14.14 2.11 15.22 4.12Q16.29 6.13 16.29 8.98Q16.29 11.82 15.22 13.82Q14.14 15.82 12.30 16.88Q10.46 17.93 8.14 17.93Z M8.14 14.75Q10.18 14.75 11.42 13.27Q12.66 11.79 12.66 8.98Q12.66 6.15 11.42 4.66Q10.18 3.18 8.14 3.18Q6.12 3.18 4.88 4.67Q3.63 6.16 3.63 8.98Q3.63 11.78 4.88 13.27Q6.12 14.75 8.14 14.75Z';

export const PATH_LETRA_I = 'M0 0L3.57 0L3.57 17.46L0 17.46Z';

export const PATH_LETRA_S =
  'M6.98 17.95L6.98 17.95Q3.83 17.95 1.95 16.51Q0.07 15.06 0 12.28L0 12.28L3.48 12.28Q3.57 13.61 4.54 14.27Q5.51 14.93 6.95 14.93L6.95 14.93Q8.38 14.93 9.25 14.31Q10.13 13.7 10.13 12.7L10.13 12.7Q10.13 11.8 9.33 11.32Q8.54 10.84 7.11 10.49L7.11 10.49L5.19 10.01Q2.98 9.47 1.72 8.31Q0.47 7.16 0.47 5.26L0.47 5.26Q0.47 3.68 1.32 2.5Q2.17 1.31 3.65 0.66Q5.13 0 7.03 0L7.03 0Q8.96 0 10.41 0.66Q11.85 1.32 12.66 2.5Q13.46 3.68 13.49 5.21L13.49 5.21L10.03 5.21Q9.94 4.16 9.13 3.59Q8.33 3.01 7 3.01L7 3.01Q5.63 3.01 4.88 3.58Q4.14 4.15 4.14 5.03L4.14 5.03Q4.14 6 4.97 6.48Q5.81 6.96 6.93 7.23L6.93 7.23L8.51 7.62Q9.97 7.96 11.16 8.6Q12.34 9.23 13.03 10.25Q13.72 11.26 13.72 12.73L13.72 12.73Q13.72 15.11 11.95 16.53Q10.17 17.95 6.98 17.95';

export const PATH_LETRA_U =
  'M7.21 17.71L7.21 17.71Q5.03 17.71 3.41 16.91Q1.79 16.11 0.9 14.68Q0 13.24 0 11.33L0 11.33L0 0L3.57 0L3.57 11.04Q3.57 12.56 4.56 13.55Q5.55 14.54 7.21 14.54L7.21 14.54Q8.85 14.54 9.84 13.55Q10.83 12.56 10.83 11.04L10.83 11.04L10.83 0L14.41 0L14.41 11.33Q14.41 13.24 13.51 14.68Q12.6 16.11 10.98 16.91Q9.36 17.71 7.21 17.71';

export const PATH_LETRA_D =
  'M6.14 17.46L6.14 17.46L0 17.46L0 0L6.2 0Q8.82 0 10.72 1.05Q12.61 2.1 13.63 4.05Q14.65 6 14.65 8.72L14.65 8.72Q14.65 11.45 13.63 13.41Q12.61 15.36 10.7 16.41Q8.79 17.46 6.14 17.46M3.57 3.08L3.57 14.38L5.96 14.38Q8.48 14.38 9.79 13.02Q11.09 11.66 11.09 8.72L11.09 8.72Q11.09 5.79 9.79 4.44Q8.5 3.08 5.99 3.08L5.99 3.08L3.57 3.08';

// T inteiro (barra+haste), contorno FECHADO ÚNICO extraído direto do glifo
// (8 vértices retos, T é reto/sans sem curva) — mesma extração via
// opentype.js/Inter-Bold, mesmo viewBox 0 0 24 24, mesma normalização
// (bbox mínimo em 0,0) que O. Vira a lâmina do ícone sem split (pedido do
// usuário, 2026-09-26: "dá pra fazer isso com o T inteiro, sem partir em
// dois?") — `flubber` interpola topologias diferentes sem exigir
// correspondência de forma (mesmo risco já aceito no O com furo, ver
// `PATH_LETRA_O` acima): a barra não tem alvo próprio, ela é absorvida/
// torcida junto com a haste até formar o paralelogramo da lâmina no meio
// do voo — só os extremos (T parado, lâmina final) ficam nítidos.
export const PATH_LETRA_T =
  'M5.34 2.97L0 2.97L0 0L14.26 0L14.26 2.97L8.93 2.97L8.93 17.46L5.34 17.46Z';

// Bounding box de cada letra DENTRO do viewBox 0 0 24 24 (mesmos números
// que saíram do script de extração) — o `d` só ocupa esse cantinho do
// viewBox, o resto é margem vazia. `useTransicaoParaIcone.js` usa isso pra
// escalar pelo TAMANHO REAL da tinta da letra, não pelo viewBox inteiro —
// sem isso a letra rendia bem menor que o texto vizinho (S/T/U/D), porque
// a conta de escala tratava a margem vazia como se fosse parte da letra.
export const BBOX_LETRA_O = { width: 16.29, height: 17.93 };
export const BBOX_LETRA_I = { width: 3.57, height: 17.46 };
export const BBOX_LETRA_T = { width: 14.26, height: 17.46 };
export const BBOX_LETRA_S = { width: 13.72, height: 17.95 };
export const BBOX_LETRA_U = { width: 14.41, height: 17.71 };
export const BBOX_LETRA_D = { width: 14.65, height: 17.46 };

// Mesmos `d` do `IconeClaquete` (base + lâmina), copiados aqui pra servir
// de destino do morph — O vira a caixa da base (ambos formas fechadas
// arredondadas), T vira a lâmina.
export const PATH_ICONE_BASE = 'M3 11h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z';
export const PATH_ICONE_LAMINA =
  'M20.2 6 3 11l-.9-2.4c-.3-1.1.3-2.2 1.3-2.5l13.5-4c1.1-.3 2.2.3 2.5 1.3z';

// Gota amorfa única, reaproveitada por TODAS as letras na técnica 'blob' de
// `variantesMorphLogo.js` — desenhada à mão (não extraída de fonte), só
// precisa parecer orgânica e caber numa escala parecida com as letras
// (bbox ~14×16, ancorada perto de 0,0, mesmo critério das letras acima).
// Mesma gota pra todo mundo é proposital: reforça a ilusão de "derreter no
// mesmo poço" antes de reformar como ícone.
export const PATH_BLOB_TRANSICIONAL =
  'M8 1C12.5 1 15.5 4.5 15 9C14.6 12.8 12.7 17 8 17C3.5 17 1 13 1.3 8.7C1.6 4.5 4 1 8 1Z';
