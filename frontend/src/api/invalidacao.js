// Pub/sub mínimo por chave de recurso — não é um cache (não guarda dado, só
// notifica). Existe pra desacoplar "quem escreveu" de "quem precisa reler":
// uma mutação chama `invalidar(chave)` assim que sua Promise resolve, e todo
// `useRecurso` (useRecurso.js) assinando aquela chave e MONTADO NESTE
// MOMENTO recarrega sozinho — sem depender do componente que fez a escrita
// ainda existir (cobre o caso de PaginaDoPlayer.jsx salvar/liberar episódio
// no unmount e só a PaginaDoAnime seguinte precisar saber disso). Sem
// assinante pra uma chave, a invalidação é descartada sem custo: a próxima
// página que montar já busca dado fresco por conta própria, como sempre fez.
const escutas = new Map(); // chave -> Set<() => void>

export function invalidar(chave) {
  escutas.get(chave)?.forEach((fn) => fn());
}

export function escutar(chave, fn) {
  if (!escutas.has(chave)) escutas.set(chave, new Set());
  escutas.get(chave).add(fn);
  return () => escutas.get(chave)?.delete(fn);
}
