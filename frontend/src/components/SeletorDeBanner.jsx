import { useEffect, useRef } from 'react';
import { BotaoDaIlha, DivisorDaIlha } from './ilha/ElementosDaIlha.jsx';

// Modo "Trocar banner" da página do anime (estado em `hooks/useSeletorDeBanner.js`),
// inteiro dentro da ilha dinâmica da navbar (`BarraDeNavegacao` `modoDaIlha`):
// miniaturas das opções, Aplicar, Cancelar e Restaurar padrão. O resto da página fica
// como está e o hero mostra ao vivo a opção marcada.

// Miniatura de uma opção: `<input type="radio">` nativo escondido (`sr-only`) sob a
// imagem — setas, Tab e leitor de tela funcionam sem JS de teclado, e a borda neon
// marca a opção selecionada (ou com foco de teclado, que nos radios é a mesma coisa).
function MiniaturaDeBanner({ candidato, indice, seletor }) {
  const atual = candidato.arquivo === seletor.arquivoAtual;
  return (
    <label
      title={atual ? 'Banner atual' : undefined}
      className="group/mini relative block h-9 w-16 shrink-0 cursor-pointer"
    >
      <input
        type="radio"
        name="banner"
        value={candidato.arquivo}
        checked={seletor.selecionado === candidato.arquivo}
        onChange={() => seletor.escolher(candidato.arquivo)}
        aria-label={`Banner ${indice + 1}${atual ? ' (atual)' : ''}`}
        className="sr-only"
      />
      <img
        src={candidato.miniatura_url}
        alt=""
        decoding="async"
        className="h-full w-full rounded-lg bg-surface object-cover"
      />
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 rounded-lg border-2 border-transparent transition-colors duration-300 group-has-[:checked]/mini:border-neon group-has-[:focus-visible]/mini:border-neon motion-reduce:transition-none"
      />
      {atual && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute bottom-1 right-1 h-1.5 w-1.5 rounded-full bg-white"
        />
      )}
    </label>
  );
}

// As opções vêm em número variável (até uma dúzia): a lista fica numa janela de
// largura máxima, pra a ilha não passar da navbar, e as pontas esmaecem só do lado em
// que ainda há mais opções, pra mostrar que a lista continua. O foco vai pra
// opção selecionada ao entrar: o item de menu que abriu o modo some junto com o menu, e
// sem isto o foco cairia no <body>.
//
// A rolagem NÃO é a nativa. A janela é `overflow-hidden` e a faixa de miniaturas anda
// por `transform: translate3d`, animada em `requestAnimationFrame` com amortecimento
// por TEMPO (independente da taxa de quadros). Motivo: com `scrollLeft` o navegador
// arredonda pra pixel inteiro, e a rolagem suave nativa recomeça a cada clique da roda
// — as duas versões anteriores andavam aos trancos. `transform` é subpixel e roda no
// compositor. A roda cancela o gesto (a página não rola, nem no extremo) e só move o
// ALVO; cliques seguidos somam. `wheel` precisa de listener nativo não-passivo: o
// `onWheel` do React é passivo e não deixaria cancelar. Sem toque: o app é desktop-first.
const LARGURA_DO_ESMAECIDO_PX = 28;
// Cada ponta esmaece em proporção ao quanto ainda há por rolar daquele lado (até a
// largura cheia), e some por completo no extremo. Ligar/desligar de uma vez fazia o
// card da ponta ficar apagado durante a rolagem e "saltar" pro normal ao parar.
// `--fade-esq`/`--fade-dir` são gravadas direto no DOM a cada quadro, sem `useState`.
const MASCARA_DAS_PONTAS =
  'linear-gradient(to right, transparent 0, #000 var(--fade-esq), #000 calc(100% - var(--fade-dir)), transparent 100%)';
// Constante de tempo do amortecimento (ms): ~63% do caminho a cada TAU.
const TAU_DA_ROLAGEM_MS = 110;

function ListaDeMiniaturas({ seletor }) {
  const { candidatos } = seletor;
  const janelaRef = useRef(null);
  const faixaRef = useRef(null);
  const mascaraRef = useRef(null);

  useEffect(() => {
    const janela = janelaRef.current;
    const faixa = faixaRef.current;
    const reduzido = window.matchMedia('(prefers-reduced-motion: reduce)');
    let x = 0;
    let alvo = 0;
    let quadro = null;
    let ultimoQuadro = null;
    const maximo = () => Math.max(0, faixa.offsetWidth - janela.clientWidth);
    const limitar = (posicao) => Math.min(Math.max(posicao, 0), maximo());

    const aplicar = () => {
      faixa.style.transform = `translate3d(${-x}px, 0, 0)`;
      const { style } = mascaraRef.current;
      style.setProperty('--fade-esq', `${Math.min(x, LARGURA_DO_ESMAECIDO_PX)}px`);
      style.setProperty('--fade-dir', `${Math.min(maximo() - x, LARGURA_DO_ESMAECIDO_PX)}px`);
    };
    const passo = (agora) => {
      const dt = ultimoQuadro === null ? 16 : Math.min(Math.max(agora - ultimoQuadro, 0), 50);
      ultimoQuadro = agora;
      x += (alvo - x) * (1 - Math.exp(-dt / TAU_DA_ROLAGEM_MS));
      if (Math.abs(alvo - x) < 0.1) {
        x = alvo;
        quadro = null;
      } else {
        quadro = requestAnimationFrame(passo);
      }
      aplicar();
    };
    const aoRolarComRoda = (evento) => {
      evento.preventDefault();
      // `deltaMode` 1 = linhas (Firefox com roda), 2 = páginas.
      const unidade = evento.deltaMode === 1 ? 16 : evento.deltaMode === 2 ? janela.clientWidth : 1;
      const delta =
        (Math.abs(evento.deltaX) > Math.abs(evento.deltaY) ? evento.deltaX : evento.deltaY) * unidade;
      alvo = limitar(alvo + delta);
      if (reduzido.matches) {
        x = alvo;
        aplicar();
      } else if (quadro === null) {
        ultimoQuadro = null;
        quadro = requestAnimationFrame(passo);
      }
    };
    // O foco de teclado numa miniatura fora da janela faz o navegador rolar a janela
    // (`overflow-hidden` ainda rola por código): converte esse deslocamento em `x` e zera
    // o `scrollLeft`, pra a posição visual não pular nem somar duas vezes.
    const aoRolarNativo = () => {
      if (janela.scrollLeft === 0) return;
      x = limitar(x + janela.scrollLeft);
      alvo = x;
      janela.scrollLeft = 0;
      aplicar();
    };

    janela.addEventListener('wheel', aoRolarComRoda, { passive: false });
    janela.addEventListener('scroll', aoRolarNativo);
    faixa.querySelector('input:checked, input')?.focus();
    aplicar();
    return () => {
      janela.removeEventListener('wheel', aoRolarComRoda);
      janela.removeEventListener('scroll', aoRolarNativo);
      if (quadro !== null) cancelAnimationFrame(quadro);
    };
  }, []);

  // A máscara fica num wrapper à parte da janela, não nela. Os `0px` iniciais valem
  // até o efeito acima medir; depois as variáveis são do DOM, não do React.
  return (
    <div
      ref={mascaraRef}
      style={{
        maskImage: MASCARA_DAS_PONTAS,
        WebkitMaskImage: MASCARA_DAS_PONTAS,
        '--fade-esq': '0px',
        '--fade-dir': '0px',
      }}
    >
      <div
        ref={janelaRef}
        role="radiogroup"
        aria-label="Banners disponíveis"
        className="max-w-[22rem] overflow-hidden py-1"
      >
        <div ref={faixaRef} className="flex w-max items-center gap-2 will-change-transform">
          {candidatos.map((candidato, indice) => (
            <MiniaturaDeBanner
              key={candidato.arquivo}
              candidato={candidato}
              indice={indice}
              seletor={seletor}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

// Aviso no lugar das miniaturas (carregando, erro, vazio): mesmo texto/estilo dos
// avisos da ilha, sem desmontar os botões Cancelar/Restaurar.
function AvisoDaIlha({ tom = 'neutro', children }) {
  return (
    <span
      role={tom === 'alerta' ? 'alert' : 'status'}
      className={`whitespace-nowrap text-[18px] font-semibold ${tom === 'alerta' ? 'text-amber-300' : 'text-ink-muted'}`}
    >
      {children}
    </span>
  );
}

export function SeletorDeBannerNaIlha({ seletor, personalizado }) {
  const { candidatos } = seletor;
  const temOpcoes = candidatos?.length > 0;
  return (
    <>
      {seletor.carregando && <AvisoDaIlha>Buscando opções…</AvisoDaIlha>}
      {seletor.erroAoBuscar && (
        <>
          <AvisoDaIlha tom="alerta">Não foi possível carregar</AvisoDaIlha>
          <BotaoDaIlha onClick={seletor.recarregar}>Tentar de novo</BotaoDaIlha>
        </>
      )}
      {candidatos?.length === 0 && <AvisoDaIlha>Sem alternativas de banner</AvisoDaIlha>}
      {temOpcoes && (
        <fieldset disabled={seletor.salvando} className="m-0 min-w-0 border-0 p-0">
          <ListaDeMiniaturas seletor={seletor} />
        </fieldset>
      )}
      {temOpcoes && (
        <>
          <DivisorDaIlha />
          <BotaoDaIlha
            onClick={seletor.aplicar}
            disabled={seletor.salvando || !seletor.podeAplicar}
          >
            {seletor.salvando ? 'Salvando…' : 'Aplicar'}
          </BotaoDaIlha>
        </>
      )}
      <DivisorDaIlha />
      <BotaoDaIlha onClick={seletor.cancelar} disabled={seletor.salvando}>
        Cancelar
      </BotaoDaIlha>
      {personalizado && (
        <>
          <DivisorDaIlha />
          <BotaoDaIlha onClick={seletor.restaurar} disabled={seletor.salvando}>
            Restaurar padrão
          </BotaoDaIlha>
        </>
      )}
      {seletor.erroAoSalvar && <AvisoDaIlha tom="alerta">{seletor.erroAoSalvar}</AvisoDaIlha>}
    </>
  );
}
