import { useLayoutEffect, useRef, useState } from 'react';
import { usePrefersReducedMotion } from './usePrefersReducedMotion.js';

// Troca de conteúdo em crossfade, sem passar pelo preto: quando `chave` muda, o
// conteúdo anterior (congelado como estava no último commit) fica numa camada que
// esmaece enquanto a nova entra por cima. O conteúdo atual é o `children` vivo; só o
// que está saindo é congelado. As camadas são irmãs com `key={chave}`, então a
// instância da que sai é a MESMA de antes (nada remonta, a parede de capas não volta
// ao início). `classeDaCamadaSaindo` posiciona a camada que sai sobre a nova (ela
// deixa o fluxo normal); `classeDaCamadaAtual` é o layout da camada atual. A
// duração (`crossfade-*` em index.css) e DURACAO_DO_CROSSFADE_MS precisam bater.
export const DURACAO_DO_CROSSFADE_MS = 500;

export default function TrocaComCrossfade({
  chave,
  classeDaCamadaAtual = '',
  classeDaCamadaSaindo = '',
  children,
}) {
  const movimentoReduzido = usePrefersReducedMotion();
  const [saindo, setSaindo] = useState([]);
  const ultimoRef = useRef({ chave, conteudo: children });

  // Layout effect: `children` é novo a cada render, então roda a cada commit e mantém
  // `ultimoRef` em dia; só mexe em `saindo` quando a `chave` muda. É layout effect
  // porque a camada que sai precisa existir antes do primeiro paint da nova (senão
  // haveria um quadro só com o fundo). O temporizador não é limpo no cleanup de propósito: o efeito
  // reroda a cada render e cancelaria a remoção da camada.
  useLayoutEffect(() => {
    const anterior = ultimoRef.current;
    ultimoRef.current = { chave, conteudo: children };
    if (anterior.chave === chave || movimentoReduzido) return;
    setSaindo((atuais) => [...atuais, anterior]);
    setTimeout(
      () => setSaindo((atuais) => atuais.filter((camada) => camada.chave !== anterior.chave)),
      DURACAO_DO_CROSSFADE_MS,
    );
  }, [chave, children, movimentoReduzido]);

  // Um array só, com `key`: a camada atual de ontem é a que sai de hoje, mesma instância.
  return [
    ...saindo.map((camada) => (
      <div
        key={camada.chave}
        aria-hidden="true"
        inert
        className={`crossfade-sai ${classeDaCamadaSaindo}`}
      >
        {camada.conteudo}
      </div>
    )),
    <div key={chave} className={`crossfade-entra ${classeDaCamadaAtual}`}>
      {children}
    </div>,
  ];
}
