import { Sparkles } from 'lucide-react';
import {
  CartaoDeEpisodio,
  FaixaDeConteudo,
  IndicadorDePlay,
  MiniaturaDoEpisodio,
  OverlayDeStatus,
  ROTULOS_STATUS,
  RotuloEpisodio,
  SinopseEpisodio,
  tomDoStatus,
} from './LinhaDeEpisodio.jsx';

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
export default function CartaoContinuarAssistindo({ item, job, aoCapturar, capturando }) {
  const rotulo = (
    <span className="flex min-w-0 flex-col gap-0.5">
      <h3 className="line-clamp-1 text-xs text-ink-muted">{item.anime_titulo}</h3>
      <RotuloEpisodio numero={item.numero} titulo={item.titulo} />
    </span>
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
            sinopse={<SinopseEpisodio sinopse={item.sinopse} />}
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
                  <span className="shrink-0 text-xs font-semibold text-ink-muted">
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
        legenda={
          <FaixaDeConteudo
            modo="grade"
            rotulo={rotulo}
            sinopse={<SinopseEpisodio sinopse={item.sinopse} />}
          />
        }
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
      legenda={
        <FaixaDeConteudo
          modo="grade"
          rotulo={rotulo}
          sinopse={<SinopseEpisodio sinopse={item.sinopse} />}
        />
      }
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
function BadgeNovo() {
  return (
    <span className="absolute left-2 top-2 z-10 inline-flex h-7 items-center gap-1 whitespace-nowrap bg-black/80 px-2 text-xs font-semibold uppercase tracking-wide text-white backdrop-blur-md">
      <Sparkles aria-hidden="true" className="h-3.5 w-3.5" />
      Novo ep
    </span>
  );
}
