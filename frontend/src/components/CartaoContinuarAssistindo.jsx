import { Check, Info, Sparkles } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import {
  CartaoDeEpisodio,
  FaixaDeConteudo,
  IndicadorDePlay,
  MiniaturaDoEpisodio,
  OverlayDeStatus,
  ROTULOS_STATUS,
  RotuloEpisodio,
  tomDoStatus,
} from './LinhaDeEpisodio.jsx';
import MenuDeAcoes from './MenuDeAcoes.jsx';

// Item da prateleira "Continuar assistindo" (paginas/Inicio.jsx) — um card por
// ANIME, não por episódio (backend, `api/servicos/progresso.py::
// listar_continuar_assistindo`, 2026-09-18): extensão do catálogo/página do
// anime pedida pelo usuário, então os 3 ramos abaixo (`item.variante`)
// espelham os mesmos estados que `LinhaDeEpisodio.jsx` já resolve pra UM
// anime (`pronto`/"processando"/"nunca capturado ou recaptura"), só cruzando
// vários animes na mesma fileira — por isso reusam as MESMAS peças
// (`CartaoDeEpisodio`, `FaixaDeConteudo`, `IndicadorDePlay`,
// `MiniaturaDoEpisodio`, `OverlayDeStatus`, `SinopseEpisodio`) em vez de
// reimplementar o card do zero.
//
// `CartaoDeEpisodio` PRECISA ser a raiz retornada por cada ramo, sem
// nenhuma `<div>` extra por fora (pedido do usuário, 2026-09-18, depois de
// uma 1ª versão que envolvia o card num wrapper próprio pro título do anime):
// o modo grade interativo (`para`/`aoClicar`) usa `w-[calc(100%+1rem)]`/`-m-2`
// (ver comentário de `LinhaDeEpisodio.jsx::CartaoDeEpisodio`) pra "vazar" 8px
// pra cada lado — é esse vazamento, não um `gap` da fileira (que não tem
// nenhum, `FileiraDeCards.jsx` cola os slots borda a borda de propósito), que
// cria o respiro visual entre cards vizinhos. Um wrapper por fora conteria
// esse vazamento dentro de si mesmo em vez de deixar ele alcançar o `<li>` da
// fileira, e os cards colavam uns nos outros. Por isso o título do anime
// entra dentro do PRÓPRIO `rotulo` da `FaixaDeConteudo` (`Rotulo` abaixo,
// mesmo lugar/mesmo empilhamento de antes desta feature existir) — nunca como
// irmão do card.
//
// `job` (Map global do WS, `App.jsx::useEventosDeJobs`) só é relevante no
// ramo `processando` — status ao vivo do pipeline sem esperar o polling da
// próxima leitura. `aoCapturar`/`capturando` só valem no ramo `capturavel`
// (clicar dispara `POST /api/admin/jobs`, mesmo `criarJobSite` que
// `PaginaDoAnime.jsx` já usa — o card não sabe se é 1ª captura ou recaptura,
// os dois casos são visualmente idênticos em modo grade, que não mostra o
// verbo da ação).
//
// `aoMarcarAssistido`/`marcando`: menu de ações (pedido do usuário) com
// "Marcar como assistido" — ao contrário do botão homônimo de
// `MenuDeAcoesDoAnime` (que marca o anime INTEIRO), aqui marca só ESTE
// episódio (`item.numero`; pedido explícito do usuário, 2026-09-21: a
// prateleira mostra só o PRÓXIMO episódio, marcar em lote a partir dela
// surpreendia — `paginas/Inicio.jsx` chama `marcarEpisodioAssistido`, que
// cria sem baixar quando o episódio nunca foi capturado, mesma lógica do
// botão da página do anime só que restrita a um número). "Ver detalhes do
// anime" navega pra `/anime/:id`. Gatilho SEMPRE presente nos 3 ramos
// (`pronto`/`processando`/`capturavel`) — as duas ações valem independente
// do estado do episódio.
//
// `sobreposicao` (prop nova de `CartaoDeEpisodio`, `LinhaDeEpisodio.jsx`,
// mesmo nome/papel do `sobreposicao` de `AnimeCard.jsx` pro numeral do Top
// 10): NÃO dá pra passar o menu como `children`/wrapper por fora — o
// comentário no topo deste arquivo já proíbe um `<div>` extra ao redor de
// `CartaoDeEpisodio` (quebra o vazamento de 8px entre cards da fileira), e em
// modo grade o card inteiro era o próprio `<Link>`/`<button>`, então um
// `<button>` de menu como filho seria HTML inválido (button dentro de
// button/a). `CartaoDeEpisodio` foi restruturado (stretched-link, mesmo
// padrão que `AnimeCard.jsx` já usa) pra que o Link/button de navegação vire
// uma camada `absolute inset-0` IRMÃ do conteúdo visual, deixando `sobreposicao`
// entrar como outro irmão por cima (`z-10`) sem aninhar em nada — `CartaoDeEpisodio`
// continua sendo a ÚNICA raiz retornada por cada ramo abaixo.
export default function CartaoContinuarAssistindo({ item, job, aoCapturar, capturando, aoMarcarAssistido, marcando }) {
  const navigate = useNavigate();
  const rotulo = (
    <span className="flex min-w-0 flex-col gap-0.5">
      <h3 className="line-clamp-1 text-xs text-ink-muted">{item.anime_titulo}</h3>
      <RotuloEpisodio numero={item.numero} titulo={item.titulo} temporada={item.numero_temporada} />
    </span>
  );

  const menu = (
    // `top-1.5` + gatilho `h-8`: o centro do botão (22px do topo) coincide
    // com o da tag `BadgeNovo` (`top-2` + `h-7`), e o ícone de 24px dentro do
    // `w-8` deixa a borda a 8px da direita, espelhando o `left-2` da tag.
    <div className="absolute right-1 top-1.5 z-10">
      <MenuDeAcoes
        rotuloGatilho={`Mais ações para ${item.anime_titulo}`}
        posicao="lado"
        itens={[
          {
            chave: 'marcar-assistido',
            rotulo: marcando ? 'Marcando…' : 'Marcar como assistido',
            Icone: Check,
            aoClicar: () => aoMarcarAssistido(item),
            desabilitado: marcando,
          },
          {
            chave: 'ver-detalhes',
            rotulo: 'Ver detalhes do anime',
            Icone: Info,
            aoClicar: () => navigate(`/anime/${item.anime_id}`),
          },
        ]}
        classeGatilho={(aberto) =>
          `flex h-8 w-8 items-center justify-center rounded-full text-white/80 outline-none transition-colors cursor-pointer drop-shadow-[0_1px_3px_rgba(0,0,0,0.9)] ${
            aberto ? 'text-white' : 'hover:text-white'
          }`
        }
        tamanhoIcone={24}
      />
    </div>
  );

  if (item.variante === 'pronto') {
    // Mesmo cálculo de LinhaDeEpisodio.jsx (ramo `pronto`): sem `progresso_s`
    // (largada nova, ex. próximo episódio que você nunca começou) a barra
    // simplesmente não aparece, em vez de aparecer zerada.
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
        sobreposicao={menu}
        brilho={item.thumb ?? null}
        rotuloAcessivel={`Assistir episódio ${item.numero} de ${item.anime_titulo}`}
        estadoDeRota={{
          episodio: {
            numero: item.numero,
            animeId: item.anime_id,
            animeTitulo: item.anime_titulo,
            titulo: item.titulo,
          },
        }}
        legenda={
          <FaixaDeConteudo
            modo="grade"
            rotulo={rotulo}
            extra={
              minutosRestantes != null ? (
                <span className="text-xs font-semibold text-ink-muted">
                  faltam {minutosRestantes} min
                </span>
              ) : null
            }
          />
        }
      >
        <MiniaturaDoEpisodio thumb={item.thumb} modo="grade" />
        <IndicadorDePlay emGrade temThumb={!!item.thumb} />
        {/* Barra de progresso estilo Netflix, sobre a própria miniatura
            (pedido do usuário, 2026-09-21 — antes ficava abaixo, na legenda).
            `absolute inset-x-0 bottom-0`: cola na borda inferior da caixa
            recortada 16:9 (mesmo `overflow-hidden` de `classeCaixa` em
            `LinhaDeEpisodio.jsx::CartaoDeEpisodio` corta a barra se ela
            tentasse passar da borda, mas `bottom-0` já a mantém dentro). */}
        {percentualAssistido != null && (
          <span
            role="progressbar"
            aria-label="progresso de reprodução"
            aria-valuenow={percentualAssistido}
            aria-valuemin={0}
            aria-valuemax={100}
            className="absolute inset-x-0 bottom-0 z-10 h-1 bg-white/25"
          >
            <span
              style={{ width: `${percentualAssistido}%` }}
              className="block h-full bg-neon"
            />
          </span>
        )}
      </CartaoDeEpisodio>
    );
  }

  if (item.variante === 'processando') {
    // Ramo estático (sem `para`/`aoClicar`) — mesmo tratamento do ramo (3) de
    // LinhaDeEpisodio.jsx: `job` (ao vivo) tem prioridade sobre `item.status`
    // (última leitura do banco, usada até o WS confirmar).
    const statusAtual = job?.status ?? item.status;
    const rotuloStatus = ROTULOS_STATUS[statusAtual] ?? statusAtual;
    return (
      <CartaoDeEpisodio
        modo="grade"
        cor="text-ink-muted"
        sobreposicao={menu}
        brilho={item.thumb ?? null}
        legenda={<FaixaDeConteudo modo="grade" rotulo={rotulo} />}
      >
        <MiniaturaDoEpisodio thumb={item.thumb} modo="grade" />
        <OverlayDeStatus rotulo={rotuloStatus} tom={tomDoStatus(statusAtual)} />
      </CartaoDeEpisodio>
    );
  }

  // `capturavel`: nunca capturado (badge "Novo ep" quando `episodio_novo`) ou
  // recaptura (`LIBERADO`/`FALHOU` na origem) — mesmo alvo de clique, a
  // diferença de verbo só existe em modo lista (RotuloDeAcao), que este card
  // nunca usa.
  return (
    <CartaoDeEpisodio
      modo="grade"
      cor="text-white font-semibold"
      aoClicar={() => aoCapturar(item)}
      desabilitado={capturando}
      rotuloAcessivel={`Capturar episódio ${item.numero} de ${item.anime_titulo}`}
      sobreposicao={menu}
      brilho={item.thumb ?? null}
      legenda={<FaixaDeConteudo modo="grade" rotulo={rotulo} />}
    >
      <MiniaturaDoEpisodio thumb={item.thumb} modo="grade" />
      {capturando && <OverlayDeStatus rotulo="Capturando…" tom="progresso" />}
      {!capturando && item.episodio_novo && <BadgeNovo />}
    </CartaoDeEpisodio>
  );
}

// Mesmo texto de `components/BadgeDeEpisodiosNovos.jsx::textoEpisodiosNovos`
// (singular fixo aqui — este card é sempre UM episódio, nunca uma contagem) e
// mesmo visual de pill de `AnimeCard.jsx::badgeAviso` (`Sparkles`, fundo
// `bg-black/80 backdrop-blur-md`) — a badge "episódio novo" já tem uma
// linguagem visual estabelecida na Galeria, este card não inventa uma nova.
// Não usa o MESMO tamanho de lá (`h-8`/`h-5 w-5`): a miniatura aqui é
// `aspect-[16/9]`, bem mais baixa que o pôster 2:3 do card da Galeria, pill
// no tamanho cheio ficaria grande demais pra altura disponível. Ajuste
// pontual (pedido explícito do usuário, 2026-09-21): ícone só um passo maior
// (`h-3.5` → `h-4`), pill/texto ficam como estavam.
function BadgeNovo() {
  return (
    <span className="absolute left-2 top-2 z-10 inline-flex h-7 items-center gap-1 whitespace-nowrap rounded-2xl bg-black/80 px-2 text-xs font-semibold uppercase tracking-wide text-white backdrop-blur-md">
      <Sparkles aria-hidden="true" className="h-4 w-4" />
      Novo ep
    </span>
  );
}
