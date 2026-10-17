// Derivação pura: intercala vários "destaques grandes" na lista de fileiras
// da home. NÃO USADA hoje — `inicio/DestaqueGrande.jsx` virou um banner ÚNICO
// e fixo (pedido explícito do usuário, 2026-09-20), posicionado direto em
// `paginas/Inicio.jsx::fileirasDaHome`, sem passar por este módulo. Mantido
// por completude caso o produto volte a querer vários destaques espalhados.
// Sem React, sem imports de `../api/`: recebe os dois arrays já resolvidos e
// devolve um array NOVO de blocos prontos pra `.map()` no render (nunca muta
// as entradas), mesma disciplina de ./fileiras.js e ./fileirasTematicas.js.
// Cada `fileira` é opaca aqui — só o campo `chave` é lido; o resto (ex.
// `node`) volta intacto em `bloco.fileira`.
//
// Regra de espaçamento: os destaques não vêm todos juntos nem colados no
// início/fim — ficam espalhados ao longo das fileiras, a cada `passo`
// fileiras (arredondado pra cima: com 3 destaques e 9 fileiras, a cada 3).
// Quando há MENOS fileiras que destaques, o espaçamento colapsa (`passo` cai
// a 1, um destaque depois de cada fileira) e o que ainda sobrar entra depois
// da última fileira — nunca antes da primeira.

export function intercalarDestaques(fileiras, destaques) {
  const listaFileiras = fileiras ?? [];
  const listaDestaques = destaques ?? [];

  if (listaDestaques.length === 0) {
    return listaFileiras.map((fileira) => ({ tipo: 'fileira', chave: fileira.chave, fileira }));
  }

  const passo = Math.max(1, Math.ceil(listaFileiras.length / listaDestaques.length));

  const blocos = [];
  let proximoDestaque = 0;
  listaFileiras.forEach((fileira, indice) => {
    blocos.push({ tipo: 'fileira', chave: fileira.chave, fileira });
    const vezDeInserir = (indice + 1) % passo === 0;
    if (vezDeInserir && proximoDestaque < listaDestaques.length) {
      blocos.push({
        tipo: 'destaque',
        chave: `destaque-${proximoDestaque}`,
        destaque: listaDestaques[proximoDestaque],
      });
      proximoDestaque += 1;
    }
  });
  // Sobra: fileiras insuficientes pra encaixar todos os destaques no meio
  // (inclusive o caso de zero fileiras) — o resto vai depois da última.
  while (proximoDestaque < listaDestaques.length) {
    blocos.push({
      tipo: 'destaque',
      chave: `destaque-${proximoDestaque}`,
      destaque: listaDestaques[proximoDestaque],
    });
    proximoDestaque += 1;
  }
  return blocos;
}
