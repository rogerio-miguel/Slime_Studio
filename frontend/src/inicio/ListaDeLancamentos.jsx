import { Play } from 'lucide-react';
import { useState } from 'react';
import BrilhoDaCapa from '../components/BrilhoDaCapa.jsx';
import IconeSalvar from '../components/IconeSalvar.jsx';
import BotaoDeEstado from '../components/mascote/BotaoDeEstado.jsx';
import AtivadorDeAnime from './AtivadorDeAnime.jsx';
import { traduzirGenero } from './generos.js';
import { PADDING_TITULO } from './tamanhoDeCard.js';

const fmtHora = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' });
const fmtDiaDaSemana = new Intl.DateTimeFormat('pt-BR', { weekday: 'long' });
const fmtDiaEMes = new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'short' });
const MS_POR_DIA = 86_400_000;

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

// "agora", "há 12 min", "há 5 h"; passadas 24h cai no rótulo do dia, porque
// "há 30 h" é pior de ler que "Ontem". `null` pra item sem horário.
function rotuloRelativo(data) {
  const minutos = Math.floor((Date.now() - data) / 60_000);
  if (minutos < 1) return 'agora';
  if (minutos < 60) return `há ${minutos} min`;
  if (minutos < 24 * 60) return `há ${Math.floor(minutos / 60)} h`;
  return rotuloDoDia(data);
}

// Cards antes do "Mostrar mais" (só os de hoje; 4 linhas em duas colunas).
const LIMITE_INICIAL_DA_LISTA = 8;

// Item sem horário (feed persistido de antes do campo existir) não conta como
// "de hoje": não dá pra afirmar, então só aparece depois do "Mostrar mais".
function lancadoHoje(item) {
  return item.episodio_lancado_em != null && diasAtras(new Date(item.episodio_lancado_em)) <= 0;
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

// Miniatura 16:9 no estilo da Crunchyroll, na ordem que reduz os fallbacks:
// `banner_com_titulo_url` (backdrop do TMDB com o título desenhado) → `banner_url`
// (banner limpo, sem texto, pode ter área vazia mas é arte horizontal do anime) →
// a capa inteira centralizada sobre ela mesma desfocada — `object-cover` cortaria o
// pôster e fundo liso deixava as laterais vazias. A capa em 2:3 foi testada e
// desalinhava o texto entre as linhas (pedido do usuário: voltar ao 16:9). Nada de
// logo/texto sobreposto; no hover da linha entra um play no centro e o glow
// ambiente (`BrilhoDaCapa`, a mesma receita do hover dos cards de pôster). Decorativa
// (`aria-hidden`): o título ao lado é o nome acessível.
function MiniaturaDeLancamento({ item }) {
  const arte = item.banner_com_titulo_url || item.banner_url;
  const brilho = arte || item.capa_url;
  return (
    <span aria-hidden="true" className="relative aspect-video w-36 shrink-0 sm:w-48">
      {brilho && <BrilhoDaCapa capa={brilho} classeAspecto="aspect-video" />}
      <span className="absolute inset-0 overflow-hidden rounded-lg bg-surface">
        {arte ? (
          <img src={arte} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          item.capa_url && (
            <>
              <img
                src={item.capa_url}
                alt=""
                loading="lazy"
                className="absolute inset-0 h-full w-full scale-125 object-cover blur-xl brightness-50 saturate-150"
              />
              <img
                src={item.capa_url}
                alt=""
                loading="lazy"
                className="relative h-full w-full object-contain"
              />
            </>
          )
        )}
        <span className="absolute inset-0 flex items-center justify-center bg-black/35 opacity-0 transition-opacity group-hover/linha:opacity-100 group-focus-visible/linha:opacity-100 motion-reduce:transition-none">
          <Play className="h-9 w-9 fill-white text-white drop-shadow-[0_2px_6px_rgb(0_0_0/0.7)]" />
        </span>
      </span>
    </span>
  );
}

// "Acabou de sair": os episódios mais recentes separados POR DIA (Hoje, Ontem,
// Segunda-feira...). Cada dia é uma faixa: o rótulo do dia (com data e contagem) em cima, uma barra de largura total e, abaixo, os cards horizontais — miniatura 16:9, nome,
// gêneros, EP e a HORA. Propositalmente sem pôster em coluna: logo abaixo do Top 10
// (coverflow de pôsteres) um segundo bloco de pôsteres pareceria repetido.
// `episodio_lancado_em` é o instante real em que o episódio foi ao ar
// (`AiringSchedule.airingAt` da AniList), então dia e hora são exatos, não estimados.
// Fechada, traz só o que saiu hoje (ou, se nada saiu hoje, os mais recentes), até
// `LIMITE_INICIAL_DA_LISTA`; "Mostrar mais" revela o resto do feed.
export default function ListaDeLancamentos({ itens, chaveDoItem, aoAtivar, desabilitado }) {
  const [expandida, setExpandida] = useState(false);
  const deHoje = itens.filter(lancadoHoje).slice(0, LIMITE_INICIAL_DA_LISTA);
  const recolhida = deHoje.length > 0 ? deHoje : itens.slice(0, LIMITE_INICIAL_DA_LISTA);
  const temMais = recolhida.length < itens.length;
  const grupos = agruparPorDia(expandida ? itens : recolhida);

  return (
    <div className="flex flex-col gap-10">
      {grupos.map((grupo) => {
        const dias = grupo.data ? diasAtras(grupo.data) : null;
        const hoje = dias != null && dias <= 0;
        return (
          <section key={grupo.chave} style={{ paddingInline: PADDING_TITULO }}>
            <h3 className="flex items-baseline gap-3">
              <span className="text-2xl font-extrabold capitalize leading-none text-white">
                {grupo.data ? rotuloDoDia(grupo.data) : 'Recentes'}
              </span>
              <span className="text-sm font-bold text-ink-muted">
                {dias != null && dias >= 1 && dias < 7 && `${fmtDiaEMes.format(grupo.data).replace('.', '')} · `}
                {grupo.itens.length} {grupo.itens.length === 1 ? 'episódio' : 'episódios'}
              </span>
            </h3>
            <span
              aria-hidden="true"
              className={`mb-4 mt-3 block h-1 w-10 rounded-full ${hoje ? 'bg-neon' : 'bg-white/25'}`}
            />
            <ul className="grid gap-3 md:grid-cols-2">
              {grupo.itens.map((item) => {
                const generos = (item.generos ?? []).slice(0, 2).map(traduzirGenero).join(' · ');
                const instante = item.episodio_lancado_em ? new Date(item.episodio_lancado_em) : null;
                const hora = instante ? fmtHora.format(instante) : null;
                // Nos outros dias o rótulo relativo repetiria o título do grupo ("Ontem").
                const relativo = instante && hoje ? rotuloRelativo(instante) : null;
                return (
                  <li key={chaveDoItem(item)}>
                    <AtivadorDeAnime
                      item={item}
                      aoAtivar={() => aoAtivar(item)}
                      desabilitado={desabilitado}
                      className="group/linha group/card flex w-full items-center gap-4 rounded-2xl p-2.5 pr-5"
                    >
                      <MiniaturaDeLancamento item={item} />
                      <span className="flex min-w-0 grow flex-col items-start justify-center gap-1.5">
                        <span className="line-clamp-2 text-base font-bold text-white sm:text-lg">
                          {item.titulo_romaji}
                        </span>
                        {generos && <span className="text-sm text-ink-muted font-bold">{generos}</span>}
                        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                          {item.episodio_lancado != null && (
                            <span className="rounded-md bg-neon-soft px-2 py-0.5 text-xs font-extrabold tabular-nums text-neon-claro">
                              EP.{item.episodio_lancado}
                            </span>
                          )}
                          {item.anime_id != null && (
                            <span className="inline-flex items-center gap-1 text-xs font-bold uppercase tracking-wide text-white">
                              <IconeSalvar preenchido className="h-4 w-4 shrink-0" />
                              No catálogo
                            </span>
                          )}
                        </span>
                      </span>
                      {hora && (
                        <span
                          className="flex shrink-0 flex-col items-end"
                          aria-label={`Horário: ${hora}${relativo ? `, ${relativo}` : ''}`}
                        >
                          <span aria-hidden="true" className="text-xl font-extrabold tabular-nums text-white">
                            {hora}
                          </span>
                          {relativo && (
                            <span aria-hidden="true" className="text-xs font-bold text-ink-muted">
                              {relativo}
                            </span>
                          )}
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
      {temMais && (
        <div className="flex justify-center">
          <BotaoDeEstado aria-expanded={expandida} onClick={() => setExpandida((atual) => !atual)}>
            {expandida ? 'Mostrar menos' : 'Mostrar mais'}
          </BotaoDeEstado>
        </div>
      )}
    </div>
  );
}
