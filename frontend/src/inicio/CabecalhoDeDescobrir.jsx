import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Compass } from 'lucide-react';
import { reduzirImagemTmdb } from '../components/reduzirImagemTmdb.js';
import { GRADIENTE_DO_HERO } from './CarrosselDestaques.jsx';
import { traduzirGenero } from './generos.js';
import TrocaComCrossfade from './TrocaComCrossfade.jsx';
import { PADDING_TITULO_GRADE } from './tamanhoDeCard.js';
import { usePrefersReducedMotion } from './usePrefersReducedMotion.js';

// Cabeçalho imersivo de paginas/Descobrir.jsx: uma parede inclinada com as capas
// dos próprios títulos da página, em colunas que sobem e descem em sentidos
// opostos, sem fim. Escolher um gênero troca a parede por uma nova com as capas
// daquele gênero, em crossfade (inicio/TrocaComCrossfade.jsx, `versao` do hook): a
// antiga continua rodando por baixo enquanto some. A parede
// é decorativa (`aria-hidden`, sem clique): quem navega são os cards da grade.
//
// Mesma geometria do hero de PaginaDoAnime: `h-svh min-h-[480px]`, fade pro preto
// (`GRADIENTE_DO_HERO`) e `-mb-32`, que deixa o topo da primeira fileira "espiar"
// sob o fade (a página põe `relative z-10` no que vem depois). A navbar é
// transparente e fica por cima.
//
// Infinito sem emenda: a coluna não é uma lista que dá a volta. O DOM é fixo (só o
// que cabe + um respiro de slots fora da tela em cima e embaixo) e, a cada slot que
// sai, os <img> são reaproveitados com outro `src`, sempre fora da tela. Por isso é
// rAF e não CSS — uma animação CSS em laço tem que repetir a lista e o salto aparece.
// Quais capas entram em cada coluna está em `ParedeDeCapas`.

const COLUNAS = 8;
const GAP_PX = 16;
const RESPIRO_DE_SLOTS = 2;
// Medidas da parede em relação ao cabeçalho (`-inset-x-[18%] -inset-y-[35%]`).
const FATOR_LARGURA = 1.36;
const FATOR_ALTURA = 1.7;
// px/s por coluna; as colunas ímpares correm ao contrário.
const velocidadeDaColuna = (coluna) => 12 + (coluna % 3) * 4;

function embaralhar(lista) {
  const copia = [...lista];
  for (let i = copia.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [copia[i], copia[j]] = [copia[j], copia[i]];
  }
  return copia;
}

export default function CabecalhoDeDescobrir({
  itensDeFundo,
  versao,
  generos,
  generoEscolhido,
  aoEscolherGenero,
  erro,
}) {
  const areaRef = useRef(null);
  const [medidas, setMedidas] = useState(null);

  const urls = useMemo(
    () => itensDeFundo.filter((item) => item.capa_url).map((item) => reduzirImagemTmdb(item.capa_url)),
    [itensDeFundo],
  );

  // Tamanho de um slot (capa 2:3 + espaçamento) e quantos cabem na parede.
  useEffect(() => {
    const area = areaRef.current;
    const medir = () => {
      const larguraDaColuna =
        (area.clientWidth * FATOR_LARGURA - (COLUNAS - 1) * GAP_PX) / COLUNAS;
      const alturaDoSlot = larguraDaColuna * 1.5 + GAP_PX;
      const quantidade =
        Math.ceil((area.clientHeight * FATOR_ALTURA) / alturaDoSlot) + 2 * RESPIRO_DE_SLOTS + 1;
      setMedidas((atual) =>
        atual && Math.round(atual.alturaDoSlot) === Math.round(alturaDoSlot) && atual.quantidade === quantidade
          ? atual
          : { alturaDoSlot, quantidade },
      );
    };
    medir();
    const observador = new ResizeObserver(medir);
    observador.observe(area);
    return () => observador.disconnect();
  }, []);

  return (
    <header className="relative isolate -mb-32 h-svh min-h-[480px] overflow-hidden bg-black">
      <div ref={areaRef} aria-hidden="true" className="absolute inset-0">
        <TrocaComCrossfade
          chave={versao}
          classeDaCamadaAtual="absolute inset-0"
          classeDaCamadaSaindo="absolute inset-0"
        >
          {medidas && urls.length > 0 && <ParedeDeCapas urls={urls} medidas={medidas} />}
        </TrocaComCrossfade>
        {/* Mesmo fade do hero de PaginaDoAnime (preto sólido embaixo, faixa escura
            do lado do texto) e sombra sob a navbar. */}
        <div className="absolute inset-0" style={{ background: GRADIENTE_DO_HERO }} />
        <div className="absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-black/70 to-transparent" />
      </div>

      {/* `pb-44`: 12 do respiro + 32 do `-mb-32`, pra o texto não ficar sob a fileira
          que espia. */}
      <div
        style={{ paddingInline: PADDING_TITULO_GRADE }}
        className="absolute inset-x-0 bottom-0 flex flex-col items-start gap-5 pb-44"
      >
        <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-bold uppercase tracking-[0.18em] text-neon-claro ring-1 ring-white/15 backdrop-blur-md">
          <Compass aria-hidden="true" strokeWidth={2.5} className="h-4 w-4" />
          Explore por assunto
        </span>

        <div>
          <h1 className="text-6xl font-extrabold tracking-tight text-white drop-shadow-lg sm:text-7xl lg:text-8xl">
            Descobrir
          </h1>
          <p className="mt-3 max-w-xl text-base font-bold text-white/75 sm:text-lg">
            {generoEscolhido
              ? `Só ${traduzirGenero(generoEscolhido).toLowerCase()}, do mais quente pro mais calmo.`
              : 'Escolha um clima e encontre o próximo anime pra maratonar.'}
          </p>
        </div>

        {generos.length > 0 && (
          <div
            role="group"
            aria-label="Filtrar por gênero"
            className="flex max-w-5xl flex-wrap gap-2"
          >
            <ChipDeGenero
              rotulo="Todos"
              ativo={generoEscolhido === null}
              aoClicar={() => aoEscolherGenero(null)}
            />
            {generos.map((genero) => (
              <ChipDeGenero
                key={genero}
                rotulo={traduzirGenero(genero)}
                ativo={generoEscolhido === genero}
                aoClicar={() => aoEscolherGenero(genero)}
              />
            ))}
          </div>
        )}

        {erro && (
          <p role="alert" className="text-sm font-bold text-red-400">
            {erro}
          </p>
        )}
      </div>
    </header>
  );
}


// A parede em si. `urls` cresce conforme a grade carrega páginas e as capas novas
// entram SEM refazer a parede: cada coluna tem uma fila de capas (`filasRef`), a
// que entra por uma borda ao reciclar um slot é a próxima da fila, e as capas novas
// vão pra frente da fila de uma coluna — aparecem nos próximos slots que entrarem,
// enquanto o que está na tela não muda. A fila gira (sai da frente, volta ao fim),
// então uma capa só repete depois de passar por todas as da coluna.
function ParedeDeCapas({ urls, medidas }) {
  const movimentoReduzido = usePrefersReducedMotion();
  const colunasRef = useRef([]);
  const urlsRef = useRef(urls);
  const filasRef = useRef(null);
  const conhecidasRef = useRef(new Set());
  const proximaColunaRef = useRef(0);

  // Capas ainda não conhecidas viram as próximas de colunas alternadas (as capas
  // são repartidas entre as colunas, então duas nunca mostram a mesma ao mesmo tempo).
  const adicionarCapas = (capas) => {
    embaralhar(capas.filter((url) => !conhecidasRef.current.has(url))).forEach((url) => {
      conhecidasRef.current.add(url);
      filasRef.current[proximaColunaRef.current % COLUNAS].unshift(url);
      proximaColunaRef.current += 1;
    });
  };

  useEffect(() => {
    urlsRef.current = urls;
    if (filasRef.current) adicionarCapas(urls);
  }, [urls]);

  useLayoutEffect(() => {
    const { alturaDoSlot, quantidade } = medidas;
    filasRef.current = Array.from({ length: COLUNAS }, () => []);
    conhecidasRef.current = new Set();
    adicionarCapas(urlsRef.current);

    // Próxima capa da fila da coluna. Com menos capas que colunas alguma fila fica
    // vazia: aí sorteia entre as conhecidas (repetição entre colunas é inevitável).
    const proxima = (coluna) => {
      const fila = filasRef.current[coluna];
      if (fila.length === 0) {
        const todas = urlsRef.current;
        return todas[Math.floor(Math.random() * todas.length)];
      }
      const url = fila.shift();
      fila.push(url);
      return url;
    };

    const estados = Array.from({ length: COLUNAS }, (_, coluna) => ({
      posicao: coluna * 0.43 * alturaDoSlot,
      sentido: coluna % 2 === 0 ? 1 : -1,
      base: null,
      janela: [],
    }));

    const desenhar = (coluna) => {
      const elemento = colunasRef.current[coluna];
      const estado = estados[coluna];
      const total = estado.posicao / alturaDoSlot;
      const base = Math.floor(total);
      if (base !== estado.base) {
        // A janela são as capas dos slots do DOM, em ordem. Subir um slot tira da frente
        // e põe uma nova no fim; descer faz o contrário. Cada slot sorteia a capa uma
        // vez só, quando entra: filas que crescem não mexem no que já está na tela.
        if (estado.base === null) {
          estado.janela = Array.from({ length: quantidade }, () => proxima(coluna));
        } else {
          const passos = Math.min(Math.abs(base - estado.base), quantidade);
          for (let i = 0; i < passos; i += 1) {
            if (base > estado.base) {
              estado.janela.shift();
              estado.janela.push(proxima(coluna));
            } else {
              estado.janela.pop();
              estado.janela.unshift(proxima(coluna));
            }
          }
        }
        estado.base = base;
        [...elemento.children].forEach((imagem, k) => {
          if (imagem.getAttribute('src') !== estado.janela[k]) imagem.src = estado.janela[k];
        });
      }
      elemento.style.transform = `translateY(${-(total - base + RESPIRO_DE_SLOTS) * alturaDoSlot}px)`;
    };

    estados.forEach((_, coluna) => desenhar(coluna));
    if (movimentoReduzido) return undefined;

    // Sem pausa fora da tela, de propósito: a parede segue andando enquanto o usuário
    // rola a grade, então ao voltar ao topo ela continua de onde estaria (pausar dava
    // a impressão de congelar e retomar).
    let quadro;
    let anterior = performance.now();
    const passoDeAnimacao = (agora) => {
      // Teto no delta: aba em segundo plano pausa o rAF e a volta não pode dar um salto.
      const delta = Math.min(agora - anterior, 100) / 1000;
      anterior = agora;
      estados.forEach((estado, coluna) => {
        estado.posicao += estado.sentido * velocidadeDaColuna(coluna) * delta;
        desenhar(coluna);
      });
      quadro = requestAnimationFrame(passoDeAnimacao);
    };
    quadro = requestAnimationFrame(passoDeAnimacao);
    return () => cancelAnimationFrame(quadro);
  }, [medidas, movimentoReduzido]);

  return (
    <div
      className="absolute -inset-x-[18%] -inset-y-[35%] flex -rotate-[14deg]"
      style={{ gap: GAP_PX }}
    >
      {Array.from({ length: COLUNAS }, (_, coluna) => (
        <div
          key={coluna}
          ref={(elemento) => {
            colunasRef.current[coluna] = elemento;
          }}
          className="flex flex-1 flex-col will-change-transform"
          style={{ gap: GAP_PX }}
        >
          {Array.from({ length: medidas.quantidade }, (_, k) => (
            <img
              key={k}
              alt=""
              decoding="async"
              className="aspect-[2/3] w-full rounded-xl bg-white/5 object-cover shadow-2xl shadow-black/60"
            />
          ))}
        </div>
      ))}
    </div>
  );
}

function ChipDeGenero({ rotulo, ativo, aoClicar }) {
  return (
    <button
      type="button"
      aria-pressed={ativo}
      onClick={aoClicar}
      className={`rounded-full px-4 py-1.5 text-sm font-bold ring-1 backdrop-blur-md transition ${
        ativo
          ? 'bg-neon text-on-neon ring-neon'
          : 'bg-white/10 text-white/85 ring-white/15 hover:bg-white/20 hover:text-white'
      }`}
    >
      {rotulo}
    </button>
  );
}
