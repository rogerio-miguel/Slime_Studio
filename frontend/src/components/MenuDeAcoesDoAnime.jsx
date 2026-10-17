import { Check, Image as IconeImagem, Trash2 } from 'lucide-react';
import MenuDeAcoes from './MenuDeAcoes.jsx';
import { FUNDO_DOS_CONTROLES } from './painelFlutuante.js';

// Menu de ações da página do anime (`paginas/PaginaDoAnime.jsx`) — "Marcar
// como assistido"/"Remover do catálogo" saíram de botões
// soltos na barra e viraram itens deste menu, cujo gatilho (ícone de kebab)
// mora ao lado do alternador grade/lista, na barra de controles
// (botão `h-8 w-8` com o fundo dos menus, sem borda). Menu ancorado à DIREITA (`right-0`, não `left-0` como
// `SeletorDeTemporada`) porque o gatilho é o item mais à direita da barra —
// abrir pra esquerda evita vazar a viewport.
//
// Lógica de acessibilidade/interação (foco, teclado, clique fora) mora em
// `MenuDeAcoes.jsx` (extraído quando `components/CartaoContinuarAssistindo.jsx`
// ganhou o mesmo padrão de menu, pedido do usuário) — este componente só
// monta a lista de itens (com a segunda linha que diz o efeito de cada um) e a
// skin do gatilho.
export default function MenuDeAcoesDoAnime({
  aoTrocarBanner,
  aoMarcarAssistidos,
  marcandoAssistidos,
  tudoAssistido,
  pendentes,
  totalNumerado,
  temporadasNoCatalogo,
  aoRemover,
}) {
  // Segunda linha de "Marcar como assistido": o efeito com o número real. Sem
  // episódio numerado ainda (carregando) não há o que dizer, então some.
  const descricaoDeMarcar =
    totalNumerado > 0
      ? tudoAssistido
        ? `Os ${totalNumerado} episódios estão assistidos`
        : `${pendentes} ${pendentes === 1 ? 'episódio pendente' : 'episódios pendentes'}`
      : undefined;

  const itens = [
    {
      chave: 'trocar-banner',
      rotulo: 'Trocar banner',
      descricao: 'Escolher outra imagem de fundo',
      Icone: IconeImagem,
      aoClicar: aoTrocarBanner,
    },
    {
      chave: 'marcar-assistido',
      rotulo: marcandoAssistidos
        ? 'Marcando…'
        : tudoAssistido
          ? 'Tudo assistido'
          : 'Marcar tudo como assistido',
      descricao: descricaoDeMarcar,
      Icone: Check,
      aoClicar: aoMarcarAssistidos,
      desabilitado: marcandoAssistidos || tudoAssistido,
    },
    {
      chave: 'remover',
      rotulo: 'Remover do catálogo',
      descricao:
        temporadasNoCatalogo > 1
          ? `Apaga as ${temporadasNoCatalogo} temporadas, episódios e capturas`
          : 'Apaga episódios e capturas deste anime',
      separadorAntes: true,
      Icone: Trash2,
      aoClicar: aoRemover,
      destrutivo: true,
    },
  ];

  return (
    <MenuDeAcoes
      itens={itens}
      rotuloGatilho="Mais ações"
      larguraMinima="min-w-[21rem]"
      classeGatilho={(aberto) =>
        `flex h-8 w-8 items-center justify-center rounded-[10px] ${FUNDO_DOS_CONTROLES} outline-none transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-neon ${
          aberto ? 'text-white' : 'text-ink-muted hover:text-white'
        }`
      }
    />
  );
}
