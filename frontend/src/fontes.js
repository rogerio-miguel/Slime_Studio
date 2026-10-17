// Nome de exibição de uma fonte a partir da CHAVE de identidade que o backend
// usa (`backend/extractors/base.py::dominio`, mesmo valor de
// `Episodio.site_origem`/`FonteAnime.dominio` e do `dominio` nos resultados de
// busca em fontes). A chave nem sempre traz o TLD — `animefire.io` traz,
// `animesdrive`/`meusanimes` não —; este mapa completa o TLD (a `BASE_URL` de
// cada extrator) só para apresentação. Chave não mapeada passa direto;
// `null`/vazio vira `null` para caber num `.filter(Boolean)`.
const DOMINIO_EXIBICAO = {
  animesdrive: 'animesdrive.cloud',
  meusanimes: 'meusanimes.blog',
};

export function nomeDaFonte(dominio) {
  return dominio ? (DOMINIO_EXIBICAO[dominio] ?? dominio) : null;
}
