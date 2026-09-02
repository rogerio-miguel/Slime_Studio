// Tradução PT-BR do conjunto fechado de gêneros da AniList. Chave fora do mapa
// (nome novo do provedor) cai no fallback `?? g` de quem consome — nunca some.
export const GENEROS_PT = {
  Action: 'Ação',
  Adventure: 'Aventura',
  Comedy: 'Comédia',
  Drama: 'Drama',
  Ecchi: 'Ecchi',
  Fantasy: 'Fantasia',
  Hentai: 'Hentai',
  Horror: 'Terror',
  'Mahou Shoujo': 'Mahou shoujo',
  Mecha: 'Mecha',
  Music: 'Musical',
  Mystery: 'Mistério',
  Psychological: 'Psicológico',
  Romance: 'Romance',
  'Sci-Fi': 'Ficção científica',
  'Slice of Life': 'Slice of life',
  Sports: 'Esporte',
  Supernatural: 'Sobrenatural',
  Thriller: 'Suspense',
};

export function traduzirGenero(g) {
  return GENEROS_PT[g] ?? g;
}
