import { useId } from 'react';

// Região que a cápsula ganha ao crescer para baixo e virar o painel de ordem e
// filtros da Galeria. Mesma casca de `RegiaoDaSinopse.jsx` — o contêiner `grid`
// anima a altura por `0fr -> 1fr` e `.sinopse-ilha-conteudo` (index.css) cuida do
// fade e da rolagem —, mas aqui há controles: clicar dentro NÃO fecha (fecha a
// cortina, o Esc, o gatilho do cabeçalho ou o Remover) e o Tab circula entre os
// botões (hooks/useSinopseNaCapsula.js, `interativo`). O cabeçalho (link +
// gatilho) fica no lugar, em BarraDeNavegacao.jsx.
//
// Contrato de `painelDeFiltros` (paginas/Galeria.jsx):
//   aberto, aoAbrir, aoFechar  — ciclo do painel (`aoFechar` só depois da animação)
//   resumo                     — texto do gatilho fechado ("Todos · A–Z")
//   filtrosAtivos, aoLimpar    — habilita "Limpar tudo" (zera filtro, gêneros e ordem)
//   selecaoAtiva, aoLimparSelecao,
//   ordemSalvaAtiva, aoLimparOrdem — usados pelo link "Meu Catálogo" da navbar
//                                (BarraDeNavegacao.jsx), em degraus: 1º clique
//                                limpa filtro e gêneros (guarda a ordem salva), o
//                                2º volta a ordem ao padrão
//   aoRemover                  — liga o modo de remoção (o painel fecha sozinho)
//   total                      — "70 animes", no rodapé
//   ordenacao                  — { opcoes: [{valor, rotulo}], valor, aoMudar } | null
//   generos                    — { opcoes: [{valor, rotulo, contagem}], selecionados:
//                                Set, aoAlternar } | null
// `ordenacao`/`generos` null = a seção não aparece. `filtro` é o mesmo
// `{ opcoes, valor, aoMudar }` do filtro da cápsula.

function Opcao({ ativa, apagada = false, onClick, children, contagem }) {
  return (
    <button
      type="button"
      aria-pressed={ativa}
      disabled={apagada}
      onClick={onClick}
      className={`inline-flex h-8 shrink-0 cursor-pointer items-center whitespace-nowrap rounded-full border px-4 text-[14px] font-semibold outline-none transition-colors focus-visible:border-white/70 disabled:cursor-not-allowed disabled:opacity-35 motion-reduce:transition-none ${
        ativa
          ? 'border-neon bg-neon-soft text-white'
          : 'border-white/[0.12] text-ink-muted enabled:hover:border-white/30 enabled:hover:text-white'
      }`}
    >
      {children}
      {contagem != null && <span className="ml-2 font-medium opacity-60">{contagem}</span>}
    </button>
  );
}

function Secao({ titulo, children }) {
  const idTitulo = useId();
  return (
    <section aria-labelledby={idTitulo} className="py-4 first:pt-1">
      <h2
        id={idTitulo}
        className="mb-3 text-[11px] font-bold uppercase tracking-[0.14em] text-ink-muted"
      >
        {titulo}
      </h2>
      <div className="flex flex-wrap gap-2">{children}</div>
    </section>
  );
}

const CLASSE_BOTAO_RODAPE =
  'inline-flex h-8 cursor-pointer items-center whitespace-nowrap text-sm font-semibold outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-40 motion-reduce:transition-none';

export default function RegiaoDoPainelDeFiltros({ painel, painelDeFiltros, filtro }) {
  const { ordenacao, generos, filtrosAtivos, total, aoLimpar, aoRemover } = painelDeFiltros;
  return (
    <div
      className="grid"
      style={{
        gridTemplateRows: painel.expandida ? '1fr' : '0fr',
        ...painel.estiloGrade,
      }}
    >
      <div
        ref={painel.regiaoRef}
        role="dialog"
        aria-modal="false"
        aria-label="Ordem e filtros do catálogo"
        tabIndex={-1}
        data-visivel={painel.expandida ? '' : undefined}
        data-rolavel={painel.rolavel ? '' : undefined}
        // Desconta o cabeçalho (fora da região) e a margem de cima/baixo.
        style={{ maxHeight: 'calc(100dvh - 6.5rem)' }}
        className="sinopse-ilha-conteudo text-left text-white outline-none"
      >
        <div
          style={{ width: painel.rolavel ? undefined : painel.larguraConteudo }}
          className="divide-y divide-white/10 px-1.5 pb-3"
        >
          {ordenacao && (
            <Secao titulo="Ordenar por">
              {ordenacao.opcoes.map((opcao) => (
                <Opcao
                  key={opcao.valor}
                  ativa={opcao.valor === ordenacao.valor}
                  onClick={() => ordenacao.aoMudar(opcao.valor)}
                >
                  {opcao.rotulo}
                </Opcao>
              ))}
            </Secao>
          )}
          <Secao titulo="Filtrar">
            {filtro.opcoes.map((opcao) => (
              <Opcao
                key={opcao.valor}
                ativa={opcao.valor === filtro.valor}
                onClick={() => filtro.aoMudar(opcao.valor)}
              >
                {opcao.rotulo}
              </Opcao>
            ))}
          </Secao>
          {generos && generos.opcoes.length > 0 && (
            <Secao titulo="Gênero">
              {generos.opcoes.map((opcao) => {
                const ativa = generos.selecionados.has(opcao.valor);
                return (
                  <Opcao
                    key={opcao.valor}
                    ativa={ativa}
                    // Marcado nunca apaga (senão não dá pra desmarcar); os outros
                    // apagam quando deixariam a grade vazia.
                    apagada={!ativa && opcao.contagem === 0}
                    contagem={opcao.contagem}
                    onClick={() => generos.aoAlternar(opcao.valor)}
                  >
                    {opcao.rotulo}
                  </Opcao>
                );
              })}
            </Secao>
          )}
          <div className="flex items-center justify-between gap-4 pt-3">
            <button
              type="button"
              disabled={filtrosAtivos === 0}
              onClick={aoLimpar}
              className={`${CLASSE_BOTAO_RODAPE} text-ink-muted enabled:hover:text-white`}
            >
              Limpar tudo
            </button>
            <div className="flex items-center gap-4">
              <button
                type="button"
                onClick={aoRemover}
                className={`${CLASSE_BOTAO_RODAPE} font-bold text-white hover:text-red-300 focus-visible:text-red-300`}
              >
                Remover
              </button>
              <span role="status" className="text-sm font-semibold text-ink-muted">
                {total}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
