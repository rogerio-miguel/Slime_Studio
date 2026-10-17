// Texto do aviso "episódio novo na fonte" — devolve só o TEXTO cru (não um
// elemento pronto): quem chama (`components/AnimeCard.jsx`) decide onde
// compor. Uso principal é inline, na MESMA linha da tag "Tn EP.n" ("T1 EP.24
// - Novo episódio disponível", pedido explícito do usuário); sem a tag de
// temporada (anime nunca refrescado), o chamador usa como linha própria —
// nunca esconder a novidade só porque falta o outro dado.
//
// A origem já foi resolvida no backend (`GET /api/animes` → `episodios_novos`):
// quantos episódios a FONTE real do anime expõe além da fronteira já capturada,
// sondada em background e servida de cache — o `status_lancamento` da AniList é
// só o filtro (só anime EM_LANCAMENTO). Aqui a única regra é "número positivo →
// mostra"; o texto não expõe a quantidade (decisão de produto), só sinaliza a
// novidade. `quantidade` ausente (card do feed "em alta", que não carrega esse
// campo), zero, `null` ou negativa devolve `null`. Usada só na galeria — a
// página do anime não mostra este aviso.
export default function textoEpisodiosNovos(quantidade) {
  if (!quantidade || quantidade < 1) return null;
  return quantidade > 1 ? 'Novos eps' : 'Novo ep';
}
