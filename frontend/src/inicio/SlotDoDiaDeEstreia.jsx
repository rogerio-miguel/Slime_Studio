import { rotuloHojeAmanha } from './rotuloHojeAmanha.js';

const fmtDiaDaSemana = new Intl.DateTimeFormat('pt-BR', { weekday: 'short' });
const fmtDiaEMes = new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'short' });
const fmtMes = new Intl.DateTimeFormat('pt-BR', { month: 'short' });

// Envolve um card de "Próximas estreias" com a marca do dia ACIMA dele: uma linha
// que atravessa todos os cards do mesmo dia e, no primeiro deles, o dia grande +
// "mês · dia da semana". Os cards continuam slots iguais da `FileiraDeCards`
// (setas e bolinhas seguem certas); o agrupamento por dia é só visual, feito
// por `primeiro`/`ultimo` (posição do card dentro do seu dia). `data: null` =
// sem data definida ("A confirmar"). Em "Hoje" só a palavra, sem o número do dia
// (como o rótulo do dia em `ListaDeLancamentos.jsx`).
//
// A linha de quem NÃO é o último do dia vai até o slot vizinho (`-mr-4`, o
// `gap-x-4` da trilha), pra ela ser contínua dentro do dia e interrompida entre
// dias. O rótulo tem altura fixa pra todos os cards alinharem pela linha.
// Só as pontas de FORA do dia são arredondadas (esquerda no primeiro, direita no
// último): arredondar todo segmento deixava um corte na junção entre os cards.
export default function SlotDoDiaDeEstreia({ data, primeiro, ultimo, children }) {
  const relativo = data ? rotuloHojeAmanha(data) : null;
  const hoje = relativo === 'Hoje';
  return (
    <div>
      <div className="flex h-14 items-end pb-2">
        {primeiro &&
          (hoje ? (
            <h3 className="whitespace-nowrap text-4xl font-extrabold leading-none text-white">
              Hoje
            </h3>
          ) : relativo ? (
            <h3 className="flex items-baseline gap-2 whitespace-nowrap">
              <span className="text-4xl font-extrabold leading-none text-white">{relativo}</span>
              <span className="text-sm font-semibold tracking-wider text-ink-muted">
                {fmtDiaEMes.format(data).replace('.', '')}
              </span>
            </h3>
          ) : data ? (
            <h3 className="flex items-baseline gap-2 whitespace-nowrap">
              <span className="text-4xl font-extrabold leading-none tabular-nums text-white">
                {data.getDate()}
              </span>
              <span className="text-sm font-semibold tracking-wider text-ink-muted">
                {`${fmtMes.format(data).replace('.', '')} · ${fmtDiaDaSemana
                  .format(data)
                  .replace('.', '')}`}
              </span>
            </h3>
          ) : (
            <h3 className="whitespace-nowrap text-xl font-extrabold leading-none text-white">
              A confirmar
            </h3>
          ))}
      </div>
      <div
        aria-hidden="true"
        className={`mb-4 h-1 ${primeiro ? 'rounded-l-full' : ''} ${ultimo ? 'rounded-r-full' : '-mr-4'} ${
          hoje ? 'bg-neon' : data ? 'bg-white/25' : 'bg-white/10'
        }`}
      />
      {children}
    </div>
  );
}
