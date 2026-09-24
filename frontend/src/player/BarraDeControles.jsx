import { useEffect, useRef, useState } from 'react';
import MenuDeConfiguracoes from './MenuDeConfiguracoes.jsx';
import PreviaDeCena, { LARGURA_THUMB } from './PreviaDeCena.jsx';
import { IconePlay, IconePausa, IconeVolume, IconeTelaCheia, IconeSkip10 } from './Icones.jsx';
import { usePreferencia } from './hooks/usePreferencia.js';
import { useSegurarParaPular } from './hooks/useSegurarParaPular.js';
import { formatarTempo } from './formatarTempo.js';

// Ghost pill (transparente, acende no hover) — a mesma família visual do
// Disney+/YouTube (ícones flutuando sobre o vídeo, sem caixa/borda própria),
// substituindo a caixa cinza+borda de antes. Estado "pressionado" (cinema
// habilitado) usa o accent neon do resto do Slime Studio (--color-neon, ver
// tailwind.config via @theme em index.css), não mais um verde ad-hoc só
// deste componente. Mesmo tamanho de caixa do trio central (`h-14 min-w-14`,
// pedido explícito do usuário: só o play fica maior, o resto — volume,
// configurações, tela cheia — fecha igual a avançar/retroceder).
// Áudio cinema e HUD saíram daqui (viraram linhas de MenuDeConfiguracoes.jsx).
// Cobre os botões periféricos; o trio central usa `classeBotaoTrio` abaixo,
// que só difere no estilo de hover (sem pill) e no play, com ícone maior.
const classeBotao =
  'inline-flex h-12 min-w-12 items-center justify-center rounded-full px-3 text-lg font-semibold text-white/90 transition ' +
  'hover:bg-white/15 hover:text-white aria-pressed:bg-neon/20 aria-pressed:text-neon ' +
  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-white focus-visible:outline-offset-2 ' +
  'disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none';

// Play/pausa e os dois botões de skip (avançar/retroceder) formam um trio
// central sem caixa nem fundo — o próprio ícone flutua sobre o vídeo e só
// escurece um pouco no hover, exatamente como o trio referenciado pelo
// usuário em play.disneyplus.com/.../{id}: conferido ao vivo lá (2026-09-13)
// que os três botões renderizam do MESMO tamanho — nenhuma caixa branca,
// nenhum play maior que os skips — por isso os três dividem esta classe
// (`min-w-14`, não `w-14` fixo, porque o skip empilha ícone+"10" e pode
// precisar de um pouco mais de largura que o quadrado mínimo).
const classeBotaoTrio =
  'relative inline-flex h-14 min-w-14 items-center justify-center rounded-full text-white transition ' +
  'hover:text-white/70 active:scale-90 ' +
  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-white focus-visible:outline-offset-2 ' +
  'motion-reduce:transition-none motion-reduce:active:scale-100 touch-none';

// Componente controlado: não guarda a fonte de verdade da reprodução — isso
// vive no <video> (videoRef, de Player.jsx). Este componente só espelha o
// estado do elemento (via listeners) em controles de UI; ações (play, mudo,
// tela cheia, HUD, cinema) são callbacks recebidos de Player.jsx — as
// mesmas que useAtalhosDeTeclado.js aciona pelo teclado, sem duplicar
// lógica. Porte de bench.js:wireControls (630-714), pra dentro de efeitos
// de React em vez de addEventListener solto num módulo de topo.
export default function BarraDeControles({
  videoRef,
  presetAtual,
  aoTrocarPreset,
  aoAlternarReproducao,
  aoAlternarMudo,
  aoAlternarTelaCheia,
  aoAlternarHud,
  hudVisivel,
  aoAlternarCinema,
  cinemaHabilitado,
  cinemaFalhou,
  // Avançar/retroceder 10s (PlayerAtivo.jsx), mesmo padrão de
  // aoAlternarReproducao/aoAlternarMudo etc. `?.()` no clique é só defesa
  // contra um chamador futuro que monte a barra sem passar as duas props.
  aoAvancar,
  aoRetroceder,
  // Avançar/retroceder 1m30 (PlayerAtivo.jsx) — não viram botões à parte:
  // alimentam o gesto de segurar nos próprios botões de skip de 10s do trio
  // abaixo (useSegurarParaPular.js), pedido do usuário 2026-09-24.
  aoAvancarNoventa,
  aoRetrocederNoventa,
  // URL do sprite de prévia (PlayerAtivo.jsx, derivada de `fonte`) — `undefined`
  // é um valor válido (PreviaDeCena.jsx só não renderiza nada nesse caso).
  storyboardUrl,
}) {
  const [tocando, setTocando] = useState(false);
  const [progresso, setProgresso] = useState(0);
  const [tempoAtual, setTempoAtual] = useState(0);
  const [duracao, setDuracao] = useState(NaN);
  // Persistidos (localStorage) — video.volume/muted nascem em 1/false a cada
  // novo <video>, sem isto o player sempre abriria no volume padrão em vez
  // do que o usuário deixou da última vez.
  const [mudo, setMudo] = usePreferencia('slime.mudo', false);
  const [volume, setVolume] = usePreferencia('slime.volume', 1);
  const seekingRef = useRef(false);
  // Posição do hover na barra de progresso, pra PreviaDeCena — `null` fora
  // do hover. Vive aqui (não em PreviaDeCena) porque depende de `duracao`,
  // já rastreada neste componente.
  const [previa, setPrevia] = useState(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    // Aplica a preferência salva uma vez, ao montar — ver comentário acima.
    video.volume = volume;
    video.muted = mudo;

    const aoTocar = () => setTocando(true);
    const aoPausar = () => setTocando(false);
    const aoAtualizarTempo = () => {
      if (!seekingRef.current && video.duration) {
        setProgresso((video.currentTime / video.duration) * 100);
      }
      setTempoAtual(video.currentTime);
      setDuracao(video.duration);
    };
    // Cobre slider de volume, mute button E os atalhos de teclado (↑/↓/M) —
    // todos mexem em video.volume/video.muted direto; este listener único
    // mantém a UI sincronizada com qualquer um deles, sem duplicar lógica.
    const aoMudarVolume = () => {
      setVolume(video.volume);
      setMudo(video.muted);
    };

    video.addEventListener('play', aoTocar);
    video.addEventListener('pause', aoPausar);
    video.addEventListener('timeupdate', aoAtualizarTempo);
    video.addEventListener('volumechange', aoMudarVolume);
    aoMudarVolume(); // estado inicial

    return () => {
      video.removeEventListener('play', aoTocar);
      video.removeEventListener('pause', aoPausar);
      video.removeEventListener('timeupdate', aoAtualizarTempo);
      video.removeEventListener('volumechange', aoMudarVolume);
    };
    // volume/mudo só lidos aqui pra semear o valor inicial ao montar — mudanças
    // posteriores já chegam ao <video> via aoDigitarVolume/aoAlternarMudo, listar
    // as duas aqui reiniciaria os listeners a cada ajuste de volume.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoRef]);

  function aoMoverSeek(event) {
    seekingRef.current = true;
    const video = videoRef.current;
    const novoProgresso = Number(event.target.value);
    setProgresso(novoProgresso);
    if (video?.duration) video.currentTime = (novoProgresso / 100) * video.duration;
  }

  function aoSoltarSeek() {
    seekingRef.current = false;
  }

  // getBoundingClientRect() do wrapper (não do <input>): os dois têm a mesma
  // largura (o input é w-full dentro dele), mas medir o wrapper evita
  // qualquer desalinhamento por borda/padding do próprio range nativo.
  function aoPassarMouseNoProgresso(event) {
    if (!Number.isFinite(duracao) || duracao <= 0) return;
    const retangulo = event.currentTarget.getBoundingClientRect();
    const fracao = Math.min(1, Math.max(0, (event.clientX - retangulo.left) / retangulo.width));
    const centroCursor = fracao * retangulo.width;
    // Clampa contra a borda real do PLAYER (`.controls`, mesma largura do
    // palco em tela cheia — `inset-x-0` na raiz do JSX abaixo), não contra a
    // faixa estreita do `<input>` (que sobra bem mais curta por causa dos
    // tempos/gaps ao lado): sem isto a prévia parava de seguir o cursor bem
    // antes da borda de verdade, sobrando um respiro grande e sem uso perto
    // das pontas. `GUTTER` é só uma folga visual além do `px-6` que `.controls`
    // já tem — não deixa a miniatura ficar colada na borda do vídeo.
    const retanguloControles = event.currentTarget.closest('.controls')?.getBoundingClientRect();
    let centro = centroCursor;
    if (retanguloControles) {
      const GUTTER = 8;
      const metade = LARGURA_THUMB / 2;
      const limiteEsquerdo = retanguloControles.left + GUTTER - retangulo.left + metade;
      const limiteDireito = retanguloControles.right - GUTTER - retangulo.left - metade;
      centro = Math.min(limiteDireito, Math.max(limiteEsquerdo, centroCursor));
    }
    setPrevia({ tempo: fracao * duracao, x: centro });
  }

  function aoSairDoProgresso() {
    setPrevia(null);
  }

  function aoDigitarVolume(event) {
    const video = videoRef.current;
    if (!video) return;
    video.volume = Number(event.target.value);
    video.muted = video.volume === 0;
  }

  // Um hook por lado (não um estado só) — retroceder e avançar podem, em
  // teoria, ser pressionados em sequência rápida sem que o anel de um
  // interfira no do outro.
  const segurarRetroceder = useSegurarParaPular(() => aoRetroceder?.(), () => aoRetrocederNoventa?.());
  const segurarAvancar = useSegurarParaPular(() => aoAvancar?.(), () => aoAvancarNoventa?.());

  // 3 estados pro ícone animado (Icones.jsx::IconeVolume) — mudo cobre tanto
  // o toggle quanto volume zerado por arraste, sem duplicar essa checagem.
  const nivelDeVolume = mudo || volume === 0 ? 'mudo' : volume < 0.5 ? 'baixo' : 'alto';

  return (
    <div
      className="controls absolute inset-x-0 bottom-0 flex flex-col gap-3 px-6 pt-8 pb-5"
      style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.85), rgba(0,0,0,0))' }}
      role="group"
      aria-label="Controles de reprodução"
    >
      {/* Linha 1: progresso, com os tempos ancorados nas pontas — mesmo
          slider/handlers de antes, só sem o badge combinado "atual / total"
          ao lado; cada tempo vira label na ponta correspondente. `--fill`
          substitui o `accent-color` nativo (ver player.css): o preenchimento
          calculado à mão chega até a ponta de verdade em vez de parar um
          pouco antes por causa do raio do thumb. O <input> vive dentro de um
          wrapper `relative` só pra ancorar PreviaDeCena (hover) — `w-full`
          nele substitui o `flex-1` que era do próprio input. `flex
          items-center` no wrapper (2026-09-17, corrigindo desalinhamento
          reportado pelo usuário): sem isso o <input> — replaced element
          dentro de um bloco comum — sobra espaço de descendente abaixo dele e
          fica encostado no topo da própria caixa, desalinhado dos tempos ao
          lado; MESMO bug que o wrapper do slider de volume abaixo já
          corrige. */}
      <div className="flex items-center gap-3">
        <span
          aria-hidden="true"
          className="min-w-[3ch] text-base text-[#ccc] [font-variant-numeric:tabular-nums]"
        >
          {formatarTempo(tempoAtual)}
        </span>
        <div
          className="relative flex min-w-30 flex-1 items-center"
          onMouseMove={aoPassarMouseNoProgresso}
          onMouseLeave={aoSairDoProgresso}
        >
          <input
            type="range"
            min="0"
            max="100"
            step="0.01"
            value={progresso}
            onInput={aoMoverSeek}
            onChange={aoSoltarSeek}
            aria-label="Posição no vídeo"
            aria-valuetext={`${formatarTempo(tempoAtual)} de ${formatarTempo(duracao)}`}
            className="barra-progresso w-full"
            style={{ '--fill': `${progresso}%` }}
          />
          {previa && <PreviaDeCena url={storyboardUrl} tempo={previa.tempo} esquerda={previa.x} />}
        </div>
        {/* aria-hidden nos dois: o tempo já é anunciado via aria-valuetext do
            slider — expor aqui também duplicaria pro leitor de tela. */}
        <span
          aria-hidden="true"
          className="min-w-[3ch] text-right text-base text-[#ccc] [font-variant-numeric:tabular-nums]"
        >
          {formatarTempo(duracao)}
        </span>
      </div>

      {/* Linha 2: 3 zonas (grid, não flex) — o trio play/skip fica
          matematicamente centralizado independente da largura dos grupos ao
          lado, em vez de seguir o texto/paddings deles como aconteceria com
          justify-between.

          Retroceder/avançar (gesto de useSegurarParaPular.js): o anel fino
          que existia ao redor do botão (AnelDeSegurar) saiu — o próprio
          `progresso` (0-1) agora vai direto pra IconeSkip10 (Icones.jsx),
          que pinta o traço do ícone em neon do início do arco até a ponta
          da seta e faz o "10" virar "90", pedido do usuário 2026-09-24. */}
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
        <div className="flex items-center gap-3">
          {/* group/volume: o slider nasce recolhido (w-0) e só se revela no
              hover/foco do grupo — mesma animação do controle de volume do
              YouTube. group-focus-within cobre navegação por teclado (Tab
              até o slider sem precisar de hover); motion-reduce mantém
              sempre aberto pra quem pediu menos movimento, em vez de um
              controle que nunca aparece. `items-center` nos dois níveis
              (grupo e wrapper que colapsa) é o que centraliza a trilha com o
              ícone — antes só o grupo tinha, e o wrapper sem `flex` deixava
              o input encostado no topo da própria caixa. */}
          <div className="group/volume flex items-center gap-1">
            <button type="button" onClick={aoAlternarMudo} aria-label={mudo ? 'Ativar som' : 'Mudo'} className={classeBotao}>
              <IconeVolume nivel={nivelDeVolume} width={26} height={26} />
            </button>
            {/* Caixa que colapsa (w-0 → w-28) é mais larga que o próprio
                slider (w-24), com `justify-center` sobrando 8px de cada
                lado — é o que faltava antes: com as duas larguras iguais o
                `overflow-hidden` cortava a metade do thumb (a "bolinha")
                sempre que ela chegava perto de uma ponta da trilha (ex.
                volume 100%), porque o raio do thumb ultrapassa a borda do
                próprio input. */}
            <div
              className={
                'flex w-0 items-center justify-center overflow-hidden opacity-0 transition-[width,opacity] duration-200 ease-out ' +
                'group-hover/volume:w-28 group-hover/volume:opacity-100 ' +
                'group-focus-within/volume:w-28 group-focus-within/volume:opacity-100 ' +
                'motion-reduce:w-28 motion-reduce:opacity-100 motion-reduce:transition-none'
              }
            >
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={volume}
                onInput={aoDigitarVolume}
                aria-label="Volume"
                className="barra-volume w-24 shrink-0"
                style={{ '--fill': `${volume * 100}%` }}
              />
            </div>
          </div>
        </div>

        {/* Trio central — retroceder/play/avançar, mesma composição do
            player do Disney+ referenciado. O "10" não fica mais empilhado
            embaixo do ícone num <span> à parte (removido a pedido do
            usuário, 2026-09-17) — agora é composto DENTRO do círculo da
            seta, direto em IconeSkip10 (Icones.jsx), sem mudar nada aqui.
            Retroceder/avançar ganharam o gesto de segurar (useSegurarParaPular
            .js, pedido do usuário 2026-09-24): toque rápido continua sendo o
            skip de 10s de sempre (via `onClick`, embutido em `handlers`);
            segurar ~600ms pinta o próprio ícone em neon (IconeSkip10,
            `progresso` abaixo) e, ao completar, salta 1m30 — sem nenhum
            botão novo na barra. */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            {...segurarRetroceder.handlers}
            aria-label="Retroceder 10 segundos — segure para retroceder 1 minuto e 30 segundos"
            className={classeBotaoTrio}
          >
            <IconeSkip10 direcao="tras" width={32} height={32} progresso={segurarRetroceder.progresso} />
          </button>
          <button
            type="button"
            onClick={aoAlternarReproducao}
            aria-label={tocando ? 'Pausar' : 'Reproduzir'}
            className={classeBotaoTrio}
          >
            {tocando ? (
              <IconePausa fill="currentColor" stroke="none" width={62} height={62} />
            ) : (
              <IconePlay fill="currentColor" stroke="none" width={62} height={62} />
            )}
          </button>
          <button
            type="button"
            {...segurarAvancar.handlers}
            aria-label="Avançar 10 segundos — segure para avançar 1 minuto e 30 segundos"
            className={classeBotaoTrio}
          >
            <IconeSkip10 direcao="frente" width={32} height={32} progresso={segurarAvancar.progresso} />
          </button>
        </div>

        {/* `relative` mora aqui (não mais dentro de MenuDeConfiguracoes.jsx)
            de propósito: o gatilho (engrenagem) fica no meio do grupo, mas o
            painel que abre (`absolute right-0` em MenuDeConfiguracoes.jsx)
            ancora no elemento posicionado mais próximo. Sendo ESTE grupo o
            ancestral posicionado, o painel fica flush com a borda direita do
            grupo inteiro — a mesma borda onde a linha de progresso acima
            termina (tempo total) — em vez de flush só com o próprio botão
            pequeno da engrenagem, que ficaria desalinhado da barra por estar
            no meio. HUD saiu daqui (virou toggle dentro do próprio menu de
            configurações) e "Avançar 1m30" nunca teve botão próprio aqui —
            virou o gesto de segurar nos botões de skip do trio acima
            (ver `progresso` em IconeSkip10, Icones.jsx) — pedidos do
            usuário, 2026-09-24. */}
        <div className="relative flex items-center justify-end gap-2">
          <MenuDeConfiguracoes
            presetAtual={presetAtual}
            aoTrocar={aoTrocarPreset}
            cinemaHabilitado={cinemaHabilitado}
            cinemaFalhou={cinemaFalhou}
            aoAlternarCinema={aoAlternarCinema}
            hudVisivel={hudVisivel}
            aoAlternarHud={aoAlternarHud}
          />
          <button type="button" onClick={aoAlternarTelaCheia} aria-label="Tela cheia" className={classeBotao}>
            <IconeTelaCheia width={26} height={26} />
          </button>
        </div>
      </div>
    </div>
  );
}
