import { Check } from 'lucide-react';
import BrilhoDaCapa from '../components/BrilhoDaCapa.jsx';
import IconeSalvar from '../components/IconeSalvar.jsx';

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
// Ação de salvar só renderiza com `aoSalvar` (a ausência do handler é o sinal —
// sem prop booleana). O botão de salvar é o ícone de fita (`IconeSalvar`, mesmo
// desenho do Instagram), sobreposto no canto superior esquerdo da capa, DENTRO
// da própria div da capa (não como irmão dela lá fora). SEMPRE visível (não
// escondido até hover): salvar é a ação primária deste card e precisa ficar
// visível de cara.
//
// `modoSelecao`/`selecionado`/`aoAlternarSelecao` (só `paginas/Galeria.jsx`):
// mesmo "Gerenciar" do AnimeCard (ver nota lá) — com `modoSelecao` o card
// ganha um botão `absolute inset-0` de alternância (`aria-pressed`), o círculo
// de seleção no canto superior direito e o anel neon quando selecionado. É a
// única exceção ao "inerte de propósito" acima: o botão só existe nesse modo e
// tem ação de verdade.
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
// pedido do usuário): glow ambiente da capa atrás do pôster (`BrilhoDaCapa`,
// ver components/AnimeCard.jsx), pôster com `rounded-2xl`. Sem indicador de
// foco de teclado por decisão explícita do usuário (2026-09-13, ver
// components/AnimeCard.jsx). Grupo NOMEADO `group/card` (a fileira horizontal
// tem `group/fileira` próprio pras setas).
//
// Título ABAIXO do pôster, em fluxo normal — não mais sobre um degradê por
// cima da imagem (rationale completo do porquê em components/AnimeCard.jsx,
// mesma correção: o degradê deixava uma lasca sem escurecer no canto
// arredondado em alguns motores gráficos). O botão de salvar e o círculo de
// seleção (`absolute`) moram DENTRO da div da capa (`relative aspect-[2/3]
// overflow-hidden`): a posição é exata por construção e qualquer transbordo
// sai recortado de graça.

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

export default function CartaoDeEstreia({
  item,
  salvo,
  salvando,
  aoSalvar,
  // `true` quando quem chama já mostra a data por fora (marca do dia em
  // `inicio/SlotDoDiaDeEstreia.jsx`) — evita repetir a mesma data embaixo do título.
  semTextoDeData = false,
  modoSelecao = false,
  selecionado = false,
  aoAlternarSelecao,
}) {
  const titulo =
    item.titulo || item.titulo_romaji || item.titulo_ingles || 'Sem título';
  const capa = item.capa_url ?? item.capa_path ?? null;

  return (
    <div className="group/card relative">
      <div className="relative flex w-full flex-col gap-2">
        {capa && <BrilhoDaCapa capa={capa} />}
        <div
          className={`relative aspect-[2/3] w-full overflow-hidden rounded-2xl bg-surface${
            modoSelecao && selecionado ? ' ring-[3px] ring-neon' : ''
          }`}
        >
          {capa && (
            <img
              src={capa}
              alt=""
              loading="lazy"
              className="absolute inset-0 h-full w-full object-cover"
            />
          )}
          {/* O botão de salvar mora AQUI DENTRO (não como irmão do pôster): a
              posição é exata e o transbordo fica recortado. */}
          {aoSalvar &&
            (salvo ? (
              <button
                type="button"
                onClick={aoSalvar}
                disabled={salvando}
                aria-label={`Remover ${titulo} do catálogo`}
                className="absolute left-2 top-2 z-10 p-1 text-white outline-none transition duration-200 ease-out hover:brightness-90 hover:scale-110 motion-reduce:transition-none cursor-pointer disabled:opacity-50"
              >
                <IconeSalvar preenchido />
              </button>
            ) : (
              <button
                type="button"
                onClick={aoSalvar}
                disabled={salvando}
                aria-label={`Salvar ${titulo} no catálogo`}
                className="absolute left-2 top-2 z-10 p-1 text-white outline-none transition duration-200 ease-out hover:brightness-90 hover:scale-110 motion-reduce:transition-none cursor-pointer disabled:opacity-50"
              >
                <IconeSalvar />
              </button>
            ))}
          {modoSelecao && (
            <span
              aria-hidden="true"
              className={`absolute right-2 top-2 z-10 flex h-7 w-7 items-center justify-center rounded-full border-2 transition-colors duration-200 motion-reduce:transition-none ${
                selecionado ? 'border-neon bg-neon text-white' : 'border-white bg-black/40 text-transparent'
              }`}
            >
              <Check strokeWidth={4} className="h-4 w-4" />
            </span>
          )}
        </div>
        <div className="relative flex flex-col gap-1">
          <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-white transition-colors lg:text-base">
            {titulo}
          </h3>
          {!semTextoDeData && (
            <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
              {textoDeEstreia(item)}
            </p>
          )}
        </div>
      </div>
      {modoSelecao && (
        <button
          type="button"
          onClick={aoAlternarSelecao}
          aria-pressed={selecionado}
          aria-label={`${titulo}, ${textoDeEstreia(item)}`}
          className="absolute inset-0 cursor-pointer outline-none"
        />
      )}
    </div>
  );
}
