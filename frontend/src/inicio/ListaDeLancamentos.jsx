import { useState } from 'react';
import AtivadorDeAnime from './AtivadorDeAnime.jsx';
import { traduzirGenero } from './generos.js';
import { PADDING_TITULO } from './tamanhoDeCard.js';

const fmtHora = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' });
const fmtDiaDaSemana = new Intl.DateTimeFormat('pt-BR', { weekday: 'long' });
const fmtDiaEMes = new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'short' });
const MS_POR_DIA = 86_400_000;

// Mesmo visual do CTA do carrossel (`CLASSE_BOTAO_HERO`: pílula clara, texto
// escuro), numa escala menor — o do carrossel cresce até `lg:h-14 lg:text-xl`,
// grande demais pra um "Mostrar mais".
const CLASSE_BOTAO_MOSTRAR_MAIS =
  'inline-flex h-12 cursor-pointer items-center gap-2 rounded-xl bg-white px-8 font-bold text-[#17171b] outline-none transition hover:brightness-90 focus-visible:ring-2 focus-visible:ring-neon focus-visible:ring-offset-2 focus-visible:ring-offset-black motion-reduce:transition-none';

// 8 = 4 linhas em duas colunas: cabe sem alongar a Home; o resto do feed
// (até o corte do backend) fica atrás de "Mostrar mais".
const LIMITE_INICIAL = 8;

// Dias entre o dia LOCAL de `data` e hoje (meia-noite a meia-noite, não 24h).
function diasAtras(data) {
  const inicioHoje = new Date();
  inicioHoje.setHours(0, 0, 0, 0);
  const inicioDoDia = new Date(data);
  inicioDoDia.setHours(0, 0, 0, 0);
  return Math.round((inicioHoje - inicioDoDia) / MS_POR_DIA);
}

// "Hoje", "Ontem", dia da semana na última semana, "12 out" além disso.
function rotuloDoDia(data) {
  const dias = diasAtras(data);
  if (dias <= 0) return 'Hoje';
  if (dias === 1) return 'Ontem';
  if (dias < 7) return fmtDiaDaSemana.format(data);
  return fmtDiaEMes.format(data).replace('.', '');
}

// Agrupa em sequência pelo dia local de `episodio_lancado_em` (o feed já vem do
// mais recente pro mais antigo). Item sem horário — feed persistido de antes
// do campo existir — cai num grupo "Recentes" sem data.
function agruparPorDia(itens) {
  const grupos = [];
  for (const item of itens) {
    const data = item.episodio_lancado_em ? new Date(item.episodio_lancado_em) : null;
    const chave = data
      ? `${data.getFullYear()}-${data.getMonth()}-${data.getDate()}`
      : 'sem-data';
    const ultimo = grupos[grupos.length - 1];
    if (ultimo?.chave === chave) ultimo.itens.push(item);
    else grupos.push({ chave, data, itens: [item] });
  }
  return grupos;
}

// "Acabou de sair" no estilo da direção B do artefato de design: lista em duas
// colunas — capa, nome, gêneros e o episódio que saiu ao lado, e à direita a
// HORA (no lugar do botão de play do mockup). As linhas são separadas POR DIA
// (Hoje, Ontem, Segunda-feira...) com uma linha e o rótulo acima, o mesmo
// recurso de `SlotDoDiaDeEstreia.jsx`; `episodio_lancado_em` é o instante real
// em que o episódio foi ao ar (`AiringSchedule.airingAt` da AniList), então dia
// e hora são exatos, não estimados.
export default function ListaDeLancamentos({ itens, chaveDoItem, aoAtivar, desabilitado }) {
  const [expandida, setExpandida] = useState(false);
  const visiveis = expandida ? itens : itens.slice(0, LIMITE_INICIAL);
  const grupos = agruparPorDia(visiveis);

  return (
    <div style={{ paddingInline: PADDING_TITULO }} className="flex flex-col gap-8">
      {grupos.map((grupo) => {
        const hoje = grupo.data != null && diasAtras(grupo.data) <= 0;
        return (
          <section key={grupo.chave}>
            <h3 className="flex items-baseline gap-3 pb-3">
              <span className="text-2xl font-extrabold capitalize leading-none text-white">
                {grupo.data ? rotuloDoDia(grupo.data) : 'Recentes'}
              </span>
              {grupo.data && diasAtras(grupo.data) >= 2 && diasAtras(grupo.data) < 7 && (
                <span className="text-sm text-ink-muted">
                  {fmtDiaEMes.format(grupo.data).replace('.', '')}
                </span>
              )}
            </h3>
            <div
              aria-hidden="true"
              className={`mb-2 h-0.5 rounded-full ${hoje ? 'bg-neon' : 'bg-white/25'}`}
            />
            <ul className="grid md:grid-cols-2 md:gap-x-10">
              {grupo.itens.map((item) => {
                const generos = (item.generos ?? []).slice(0, 2).map(traduzirGenero).join(' · ');
                const hora = item.episodio_lancado_em
                  ? fmtHora.format(new Date(item.episodio_lancado_em))
                  : null;
                return (
                  <li key={chaveDoItem(item)}>
                    <AtivadorDeAnime
                      item={item}
                      aoAtivar={() => aoAtivar(item)}
                      desabilitado={desabilitado}
                      className="-mx-3 flex w-[calc(100%+1.5rem)] items-center gap-4 rounded-2xl px-3 py-3 transition-colors hover:bg-surface"
                    >
                      <span className="aspect-[2/3] w-20 shrink-0 overflow-hidden rounded-lg bg-surface sm:w-24">
                        {item.capa_url && (
                          <img
                            src={item.capa_url}
                            alt=""
                            loading="lazy"
                            className="h-full w-full object-cover"
                          />
                        )}
                      </span>
                      <span className="flex min-w-0 grow flex-col items-start gap-1">
                        <span className="line-clamp-2 text-base font-bold text-white sm:text-lg">
                          {item.titulo_romaji}
                        </span>
                        {generos && <span className="text-sm text-ink-muted">{generos}</span>}
                        {item.episodio_lancado != null && (
                          <span className="text-sm font-bold text-ink-muted">
                            Episódio {item.episodio_lancado} disponível
                          </span>
                        )}
                      </span>
                      {hora && (
                        <span
                          className="flex shrink-0 flex-col items-end pr-2"
                          aria-label={`Horário: ${hora}`}
                        >
                          <span
                            aria-hidden="true"
                            className="text-2xl font-extrabold tabular-nums text-white"
                          >
                            {hora}
                          </span>
                          <span
                            aria-hidden="true"
                            className="text-[11px] font-bold uppercase tracking-wider text-ink-muted"
                          >
                            horário
                          </span>
                        </span>
                      )}
                    </AtivadorDeAnime>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
      {itens.length > LIMITE_INICIAL && (
        <div className="flex justify-center">
          <button
            type="button"
            aria-expanded={expandida}
            onClick={() => setExpandida((atual) => !atual)}
            className={CLASSE_BOTAO_MOSTRAR_MAIS}
          >
            {expandida ? 'Mostrar menos' : 'Mostrar mais'}
          </button>
        </div>
      )}
    </div>
  );
}
