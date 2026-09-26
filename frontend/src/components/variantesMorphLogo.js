// Comparação A/B do morph letras→ícone (pedido do usuário, 2026-09-26: "vou
// testar uma por uma") — trocar `TECNICA_MORPH_ATIVA` aqui pra alternar
// entre as técnicas testadas, sem apagar nenhuma implementação. Consumido
// por `LetraViajante.jsx` (mix-blend-mode) e `useTransicaoParaIcone.js`
// (squash-and-stretch / morph em 2 estágios via blob / rastro).
//
// Técnicas se combinam concatenando os nomes com `+` (ex.:
// 'esticar-fusao+rastro-gosma', pedido do usuário 2026-09-26: "junta esse
// [rastro-gosma] mais o esticar-fusao") — os `USA_*` abaixo checam
// substring, não igualdade exata, então uma técnica nova só precisa
// declarar sua própria constante `USA_X` e nunca precisa saber se está
// sozinha ou combinada com outra.
//
// 'esticar-fusao': squash-and-stretch (a letra estica/comprime como gosma
//   no meio do trajeto, eixo = direção do movimento) + `mix-blend-mode:
//   lighten` nas letras (fusão visual — quando 2+ convergem pro mesmo
//   destino, a cor neon soma em vez de uma tampar a outra). Testado ao vivo
//   2026-09-26, usuário: "ficou um pouco melhor que antes".
//
// 'blob': cada letra morfa PRIMEIRO (metade do trajeto) pra uma forma de
//   gota amorfa única, reaproveitada por TODAS as letras (ponto simbólico:
//   todo mundo "derrete" no mesmo poço antes de virar ícone) — só na
//   segunda metade do trajeto morfa da gota pra peça final do ícone.
//   Testado ao vivo 2026-09-26, usuário: "esse ficou bom".
//
// 'spring': mesma forma de sempre (morph direto letra↔ícone, sem blob) —
//   só troca a curva de easing do TRAJETO (posição/tamanho) de uma
//   desaceleração reta pra uma com overshoot ("easeOutBack": a peça passa
//   um pouco do destino e assenta de volta). Ver `EASING_TRAVESSIA` em
//   `useTransicaoParaIcone.js`. Testado ao vivo 2026-09-26 — BUG conhecido,
//   aceito como não-bloqueante pelo usuário ("não me chamou muita
//   atenção"): o overshoot empurra a peça um pouco além do slot do ícone,
//   invadindo a borda do "SLIME" (os dois ficam colados, sem folga — o
//   overshoot não tem pra onde ir sem cruzar o texto vizinho). Não corrigido
//   nesta rodada; retomar se o usuário voltar a esta técnica.
//
// 'rastro-gosma': mesma forma/trajeto retos de sempre (sem blob, sem
//   overshoot) — acrescenta um rastro atrás da letra em movimento (3
//   "fantasmas" via `drop-shadow` empilhados, opacidade decrescente, mais
//   `blur` geral) na direção OPOSTA ao trajeto, com intensidade seguindo o
//   mesmo perfil de "velocidade" do squash-and-stretch (pico no meio do
//   trajeto, zero parado). Testado ao vivo 2026-09-26 sozinho, usuário:
//   "não gostei muito, mas achei legal"; testado combinado com
//   'esticar-fusao' na sequência — usuário pediu pra voltar só pro 'blob'
//   (2026-09-26), mas nenhuma das duas foi apagada.
//
// 'encontro': NÃO é uma técnica de forma — é um ajuste de TIMING que só faz
//   sentido em cima do 'blob' (por isso ativado como 'blob+encontro' abaixo,
//   nunca sozinho). Ideia do usuário (2026-09-26, "uma ideia não muito bem
//   desenvolvida"): em vez das 6 letras chegarem na gota em cascata (cada
//   uma 30ms depois da anterior, `atrasoLetraMs` em `LogoSlimeStudio.jsx`),
//   todas chegam ao MESMO TEMPO — como a gota de todas tem a MESMA forma,
//   posição e tamanho (`PATH_BLOB_TRANSICIONAL`, reaproveitado; a posição
//   de destino já era compartilhada por todas antes até disso, só a FORMA
//   diferia por letra), chegar junto lê como um "encontro" formando um
//   círculo só, que depois se abre pras 2 formas finais do ícone (lâmina/
//   base). Testado ao vivo 2026-09-26 (junto com `VOLTA_ANIMADA`), usuário:
//   "está ficando bom".
//
// 'giro-horario' (APOSENTADA, não só desativada): rotação pura somada por
//   cima de qualquer técnica ativa, só na viagem de VOLTA (ícone→letra).
//   Pedido do usuário (2026-09-26): a ida já "lê" como sentido horário (o
//   clap de abertura gira nesse sentido); a volta devia CONTINUAR no mesmo
//   sentido em vez de ficar simétrica-mas-oposta. Testado ao vivo, usuário:
//   "não ficou bom" — desativado no mesmo dia. Mais tarde no mesmo dia a
//   volta deixou de VIAJAR de vez (crossfade simples no lugar do desmonte
//   em letras, ver `LogoSlimeStudio.jsx`/`useTransicaoParaIcone.js`) — a
//   premissa desta técnica (girar a letra DURANTE a viagem de volta) ficou
//   estruturalmente impossível, não só desligada por flag.
//   `USA_GIRO_HORARIO` continua exportada só como registro histórico; nada
//   mais no código a lê.
export const TECNICA_MORPH_ATIVA = 'blob+encontro';

export const USA_ESTICAR_FUSAO = TECNICA_MORPH_ATIVA.includes('esticar-fusao');
export const USA_RASTRO_GOSMA = TECNICA_MORPH_ATIVA.includes('rastro-gosma');
export const USA_BLOB = TECNICA_MORPH_ATIVA.includes('blob');
export const USA_SPRING = TECNICA_MORPH_ATIVA.includes('spring');
export const USA_ENCONTRO = TECNICA_MORPH_ATIVA.includes('encontro');
export const USA_GIRO_HORARIO = TECNICA_MORPH_ATIVA.includes('giro-horario');

// Independente da técnica de morph acima — controla só se a VOLTA
// (ícone→nome) anima ou pula direto pro estado final (`useVoltandoInstantaneo`
// em `LogoSlimeStudio.jsx`). Ficou temporariamente travada em instantânea
// (pedido do usuário, 2026-09-24: "por agora, sem animação nenhuma na
// volta" — a coreografia de então não convencia). Reativada 2026-09-26
// (pedido do usuário: "o ícone fechar a lâmina, se transformar no círculo,
// depois no nome") — a sequência de base (ícone encolhe → letras viajam de
// volta) já estava pronta, só desligada; o "vira círculo" já sai de graça
// do `blob+encontro` acima (mesmo morph, sentido invertido). Trocar aqui
// se a versão animada não convencer nesta rodada.
export const VOLTA_ANIMADA = true;
