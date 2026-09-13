import BotaoRemoverDoCatalogo from '../components/BotaoRemoverDoCatalogo.jsx';

// Ícone de "salvar" (fita de marcador) — cópia exata do glifo do botão
// "Salvar" do Instagram (mesmo `viewBox`/`points`, confirmado direto no SVG
// renderizado do próprio site, não só no HTML colado). Checado contra
// `lucide-react` (já instalado, ver `player/Icones.jsx`) antes de desenhar à
// mão — nenhum ícone de lá bate: o `Bookmark` de lá tem cantos arredondados
// no topo e um entalhe curvo embaixo (glifo "livro"), não o retângulo de
// cantos retos + V reto do Instagram. Sem equivalente pronto, mão na massa é
// o passo certo da Escada de Minimalismo (CLAUDE.md §4, passo 6).
// `preenchido` alterna entre contorno (ainda não salvo) e sólido (já no
// catálogo), igual ao toggle de lá.
// `strokeWidth="2.5"` (mais grosso que o "2" do Instagram, pedido explícito
// do usuário): no card deles o ícone senta numa barra de ações espaçosa; no
// nosso ele é um selo pequeno no canto da capa, então precisa de mais peso
// visual pra não sumir. `h-8 w-8` (32px, maior que o `width="24" height="24"`
// de lá pelo mesmo motivo — ajustado depois de ver renderizado).
function IconeSalvar({ preenchido = false }) {
  return (
    <svg viewBox="0 0 24 24" className="h-8 w-8" role="img" aria-hidden="true">
      <polygon
        points="20 21 12 13.44 4 21 4 3 20 3 20 21"
        fill={preenchido ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// Card de anime que ainda NÃO estreou. Dois usos:
//   1. Fileira "Próximas estreias" da Home (paginas/Inicio.jsx) — item do feed
//      `GET /api/animes/proxima-temporada`, com `aoSalvar` pra materializar o
//      anime no catálogo local (`POST /api/admin/animes`, get-or-create por
//      slug) como bookmark/watchlist.
//   2. Cards de anime não-estreado no catálogo (paginas/Galeria.jsx) — já
//      materializado; a Galeria passa `aoRemover` e nunca `aoSalvar`.
// A Galeria reusa ESTE card em vez de AnimeCard justamente porque o anime ainda
// não estreou: AnimeCard navega pra `/anime/:id`, que aqui levaria a uma página
// sem episódios e com resolução de fonte fadada a falhar. Este card é inerte de
// propósito — sem `<Link>`/`onClick`/`tabIndex`/`role` (card focável sem ação é
// armadilha de teclado). Quando o anime estrear de verdade e aparecer num site,
// a página dele passa a resolver fonte normalmente.
//
// Ação de salvar só renderiza com `aoSalvar`; o botão de remover só com
// `aoRemover` — NUNCA os dois juntos (mesma posição, se coexistissem um
// cobriria o outro). A ausência do handler é o sinal — sem prop booleana. O
// botão de salvar é o ícone de fita (`IconeSalvar`, mesmo desenho do
// Instagram), sobreposto no canto superior direito da capa — DENTRO da
// própria div da capa (não como irmão dela lá fora, ver nota mais abaixo).
// SEMPRE visível (não escondido até hover, ao contrário de
// `BotaoRemoverDoCatalogo`): salvar é a ação primária deste card e precisa
// ficar visível de cara.
//
// `aoSalvar` é um TOGGLE, não só "salvar": com `salvo=false` o clique
// materializa (fita em contorno); com `salvo=true` o MESMO clique remove essa
// temporada do catálogo (fita preenchida vira o alvo — `aria-label` já muda
// pra "Remover"). Quem decide qual das duas coisas fazer é o CHAMADOR
// (`paginas/Inicio.jsx::alternarEstreiaSalva`), que já sabe o estado atual —
// este componente só liga o clique ao callback e troca a aparência conforme
// `salvo`, sem lógica de negócio própria.
//
// Risco conhecido (não corrigir agora): um bookmark recém-salvo pode nascer sem
// nenhum sinal de data (`estreia_em`/`proximo_ep_em`/`ano` todos ausentes — o
// enriquecimento é best-effort/assíncrono) e cair no rótulo genérico "Estreia
// em breve" até o próximo carregamento. Assim que o warm de lançamento roda,
// `estreia_em` (data completa da AniList) ou pelo menos `ano` passam a existir.
//
// Mesma mecânica visual de hover do AnimeCard — sem escala (removida a
// pedido do usuário): hover de mouse → `hover:bg-surface-hover` sobre
// `p-3 -m-3` (o padding some o conteúdo do lugar, a margem negativa cancela;
// só revela a caixa de fundo quando o hover pinta ela), cobrindo o card
// INTEIRO (pôster + legenda), não só a imagem. Sem indicador de foco de
// teclado por decisão explícita do usuário (2026-09-13, ver
// components/AnimeCard.jsx) — havia um anel/borda neon aqui antes, removido
// junto com o resto do sistema. Grupo NOMEADO `group/card` (a fileira
// horizontal tem `group/fileira` próprio pras setas).
//
// Título ABAIXO do pôster, em fluxo normal — não mais sobre um degradê por
// cima da imagem (rationale completo do porquê em components/AnimeCard.jsx,
// mesma correção: o degradê deixava uma lasca sem escurecer no canto
// arredondado em alguns motores gráficos). O botão de salvar e
// `BotaoRemoverDoCatalogo` (ambos `absolute right-2 top-2`, nunca os dois ao
// mesmo tempo — ver nota acima) moram DENTRO da div da capa (`relative
// aspect-[2/3] overflow-hidden`), não como irmãos dela no wrapper `p-3 -m-3`
// de fora: esse wrapper existe só pra pintar o fundo do hover (ver bloco
// abaixo) e NÃO é uma referência de posição confiável — o padding/margem
// negativa que "cancela" só funciona no eixo horizontal (margem vertical
// colapsa com o pai, que não tem padding/borda pra bloquear isso), então um
// `top-2` ancorado nele desalinhava do topo real do pôster. Ancorando na
// própria div da capa, a posição é exata por construção e qualquer transbordo
// sai recortado (`overflow-hidden`) de graça.

// Instâncias únicas de módulo — recriar `Intl.*` por render é caro.
const fmtDia = new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'long' });
const fmtDiaAno = new Intl.DateTimeFormat('pt-BR', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

// Linha de estreia derivada do item — feed `GET /api/animes/proxima-temporada`
// (`AnimeEmAltaSaida`) na Home, ou `GET /api/animes` (`AnimeSaida`) na Galeria.
// Ordem importa — para no primeiro match.
//   1. `proximo_ep_em` no futuro: para NOT_YET_RELEASED é o ar do episódio 1 =
//      data de estreia exata (com ano só quando difere do atual).
//   2. já em lançamento com próximo ep datado: "Novo episódio ..." (raro nesta
//      fileira, mas o feed pode trazer título que estreou adiantado).
//   3. `estreia_em` no futuro (`AnimeSaida`, catálogo): data completa da AniList
//      (`startDate`), disponível ~semanas antes de `proximo_ep_em` ser agendado.
//   4. só `ano_estreia`/`ano` (Kitsu degradado, ou AniList sem grade ainda): o ano.
//   5. nada aproveitável: rótulo genérico.
function textoDeEstreia(item) {
  const epEm = item.proximo_ep_em;
  const data = epEm ? new Date(epEm) : null;
  const futuro = data && data > new Date();

  if (futuro && item.status_lancamento !== 'em_lancamento') {
    const mesmoAno = data.getFullYear() === new Date().getFullYear();
    return `Estreia ${(mesmoAno ? fmtDia : fmtDiaAno).format(data)}`;
  }
  if (futuro) {
    const mesmoAno = data.getFullYear() === new Date().getFullYear();
    return `Novo episódio ${(mesmoAno ? fmtDia : fmtDiaAno).format(data)}`;
  }
  // `estreia_em`: string ISO `YYYY-MM-DD` de `GET /api/animes`. Parse com sufixo
  // `T00:00:00` pra cair na meia-noite LOCAL, não UTC (`new Date('2026-01-15')`
  // é UTC e em UTC-3 mostraria 14/01).
  if (item.estreia_em) {
    const estreia = new Date(`${item.estreia_em}T00:00:00`);
    if (!Number.isNaN(estreia.getTime()) && estreia > new Date()) {
      const mesmoAno = estreia.getFullYear() === new Date().getFullYear();
      return `Estreia ${(mesmoAno ? fmtDia : fmtDiaAno).format(estreia)}`;
    }
  }
  const ano = item.ano_estreia ?? item.ano;
  if (ano) return `Estreia em ${ano}`;
  return 'Estreia em breve';
}

export default function CartaoDeEstreia({ item, salvo, salvando, aoSalvar, aoRemover }) {
  const titulo =
    item.titulo || item.titulo_romaji || item.titulo_ingles || 'Sem título';
  const capa = item.capa_url ?? item.capa_path ?? null;

  return (
    <div className="group/card relative">
      <div className="relative flex w-full flex-col gap-2 rounded-2xl p-3 -m-3 transition-colors duration-300 ease-out hover:bg-surface-hover motion-reduce:transition-none">
        <div className="relative aspect-[2/3] w-full overflow-hidden rounded-2xl bg-surface">
          {capa && (
            <img
              src={capa}
              alt=""
              loading="lazy"
              className="absolute inset-0 h-full w-full object-cover"
            />
          )}
          {/* Salvar/remover moram AQUI DENTRO (não como irmãos do pôster lá
              embaixo em `A`) — ver nota de posição no bloco de comentário do
              topo do arquivo: o wrapper `p-3 -m-3` NÃO é uma referência de
              posição confiável (colapso de margem verticais entre ele e o
              pai), então ancorar `top-2`/`right-2` nele deixava o ícone
              flutuando fora da capa. Aqui dentro o pai É a própria capa
              (`relative overflow-hidden`), então a posição é exata e
              qualquer transbordo fica recortado de graça. */}
          {aoSalvar &&
            (salvo ? (
              <button
                type="button"
                onClick={aoSalvar}
                disabled={salvando}
                aria-label={`Remover ${titulo} do catálogo`}
                className="absolute right-2 top-2 z-10 p-1 text-white outline-none transition duration-200 ease-out hover:brightness-90 hover:scale-110 motion-reduce:transition-none cursor-pointer disabled:opacity-50"
              >
                <IconeSalvar preenchido />
              </button>
            ) : (
              <button
                type="button"
                onClick={aoSalvar}
                disabled={salvando}
                aria-label={`Salvar ${titulo} no catálogo`}
                className="absolute right-2 top-2 z-10 p-1 text-white outline-none transition duration-200 ease-out hover:brightness-90 hover:scale-110 motion-reduce:transition-none cursor-pointer disabled:opacity-50"
              >
                <IconeSalvar />
              </button>
            ))}
          {aoRemover && <BotaoRemoverDoCatalogo titulo={titulo} aoRemover={aoRemover} />}
        </div>
        <div className="relative flex flex-col gap-1">
          <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-white transition-colors lg:text-base">
            {titulo}
          </h3>
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
            {textoDeEstreia(item)}
          </p>
        </div>
      </div>
    </div>
  );
}
