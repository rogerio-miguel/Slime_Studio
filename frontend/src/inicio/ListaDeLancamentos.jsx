import { Play } from 'lucide-react';
import { useState } from 'react';
import AnimeCard from '../components/AnimeCard.jsx';
import IconeSalvar from '../components/IconeSalvar.jsx';
import useCardsPorPagina from '../hooks/useCardsPorPagina.js';
import AtivadorDeAnime from './AtivadorDeAnime.jsx';
import GradeDeCatalogo from './GradeDeCatalogo.jsx';
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

// Linhas da lista antes do "Mostrar mais" (só as de hoje; 4 linhas em duas colunas).
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
// logo/texto sobreposto; no hover da linha entra um play no centro. Decorativa
// (`aria-hidden`): o título ao lado é o nome acessível.
function MiniaturaDeLancamento({ item }) {
  const arte = item.banner_com_titulo_url || item.banner_url;
  return (
    <span
      aria-hidden="true"
      className="relative aspect-video w-36 shrink-0 overflow-hidden rounded-lg bg-surface sm:w-48"
    >
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
  );
}

// "Acabou de sair": os episódios mais recentes em pôster — o mesmo card e a mesma
// grade das fileiras da Home (tamanho "pequeno", glow no hover), com o episódio e
// "há N min" na legenda, nada sobre a imagem — e, abaixo, o resto em lista de duas
// colunas: capa, nome, gêneros, episódio e à direita a HORA. Fechada, a lista traz
// só o que saiu hoje ("Mais cedo hoje"), até `LIMITE_INICIAL_DA_LISTA` linhas;
// "Mostrar mais" revela o resto do feed.
// Ela é separada POR DIA (Mais cedo hoje, Ontem, Segunda-feira...) com uma linha e o rótulo acima, o mesmo
// recurso de `SlotDoDiaDeEstreia.jsx`; `episodio_lancado_em` é o instante real em
// que o episódio foi ao ar (`AiringSchedule.airingAt` da AniList), então dia e
// hora são exatos, não estimados.
export default function ListaDeLancamentos({ itens, chaveDoItem, aoAtivar, desabilitado }) {
  const [expandida, setExpandida] = useState(false);
  const qtdDestaques = useCardsPorPagina();
  const destaques = itens.slice(0, qtdDestaques);
  const resto = itens.slice(qtdDestaques);
  const recolhida = resto.filter(lancadoHoje).slice(0, LIMITE_INICIAL_DA_LISTA);
  const temMais = recolhida.length < resto.length;
  const grupos = agruparPorDia(expandida ? resto : recolhida);

  return (
    <div className="flex flex-col gap-8">
      <GradeDeCatalogo
        itens={destaques}
        tamanho="pequeno"
        comSombra={false}
        comAnimacao={false}
        chaveDoItem={chaveDoItem}
        renderItem={(item) => (
          <AnimeCard
            anime={item}
            aoAtivar={() => aoAtivar(item)}
            desabilitado={desabilitado}
            episodioLancado={item.episodio_lancado}
            lancadoHa={
              item.episodio_lancado_em ? rotuloRelativo(new Date(item.episodio_lancado_em)) : null
            }
          />
        )}
      />
      {grupos.map((grupo) => {
        const hoje = grupo.data != null && diasAtras(grupo.data) <= 0;
        return (
          <section key={grupo.chave} style={{ paddingInline: PADDING_TITULO }}>
            <h3 className="flex items-baseline gap-3 pb-3">
              <span className="text-2xl font-extrabold capitalize leading-none text-white">
                {hoje ? 'Mais cedo hoje' : grupo.data ? rotuloDoDia(grupo.data) : 'Recentes'}
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
                      className="group/linha -mx-3 flex w-[calc(100%+1.5rem)] items-center gap-4 rounded-2xl px-3 py-2 transition-colors hover:bg-surface"
                    >
                      <MiniaturaDeLancamento item={item} />
                      {/* Coluna da altura da miniatura (`self-stretch`) só pra ancorar o "Assistir":
                          o conteúdo segue empilhado e centralizado, mas a chamada do hover fica
                          no mesmo lugar (meio da miniatura, logo abaixo de um título de 2 linhas) com título de 1 ou 2 linhas, como na
                          Crunchyroll. Gêneros e chips somem com `invisible` (mantêm o espaço, então
                          nada se mexe) e o "Assistir" é só visual: o clique é da linha inteira. */}
                      <span className="relative flex min-w-0 grow flex-col items-start justify-center gap-1 self-stretch">
                        <span className="line-clamp-2 text-base font-bold text-white sm:text-lg">
                          {item.titulo_romaji}
                        </span>
                        <span className="flex flex-col items-start gap-1 group-hover/linha:invisible group-focus-visible/linha:invisible">
                          {generos && <span className="text-sm text-ink-muted">{generos}</span>}
                          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            {item.episodio_lancado != null && (
                              <span className="rounded-md bg-neon-soft px-2 py-0.5 text-xs font-extrabold tabular-nums text-[#9cc8ff]">
                                EP.{item.episodio_lancado}
                              </span>
                            )}
                            {item.anime_id != null && (
                              <span className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-white">
                                <IconeSalvar preenchido className="h-4 w-4 shrink-0" />
                                No catálogo
                              </span>
                            )}
                          </span>
                        </span>
                        <span
                          aria-hidden="true"
                          className="invisible absolute left-0 top-1/2 mt-4 flex items-center gap-1.5 whitespace-nowrap text-sm font-extrabold uppercase tracking-wide text-neon group-hover/linha:visible group-focus-visible/linha:visible"
                        >
                          <Play className="h-3.5 w-3.5 fill-neon" />
                          Assistir{item.episodio_lancado != null ? ` EP.${item.episodio_lancado}` : ''}
                        </span>
                      </span>
                      {hora && (
                        <span
                          className="flex shrink-0 flex-col items-end pr-2 group-hover/linha:invisible group-focus-visible/linha:invisible"
                          aria-label={`Horário: ${hora}${relativo ? `, ${relativo}` : ''}`}
                        >
                          <span
                            aria-hidden="true"
                            className="text-xl font-extrabold tabular-nums text-white"
                          >
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
