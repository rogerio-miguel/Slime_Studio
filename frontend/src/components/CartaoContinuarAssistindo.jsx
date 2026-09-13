import {
  CartaoDeEpisodio,
  FaixaDeConteudo,
  IndicadorDePlay,
  MiniaturaDoEpisodio,
  RotuloEpisodio,
} from './LinhaDeEpisodio.jsx';

// Item da prateleira "Continuar assistindo" (paginas/Inicio.jsx). Não é uma
// reimplementação visual — É o `CartaoDeEpisodio` em modo grade, a mesma peça
// que `LinhaDeEpisodio.jsx` usa no ramo `episodio.status === 'pronto'` na
// grade de `PaginaDoAnime.jsx` (importado daquele arquivo, não copiado):
// tamanho (aspect-ratio 16/9), sombra (`SOMBRA_SLIDE_ATIVO`), hover/escala e
// borda neon vêm de graça por serem o MESMO componente, não reimplementados
// (pedido do usuário após a primeira tentativa, que reimplementava esse CSS à
// mão e não batia o tamanho do card real).
//
// Diferenças de conteúdo em relação ao ramo `pronto`: esta prateleira cruza
// vários animes na mesma fileira — ao contrário da grade de episódios de UM
// anime só em `PaginaDoAnime.jsx` — então o `rotulo` da `FaixaDeConteudo`
// abre com o TÍTULO DO ANIME antes do `RotuloEpisodio` ("EP.N - Título",
// MESMO componente do card da página do anime, não reimplementado). Sem
// sinopse (pedido do usuário — a prateleira é compacta, um card por anime já
// em progresso). Também não há badge "✓ assistido": a query do backend que
// alimenta esta prateleira já filtra por episódio não concluído, então
// `trailing` fica de fora.
//
// `state` do Link segue o MESMO formato que LinhaDeEpisodio.jsx já passa pro
// player (`{ episodio: { numero, animeId, animeTitulo, titulo } }`) — sem
// isso o cabeçalho do player perderia o link "voltar"/título de imediato (só
// recuperaria número/animeId depois, via o fallback de
// `GET /api/episodios/{id}` em PaginaDoPlayer.jsx).
export default function CartaoContinuarAssistindo({ item }) {
  // Mesmo cálculo do ramo `pronto` de LinhaDeEpisodio.jsx: sem `duracao_s`
  // (worker não conseguiu sondar) não dá pra calcular a fração, a barra
  // simplesmente não aparece (em vez de aparecer zerada).
  const percentualAssistido =
    item.progresso_s > 0 && item.duracao_s
      ? Math.min(100, Math.round((item.progresso_s / item.duracao_s) * 100))
      : null;
  const minutosRestantes =
    percentualAssistido != null
      ? Math.max(1, Math.round((item.duracao_s - item.progresso_s) / 60))
      : null;

  return (
    <CartaoDeEpisodio
      modo="grade"
      cor="text-white"
      para={`/assistir/${item.episodio_id}`}
      estadoDeRota={{
        episodio: {
          numero: item.numero,
          animeId: item.anime_id,
          animeTitulo: item.anime_titulo,
          titulo: item.titulo,
        },
      }}
      // `legenda` (não `children`): no modo grade, `CartaoDeEpisodio` recorta
      // `children` na caixa 16:9 e renderiza `legenda` ABAIXO dela, fora do
      // recorte (ver rationale em components/LinhaDeEpisodio.jsx). Dentro de
      // `children`, `FaixaDeConteudo` ficaria presa no `aspect-[16/9]` +
      // `overflow-hidden` da caixa e sumiria (conteúdo maior que a caixa,
      // cortado).
      legenda={
        <FaixaDeConteudo
          modo="grade"
          rotulo={
            <span className="flex min-w-0 flex-col gap-0.5">
              <h3 className="line-clamp-1 text-xs text-ink-muted">{item.anime_titulo}</h3>
              <RotuloEpisodio numero={item.numero} titulo={item.titulo} />
            </span>
          }
          extra={
            percentualAssistido != null ? (
              <span className="flex items-center gap-2">
                <span
                  role="progressbar"
                  aria-label="progresso de reprodução"
                  aria-valuenow={percentualAssistido}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  className="h-1 flex-1 overflow-hidden rounded-full bg-border-chrome"
                >
                  <span
                    style={{ width: `${percentualAssistido}%` }}
                    className="block h-full rounded-full bg-neon"
                  />
                </span>
                <span className="shrink-0 text-xs text-ink-muted font-semibold">
                  faltam {minutosRestantes} min
                </span>
              </span>
            ) : null
          }
        />
      }
    >
      <MiniaturaDoEpisodio thumb={item.thumb} modo="grade" />
      <IndicadorDePlay emGrade temThumb={!!item.thumb} />
    </CartaoDeEpisodio>
  );
}
