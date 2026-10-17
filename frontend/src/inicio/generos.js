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

// Gêneros da página Descobrir, na ordem dos chips: os do mapa acima, menos
// "Hentai" (conteúdo adulto nunca entra). Espelha
// `backend/integrations/registro.py::GENEROS_DE_DESCOBERTA`, que é quem recusa
// qualquer outro valor em `GET /api/animes/descobrir`.
export const GENEROS_DE_DESCOBERTA = Object.keys(GENEROS_PT).filter((g) => g !== 'Hentai');

export function traduzirGenero(g) {
  return GENEROS_PT[g] ?? g;
}
