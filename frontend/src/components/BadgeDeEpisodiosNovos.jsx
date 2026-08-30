// Aviso "episódio novo na fonte" sobre o card do anime na galeria. Mesmo
// tratamento visual do título do card (AnimeCard.jsx): texto branco em negrito
// sobre um degradê preto — só que no TOPO do card (o título é embaixo). Sem
// pill: o degradê some para transparente, igual ao do título. `pointer-events-
// none` porque a faixa cobre o terço superior do card e não pode roubar o
// clique do <Link>/<button> por baixo.
//
// A origem já foi resolvida no backend (`GET /api/animes` → `episodios_novos`):
// quantos episódios a FONTE real do anime expõe além da fronteira já capturada,
// sondada em background e servida de cache — o `status_lancamento` da AniList é
// só o filtro (só anime EM_LANCAMENTO). Aqui a única regra é "número positivo →
// mostra"; o texto não expõe a quantidade (decisão de produto), só sinaliza a
// novidade. `quantidade` ausente (card do feed "em alta", que não carrega esse
// campo), zero, `null` ou negativa não renderiza nada. Usada só na galeria — a
// página do anime não mostra este aviso.
export default function BadgeDeEpisodiosNovos({ quantidade }) {
  if (!quantidade || quantidade < 1) return null;

  const texto =
    quantidade > 1 ? 'Novos episódios disponíveis' : 'Novo episódio disponível';

  return (
    <span className="pointer-events-none absolute inset-x-0 top-0 z-10 rounded-t-xl bg-gradient-to-b from-black/90 via-black/50 to-transparent px-4 pb-6 pt-3 text-sm font-semibold leading-snug text-white">
      {texto}
    </span>
  );
}
