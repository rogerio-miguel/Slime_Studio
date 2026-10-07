const MS_POR_DIA = 86_400_000;

// "Hoje"/"Amanhã" pelo dia LOCAL (meia-noite a meia-noite), não por diferença
// de 24h — um episódio à 01h de amanhã não é "daqui a 1 dia" às 23h de hoje.
// Qualquer outro dia devolve `null` e quem chama mostra a data. Compartilhado
// pela marca do dia de "Próximas estreias" e pelo próximo episódio do carrossel.
export function rotuloHojeAmanha(data) {
  const inicioHoje = new Date();
  inicioHoje.setHours(0, 0, 0, 0);
  const inicioDoDia = new Date(data);
  inicioDoDia.setHours(0, 0, 0, 0);
  const dias = Math.round((inicioDoDia - inicioHoje) / MS_POR_DIA);
  if (dias === 0) return 'Hoje';
  if (dias === 1) return 'Amanhã';
  return null;
}
