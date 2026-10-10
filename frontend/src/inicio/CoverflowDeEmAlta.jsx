import { useRef, useState } from 'react';
import { ConteudoDeDestaque } from './CarrosselDestaques.jsx';
import IconeSeta from './IconeSeta.jsx';
import { reduzirImagemTmdb } from '../components/reduzirImagemTmdb.js';
import { CLASSES_POR_PAGINA } from './tamanhoDeCard.js';

// Com 10 títulos a roda tem 5 posições de um lado e 4 do outro; a 5ª do lado
// longo fica escondida pra os dois lados mostrarem a mesma quantidade (4).
const VIZINHOS_VISIVEIS = 4;
// Arrasto horizontal mínimo (px) pra contar como troca em vez de clique.
const ARRASTO_MINIMO_PX = 50;

// Top 10 em coverflow contínuo: o pôster em foco fica grande no centro e os
// vizinhos giram pra trás em perspectiva, de ponta a ponta (os das bordas saem
// pela lateral da tela). A roda dá a volta (depois do 10º vem o
// 1º), então nenhum lado fica vazio no 1º título. Abaixo do coverflow vai o MESMO
// bloco de conteúdo do hero (`ConteudoDeDestaque` compacto: título,
// sinopse, "Ler sinopse completa" e CTA), centralizado, com a pílula "#N em alta" no topo.
//
// A geometria (perspectiva, deslocamento, rotação) mora em `.coverflow*` no
// index.css e é dirigida por três variáveis por item: `--o` (posição relativa
// ao foco), `--a` (|--o|) e `--s` (sinal). Só `transform`/`opacity` mudam, então
// a troca roda no compositor. Não há troca automática: quem escolhe o título é o
// usuário (setas, ← →, arrasto ou clique num vizinho; o pôster central não abre o anime).
//
// Teclado: o coverflow inteiro é um único ponto de foco (`tabIndex=0`) e ← → giram a
// roda; os pôsteres ficam fora da ordem de Tab (`tabIndex=-1`) porque o item em
// foco troca a cada giro e o botão "Assistir agora"/título do bloco de baixo já
// é o caminho por teclado pro anime.
export default function CoverflowDeEmAlta({
  itens,
  chaveDoItem,
  aoAtivar,
  desabilitado,
  aoAbrirSinopse,
}) {
  const [foco, setFoco] = useState(0);
  const arrastoInicialRef = useRef(null);
  const arrastouRef = useRef(false);
  if (itens.length === 0) return null;

  const total = itens.length;
  // Os feeds podem encolher entre renders (refetch); o módulo mantém o índice
  // dentro da lista.
  const indiceAtual = foco % total;
  const atual = itens[indiceAtual];
  const capaAtual = reduzirImagemTmdb(atual.capa_url);
  // Menor caminho no círculo: de -total/2 até total/2 - 1.
  const deslocamento = (indice) =>
    ((((indice - indiceAtual + Math.floor(total / 2)) % total) + total) % total) -
    Math.floor(total / 2);
  const girar = (passo) => setFoco((indiceAtual + passo + total) % total);

  const classesSeta =
    'absolute inset-y-0 z-20 flex w-[3.7%] cursor-pointer items-center justify-center ' +
    'text-white/60 outline-none transition-colors duration-300 hover:text-neon focus-visible:text-neon ' +
    'motion-reduce:transition-none';

  return (
    <div>
      <div className={`coverflow-raiz ${CLASSES_POR_PAGINA.pequeno}`}>
        <div
          className="coverflow group/coverflow relative outline-none focus-visible:ring-2 focus-visible:ring-neon"
          role="group"
          aria-roledescription="carrossel"
          aria-label="Top 10 em alta"
          tabIndex={0}
          onKeyDown={(evento) => {
            if (evento.key === 'ArrowLeft') {
              evento.preventDefault();
              girar(-1);
            } else if (evento.key === 'ArrowRight') {
              evento.preventDefault();
              girar(1);
            }
          }}
          onPointerDown={(evento) => {
            arrastoInicialRef.current = evento.clientX;
            arrastouRef.current = false;
          }}
          onPointerUp={(evento) => {
            const inicio = arrastoInicialRef.current;
            arrastoInicialRef.current = null;
            if (inicio == null || Math.abs(evento.clientX - inicio) < ARRASTO_MINIMO_PX) return;
            arrastouRef.current = true;
            girar(evento.clientX < inicio ? 1 : -1);
          }}
        >
          {capaAtual && (
            <img
              key={chaveDoItem(atual)}
              src={capaAtual}
              alt=""
              aria-hidden="true"
              className="coverflow-brilho"
            />
          )}
          {itens.map((item, indice) => {
            const posicao = deslocamento(indice);
            const distancia = Math.abs(posicao);
            const noCentro = posicao === 0;
            const visivel = distancia <= VIZINHOS_VISIVEIS;
            const capa = reduzirImagemTmdb(item.capa_url);
            const titulo = item.titulo_romaji || item.titulo_ingles;
            return (
              <button
                key={chaveDoItem(item)}
                type="button"
                tabIndex={-1}
                aria-hidden={visivel ? undefined : 'true'}
                aria-current={noCentro ? 'true' : undefined}
                data-fora={visivel ? undefined : ''}
                aria-label={noCentro ? titulo : `Mostrar ${titulo}`}
                style={{ '--o': posicao, '--a': distancia, '--s': Math.sign(posicao) }}
                onClick={() => {
                  if (arrastouRef.current) {
                    arrastouRef.current = false;
                    return;
                  }
                  // O pôster central não abre o anime: quem leva a ele é o bloco de texto.
                  if (!noCentro) setFoco(indice);
                }}
                className={`coverflow-item outline-none ${noCentro ? 'cursor-default' : 'cursor-pointer'}`}
              >
                <span
                  style={item.capa_cor ? { backgroundColor: item.capa_cor } : undefined}
                  className="coverflow-capa block h-full w-full overflow-hidden rounded-2xl bg-surface"
                >
                  {capa && (
                    <img
                      src={capa}
                      alt=""
                      draggable={false}
                      loading={distancia <= 3 ? undefined : 'lazy'}
                      className="h-full w-full object-cover"
                    />
                  )}
                </span>
              </button>
            );
          })}

          {/* Setas no gutter: geometria e cor das fileiras. Aparecem quando o mouse
              está sobre um pôster (não no coverflow todo, que inclui o reflexo e o
              vazio entre os pôsteres), sobre a própria zona ou com foco; seguem
              alcançáveis por Tab mesmo invisíveis. */}
          <button
            type="button"
            onClick={() => girar(-1)}
            aria-label="Anterior: Top 10 em alta"
            className={`left-0 opacity-0 group-has-[.coverflow-item:hover]/coverflow:opacity-100 hover:opacity-100 focus-visible:opacity-100 ${classesSeta}`}
          >
            <IconeSeta direcao="esquerda" />
          </button>
          <button
            type="button"
            onClick={() => girar(1)}
            aria-label="Próximo: Top 10 em alta"
            className={`right-0 opacity-0 group-has-[.coverflow-item:hover]/coverflow:opacity-100 hover:opacity-100 focus-visible:opacity-100 ${classesSeta}`}
          >
            <IconeSeta direcao="direita" />
          </button>
        </div>
      </div>

      {/* Altura mínima = a do conteúdo completo (pílula, título, alternativo,
          sinopse, "Ler sinopse" e botão): sem ela a posição do que vem abaixo e
          do próprio bloco mudaria conforme o título tenha ou não sinopse/alternativo.
          Conteúdo alinhado ao topo, então a pílula nunca sai do lugar.
          `items-center!`/`text-center` centralizam o bloco (que nasce alinhado à
          esquerda, como no hero). */}
      <div aria-live="polite" className="min-h-[18.125rem]">
        <ConteudoDeDestaque
          compacto
          item={atual}
          rank={indiceAtual + 1}
          className="items-center! text-center"
          aoAbrirSinopse={aoAbrirSinopse}
          aoMaterializar={aoAtivar}
          materializando={desabilitado}
        />
      </div>
    </div>
  );
}
