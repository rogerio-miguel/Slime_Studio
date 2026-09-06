// Recorte que o carrossel hero (inicio/CarrosselDestaques.jsx) está exibindo
// AGORA, derivado só do relógio. Módulo puro — sem React, sem imports de
// `../api/` —, mesmo padrão de ./fileiras.js e ./intercalarDestaques.js.
//
// O carrossel mantém o estado da rotação da janela dentro do componente
// (`blocoDaJanela`: um `useState` semeado por `Date.now()` e incrementado por
// um `setInterval` de 10 min). Aqui a janela é RE-derivada do relógio na hora
// da chamada — no mount as duas coincidem (mesma fórmula, mesma semente) e
// podem divergir em no máximo um bloco depois de uma rotação de 10 min. É
// tolerância aceitável: o único consumidor é a exclusão "melhor esforço" em
// paginas/Inicio.jsx que impede os "destaques grandes" de repetir os animes
// que o carrossel mostra — um item a mais ou a menos na borda de uma rotação
// não quebra nada.
//
// `TAMANHO_DA_JANELA` / `INTERVALO_ROTACAO_MS` / `embaralharComSemente` são a
// fonte única e o CarrosselDestaques.jsx os importa de volta — o recorte
// precisa sair bit a bit idêntico dos dois lados.

// Quantos destaques o carrossel mostra de uma vez. O feed "em alta" chega com
// até 50 itens (`perPage: 50` na AniList); em vez de fixar nos 15 primeiros,
// essa é uma JANELA que desliza pelo pool inteiro ao longo do tempo.
export const TAMANHO_DA_JANELA = 15;

// A cada 10 min a janela avança um bloco pelo pool. O bloco vem do relógio
// (`Date.now()`), não de 0: dois reloads dentro da mesma janela de 10 min
// veem o mesmo recorte e não há "drift" entre abas.
export const INTERVALO_ROTACAO_MS = 600000;

// Embaralhamento (Fisher-Yates) com PRNG determinístico (mulberry32) semeado
// por um inteiro — o bloco da janela. A ordem é ESTÁVEL dentro dos 10 min de
// uma janela e só troca junto com a rotação; sem isto o recorte sairia em
// ordem de ranking (#1, #2, #3…), e o usuário quer ordem aparentemente
// aleatória.
export function embaralharComSemente(lista, semente) {
  const arr = [...lista];
  let s = semente >>> 0;
  const rand = () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

// Recorte que o carrossel exibe no instante `agora` — o pool inteiro
// embaralhado com semente no bloco da janela, cortado em `TAMANHO_DA_JANELA`.
// Espelha o `base` de CarrosselDestaques.jsx (mesma fórmula de semente, mesmo
// `slice`).
export function recorteVisivelDoCarrossel(pool, agora = Date.now()) {
  const lista = pool ?? [];
  const tamanho = Math.min(TAMANHO_DA_JANELA, lista.length);
  if (tamanho === 0) return [];
  const bloco = Math.floor(agora / INTERVALO_ROTACAO_MS);
  return embaralharComSemente(lista, bloco).slice(0, tamanho);
}
