// Miniaturas e glows não precisam da imagem `original` do TMDB (1920×1080 e
// ~8 MB decodificados): o backend guarda o banner em `original` pro hero de
// tela cheia, e usar essa mesma URL num card de ~480px pesava na decodificação e
// no download ao rolar as fileiras. `w780` existe pra backdrop E pra poster, e
// cobre cards com folga (a ~1,6x do tamanho exibido numa tela 1x). URL de outra
// origem passa intacta.
export function reduzirImagemTmdb(url) {
  if (!url) return url;
  return url.replace(/^(https:\/\/image\.tmdb\.org\/t\/p\/)original(\/)/, '$1w780$2');
}
