import { BotaoDaIlha, DivisorDaIlha } from './ElementosDaIlha.jsx';

// Barra do modo Gerenciar (seleção e remoção em lote do catálogo,
// paginas/Galeria.jsx): contagem, selecionar todos, remover com a confirmação
// dentro da própria ilha e o resultado/erro da remoção.
// Contrato de `gerenciar`: { fase: 'inativo' | 'selecionando' | 'confirmando' |
// 'removendo' | 'concluido' | 'erro', qtdSelecionados, textoConfirmacao,
// resultado, aoSelecionarTodos, aoPedirRemocao, aoCancelarRemocao,
// aoConfirmarRemocao, aoSair }.
export default function ConteudoGerenciarIlha({ gerenciar }) {
  const { fase, qtdSelecionados, textoConfirmacao, resultado } = gerenciar;
  const plural = qtdSelecionados === 1 ? 'selecionado' : 'selecionados';
  const classeTexto = 'whitespace-nowrap text-[18px] font-semibold';
  if (fase === 'confirmando') {
    return (
      <>
        <span role="alert" className={`${classeTexto} text-white`}>
          {textoConfirmacao}
        </span>
        <DivisorDaIlha />
        <BotaoDaIlha perigo onClick={gerenciar.aoConfirmarRemocao}>
          Remover
        </BotaoDaIlha>
        <DivisorDaIlha />
        <BotaoDaIlha onClick={gerenciar.aoCancelarRemocao}>Cancelar</BotaoDaIlha>
      </>
    );
  }
  if (fase === 'removendo') {
    return (
      <span role="status" className={`${classeTexto} text-ink-muted`}>
        Removendo…
      </span>
    );
  }
  if (fase === 'concluido' || fase === 'erro') {
    return (
      <>
        <span
          role={fase === 'erro' ? 'alert' : 'status'}
          className={`${classeTexto} ${fase === 'erro' ? 'text-amber-300' : 'text-white'}`}
        >
          {resultado}
        </span>
        {fase === 'erro' && (
          <>
            <DivisorDaIlha />
            <BotaoDaIlha onClick={gerenciar.aoSair}>Fechar</BotaoDaIlha>
          </>
        )}
      </>
    );
  }
  return (
    <>
      <span role="status" className={`${classeTexto} text-white`}>
        {qtdSelecionados} <span className="text-ink-muted">{plural}</span>
      </span>
      <DivisorDaIlha />
      <BotaoDaIlha onClick={gerenciar.aoSelecionarTodos}>Selecionar todos</BotaoDaIlha>
      <DivisorDaIlha />
      <BotaoDaIlha perigo disabled={qtdSelecionados === 0} onClick={gerenciar.aoPedirRemocao}>
        {qtdSelecionados > 0 ? `Remover (${qtdSelecionados})` : 'Remover'}
      </BotaoDaIlha>
      <DivisorDaIlha />
      <BotaoDaIlha onClick={gerenciar.aoSair}>Cancelar</BotaoDaIlha>
    </>
  );
}
