// "Verificado há 2 h · próxima: em 4 h · motivo" — estado da sondagem de fonte
// (`GET /api/admin/verificacoes`). Informação de diagnóstico: sem registro (anime
// nunca sondado) ou com a consulta falha, não renderiza nada em vez de poluir a
// página com um erro que não impede o uso.

const MOTIVO_POR_RESULTADO = {
  ok: 'fonte consultada',
  nao_encontrado: 'não encontrado na fonte',
  precisa_sessao: 'aguardando renovar a sessão do site',
  site_indisponivel: 'site indisponível',
  ambiguo: 'fonte ambígua, aguarda sua escolha',
  erro: 'falha ao consultar a fonte',
};

function duracao(ms) {
  const minutos = Math.max(1, Math.round(ms / 60_000));
  if (minutos < 60) return `${minutos} min`;
  const horas = Math.round(minutos / 60);
  if (horas < 24) return `${horas} h`;
  return `${Math.round(horas / 24)} d`;
}

function quando(iso) {
  const diferenca = new Date(iso) - Date.now();
  return diferenca > 0 ? `em ${duracao(diferenca)}` : 'na próxima passada';
}

export default function LinhaDeVerificacao({ verificacao }) {
  if (!verificacao) return null;
  const motivo = MOTIVO_POR_RESULTADO[verificacao.ultimo_resultado] ?? verificacao.ultimo_resultado;
  const partes = [
    `Verificado há ${duracao(Date.now() - new Date(verificacao.ultima_tentativa_em))}`,
    `próxima: ${quando(verificacao.proxima_em)}`,
    motivo,
  ];
  return (
    <p className="text-xs text-ink-muted" title={verificacao.detalhe ?? undefined}>
      {partes.join(' · ')}
    </p>
  );
}
