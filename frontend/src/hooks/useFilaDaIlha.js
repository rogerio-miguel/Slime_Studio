import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

// Fila de mensagens da ilha dinâmica: a cápsula só tem UM slot de texto, então
// os sinais da página (captura, novos episódios, erro) esperam a vez aqui.
//
// Transitórios (somem sozinhos), em ordem de prioridade — o primeiro da lista
// vence:
//   1. erro     — falha não se autorresolve como um "pronto" (o card do episódio
//                 guarda o alerta, mas este é o único aviso imediato); fura a
//                 vez de qualquer outro.
//   2. pronto   — aponta um episódio específico.
//   3. novosEps — genérico ("o catálogo tem novidade").
// Contínuos (ficam enquanto o sinal durar), só aparecem com a fila de
// transitórios vazia:
//   4. status      — aponta um episódio específico.
//   5. verificando — genérico ("estou checando").
//
// A fila é da ilha, não da página: o transitório é copiado para cá quando o sinal
// aparece, então o timer da página pode expirar sem que a mensagem se perca
// enquanto um menu a segura. O tempo de exibição só corre enquanto ela está de
// fato na tela. Os contínuos não entram na fila — o texto é lido ao vivo.
//
// `retida` (menu da ilha ativo: painel de filtros, dropdown, Gerenciar, sinopse):
// nada aparece. Ao soltar, cada transitório ocupa a cápsula por vez, e o
// seguinte entra direto, sem passar por "vazio" (que fecharia a ilha).
const TRANSITORIOS = [
  { tipo: 'erro', duracaoMs: 6000, tom: 'alerta' },
  { tipo: 'pronto', duracaoMs: 5000 },
  { tipo: 'novosEps', duracaoMs: 5000 },
];
const CONTINUOS = ['status', 'verificando'];

const dadosDoTipo = (tipo) => TRANSITORIOS.find((t) => t.tipo === tipo);

const posicao = (tipo) => TRANSITORIOS.findIndex((t) => t.tipo === tipo);

// Maior prioridade primeiro; empate fica com quem chegou antes (a ordem do array).
function primeiroDaFila(fila) {
  let melhor = null;
  for (const item of fila) {
    if (!melhor || posicao(item.tipo) < posicao(melhor.tipo)) melhor = item;
  }
  return melhor;
}

// Enfileira quando o texto do sinal muda para algo novo. Dispara só nessa
// transição (não a cada render), então uma mensagem que já foi exibida e saiu
// da fila não volta enquanto a página ainda segura o mesmo texto.
function useEnfileirarAoAparecer(tipo, texto, sinaisRef, setFila) {
  useEffect(() => {
    if (!texto) return;
    const id = `${tipo}:${texto}`;
    setFila((fila) =>
      fila.some((item) => item.id === id)
        ? fila
        : [...fila, { id, tipo, texto, aoClicar: sinaisRef.current[tipo]?.aoClicar }],
    );
  }, [tipo, texto, sinaisRef, setFila]);
}

// `sinais`: { erro, pronto, novosEps, status, verificando }, cada um
// `{ texto: string|null, aoClicar?: () => void }`.
// Devolve `{ texto, tom, aoClicar } | null`.
export function useFilaDaIlha({ sinais, retida }) {
  const [fila, setFila] = useState([]);
  const sinaisRef = useRef(sinais);
  useLayoutEffect(() => {
    sinaisRef.current = sinais;
  });

  useEnfileirarAoAparecer('erro', sinais.erro?.texto, sinaisRef, setFila);
  useEnfileirarAoAparecer('pronto', sinais.pronto?.texto, sinaisRef, setFila);
  useEnfileirarAoAparecer('novosEps', sinais.novosEps?.texto, sinaisRef, setFila);

  const proximo = useMemo(() => primeiroDaFila(fila), [fila]);
  const exibindo = retida ? null : proximo;

  useEffect(() => {
    if (!exibindo) return undefined;
    const temporizador = setTimeout(
      () => setFila((atual) => atual.filter((item) => item.id !== exibindo.id)),
      dadosDoTipo(exibindo.tipo).duracaoMs,
    );
    return () => clearTimeout(temporizador);
  }, [exibindo]);

  const dispensar = useCallback((item) => {
    item.aoClicar?.();
    setFila((atual) => atual.filter((outro) => outro.id !== item.id));
  }, []);

  if (retida) return null;
  if (exibindo) {
    return {
      texto: exibindo.texto,
      tom: dadosDoTipo(exibindo.tipo).tom,
      aoClicar: () => dispensar(exibindo),
    };
  }
  const tipoContinuo = CONTINUOS.find((tipo) => sinais[tipo]?.texto);
  if (!tipoContinuo) return null;
  return { texto: sinais[tipoContinuo].texto, aoClicar: sinais[tipoContinuo].aoClicar };
}
