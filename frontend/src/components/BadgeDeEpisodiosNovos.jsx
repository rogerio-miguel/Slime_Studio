// Aviso "episódio novo na fonte" logo ACIMA do título do card na galeria —
// mesmo tratamento visual da linha de estreia de `inicio/CartaoDeEstreia.jsx`
// (texto curto em caixa alta, neon, kicker sobre o título). Renderizado dentro
// do fluxo flex do card (não mais como faixa sobreposta no topo), então não
// precisa de `pointer-events-none` nem de degradê próprio.
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
    <p className="text-xs font-semibold uppercase tracking-wide text-neon">
      {texto}
    </p>
  );
}
