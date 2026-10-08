import { useEffect, useState } from 'react';
import { DivisorDaIlha } from './ElementosDaIlha.jsx';
import ConteudoGerenciarIlha from './ConteudoGerenciarIlha.jsx';
import { DURACAO_ABRE_MS } from './coreografiaDaIlha.js';

const ENTRADA = 'flex items-center gap-2 animate-ilha-conteudo motion-reduce:animate-none';

// Parte da cápsula que cresce ao lado do link: divisor + o conteúdo da vez.
// Quem ocupa o conteúdo, por prioridade: modo Gerenciar > `modoDaIlha` (ex.:
// "Trocar banner") > `seletor` (filtro/seções/mensagem, inclusive "Sinopse").
//
// A largura anima até a medida NATURAL do conteúdo (`largura`, medida por quem
// chama): um teto genérico de `max-width` parava de crescer ao passar da largura
// real e o resto da duração ficava parado ("trepidação"), e trocar de conteúdo
// pulava sem transição. O wrapper fica montado mesmo fechado (gate de montagem
// estável, `temConteudo` no pai) — montar já aberto não teria transição de
// largura — e `inert` tira o conteúdo do foco/leitor de tela enquanto fechado.
// `overflow-hidden` sempre: o menu do dropdown é `absolute` com ancestral
// posicionado na cápsula, fora daqui, então o recorte não o corta.
//
// Largura sem transição (`acompanhaORotulo`) quando a ilha JÁ está aberta mostrando
// o seletor: aí só o texto do rótulo muda e ele mesmo anima a largura (rolagem,
// SeletorEmMenu.jsx). Transicionar o contêiner por cima perseguia uma medida que
// muda a cada quadro, reiniciando a transição: a cápsula só começava a mexer
// depois do texto terminar e levava mais 450ms ("o texto troca e depois a ilha
// diminui"). Só liga depois da abertura assentar, senão cortaria a transição de
// abrir; trocar de modo (Gerenciar, sinopse...) volta a transicionar.
export default function ConteudoDaIlha({
  aberta,
  estilo,
  largura,
  medidorRef,
  seletor,
  gerenciar,
  gerenciando,
  modoDaIlha,
  modoNaIlha,
  larguraSegueOConteudo = false,
}) {
  const emSeletor = aberta && !modoNaIlha;
  const [assentada, setAssentada] = useState(false);
  useEffect(() => {
    if (!emSeletor) return undefined;
    const temporizador = setTimeout(() => setAssentada(true), DURACAO_ABRE_MS + 50);
    return () => {
      clearTimeout(temporizador);
      setAssentada(false);
    };
  }, [emSeletor]);
  const acompanhaORotulo = larguraSegueOConteudo || (emSeletor && assentada);
  return (
    <div
      inert={!aberta || undefined}
      style={{
        ...estilo,
        width: aberta ? largura : 0,
        // Com o painel de filtros ancorado a cápsula tem largura própria, então o
        // contêiner só precisa acompanhar o rótulo que rola; transicionar a largura
        // aqui o deixava atrasado e, ao devolver a cápsula ao fluxo, ela dava um
        // salto de alguns px.
        ...(acompanhaORotulo ? { transitionDuration: '0ms' } : null),
      }}
      className={`overflow-hidden transition-[width,opacity,margin-left] motion-reduce:transition-none ${
        aberta ? 'ml-2 opacity-100' : 'ml-0 opacity-0'
      }`}
    >
      <div ref={medidorRef} className="flex w-max items-center gap-2">
        <DivisorDaIlha />
        {/* O seletor fica montado em todos os modos: guarda estado (largura do
            rótulo, aberto) que um desmonte jogaria fora. `hidden` o tira do
            layout, então o medidor só conta o conteúdo visível; sair de
            `display:none` reinicia o fade de entrada. */}
        <div className={`${ENTRADA} ${modoNaIlha ? 'hidden' : ''}`}>{seletor}</div>
        {gerenciando && (
          // `key={fase}`: cada fase reentra com fade enquanto a largura anima.
          <div key={gerenciar.fase} className={ENTRADA}>
            <ConteudoGerenciarIlha gerenciar={gerenciar} />
          </div>
        )}
        {!gerenciando && modoDaIlha && <div className={ENTRADA}>{modoDaIlha}</div>}
      </div>
    </div>
  );
}
