import { useState } from 'react';
import MenuDeAcoes from './MenuDeAcoes.jsx';
import { aplicarTema, lerTemaSalvo, salvarTema, TEMAS } from '../temas.js';

// Ícone de cada item do menu: a bolinha na cor do tema (não na do tema ativo,
// por isso não usa `bg-neon`). Criado uma vez por tema, fora do render.
function criarPontoDeCor(cor) {
  function PontoDeCor({ className }) {
    return <span aria-hidden="true" className={`${className} rounded-full`} style={{ backgroundColor: cor }} />;
  }
  return PontoDeCor;
}
const PONTOS = Object.fromEntries(TEMAS.map((tema) => [tema.id, criarPontoDeCor(tema.cor)]));

// O gatilho é o `children` (o logo da navbar). O tema salvo é aplicado em
// `main.jsx`, antes do primeiro render, pra valer também nas páginas sem
// navbar (player).
export default function SeletorDeTema({ children, classeDoContainer, classeDoGatilho }) {
  const [atual, setAtual] = useState(lerTemaSalvo);

  const itens = TEMAS.map((tema) => ({
    chave: tema.id,
    rotulo: tema.nome,
    Icone: PONTOS[tema.id],
    marcado: tema.id === atual,
    aoClicar: () => {
      setAtual(tema.id);
      aplicarTema(tema.id);
      salvarTema(tema.id);
    },
  }));

  return (
    <MenuDeAcoes
      itens={itens}
      rotuloGatilho="Tema do app"
      gatilho={children}
      dica="Trocar tema"
      ancoragem="centro"
      larguraMinima="min-w-[10rem]"
      classeDoContainer={classeDoContainer}
      classeGatilho={() => classeDoGatilho}
    />
  );
}
