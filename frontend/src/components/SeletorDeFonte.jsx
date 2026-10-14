import { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { buscarEmFontes } from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import { nomeDaFonte } from '../fontes.js';
import CampoDeBusca from './ilha/CampoDeBusca.jsx';
import { CLASSE_PAINEL_FLUTUANTE, FUNDO_DOS_CONTROLES } from './painelFlutuante.js';
import { useFecharAoClicarFora } from '../hooks/useFecharAoClicarFora.js';

// Seletor de fonte e versão da barra de controles da página do anime
// (`paginas/PaginaDoAnime.jsx`) — substituiu o diálogo "Trocar fonte". A pílula
// mostra a fonte/versão ativas; aberta, vira um painel com busca ao vivo nos
// sites de streaming (`buscarEmFontes`, o mesmo endpoint do diálogo) e a lista
// de candidatos, cada um com o alternador Legendado/Dublado na própria linha —
// fonte e versão saem numa escolha só.
//
// Busca: abre já pesquisando o título do anime (como o diálogo fazia) e só
// refaz no envio do formulário (Enter ou botão "Buscar"), nunca enquanto o
// usuário digita. Cada busca varre os sites ao vivo (segundos, scraping), então
// também NUNCA roda com o painel fechado.
//
// Candidatos com versão confirmada (`candidato.versao != null`) vêm como uma
// entrada de catálogo por versão (dublado é outro slug no AnimesDrive,
// `fontes/adaptadores/animesdrive.py`); `construirLinhas` agrupa as duas numa
// linha só. Fronteira de token igual à de `fontes/versao.py` — mantida em JS
// porque é só apresentação de resultados já retornados.
const REGEX_MARCADOR_VERSAO = /(?:^|[-\s])(?:dublado|dub|legendado|leg)(?:$|[-\s])/g;
const VERSOES = ['legendado', 'dublado'];
const ROTULO_CURTO = { legendado: 'Leg.', dublado: 'Dub.' };
const ROTULO_LONGO = { legendado: 'legendado', dublado: 'dublado' };

function slugBase(identificador) {
  return identificador.toLowerCase().replace(REGEX_MARCADOR_VERSAO, ' ').trim().replace(/[-\s]+/g, ' ');
}

// Uma linha por fonte; `candidatoPorVersao` guarda o candidato a confirmar em
// cada versão que EXISTE nela, e só essas viram botão. Grupo: as encontradas.
// Site que não diferencia versão: só Legendado (convenção do sistema pra
// ausência de marcador) — a UI não oferece Dublado que o site não prova ter.
function construirLinhas(candidatos) {
  const linhas = [];
  const indicePorChave = new Map();
  for (const candidato of candidatos) {
    if (candidato.versao == null) {
      linhas.push({
        chave: `${candidato.dominio}:${candidato.identificador}`,
        principal: candidato,
        confirmada: false,
        candidatoPorVersao: new Map([['legendado', candidato]]),
      });
      continue;
    }
    const chave = `${candidato.dominio}:grupo:${slugBase(candidato.identificador)}`;
    let indice = indicePorChave.get(chave);
    if (indice == null) {
      indice = linhas.length;
      indicePorChave.set(chave, indice);
      linhas.push({ chave, principal: null, confirmada: true, candidatoPorVersao: new Map() });
    }
    const porVersao = linhas[indice].candidatoPorVersao;
    if (!porVersao.has(candidato.versao)) porVersao.set(candidato.versao, candidato);
  }
  for (const linha of linhas) {
    // Nome "limpo", sem sufixo "Dublado": o do legendado quando existir.
    linha.principal ??= linha.candidatoPorVersao.get('legendado') ?? [...linha.candidatoPorVersao.values()][0];
  }
  return linhas;
}

export default function SeletorDeFonte({
  rotulo,
  fonteRespondeu,
  dominioAtivo,
  versaoAtiva,
  tituloAnime,
  aoEscolher,
  confirmando = false,
  erro = null,
  aoAbrir,
}) {
  const [aberto, setAberto] = useState(false);
  const [termo, setTermo] = useState('');
  const [termoConsultado, setTermoConsultado] = useState('');
  const idPainel = useId();
  const containerRef = useRef(null);
  const gatilhoRef = useRef(null);
  const painelRef = useRef(null);

  // Abrir pesquisa o título do anime; fechar descarta o termo editado — a
  // próxima abertura não herda a busca anterior.
  useEffect(() => {
    // Zera o termo consultado ao fechar: sem isso a próxima abertura dispararia
    // uma busca ao vivo com o termo velho antes de o título do anime entrar.
    if (!aberto) {
      setTermoConsultado('');
      return;
    }
    aoAbrir?.();
    setTermo(tituloAnime ?? '');
    setTermoConsultado((tituloAnime ?? '').trim());
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aberto, tituloAnime]);

  const termoValido = termoConsultado.length > 0;
  // Abrir o painel usa o cache do servidor (reabrir é instantâneo); Enter/Buscar
  // marcam esta ref pra ir de verdade aos sites. Lida e zerada no início da
  // busca, que roda uma vez por commit mesmo com termo e recarga mudando juntos.
  const atualizarRef = useRef(false);
  const busca = useRecurso(() => {
    if (!aberto || !termoValido) return Promise.resolve(null);
    const atualizar = atualizarRef.current;
    atualizarRef.current = false;
    return buscarEmFontes(termoConsultado, { atualizar });
  }, [aberto, termoConsultado, termoValido]);

  const fechar = (devolverFoco = true) => {
    setAberto(false);
    if (devolverFoco) gatilhoRef.current?.focus();
  };

  useFecharAoClicarFora(aberto, containerRef, () => setAberto(false), { bloqueado: confirmando });

  const escolher = async (candidato, versao) => {
    const deuCerto = await aoEscolher(candidato, versao);
    if (deuCerto) fechar();
  };

  const aoTeclarNoPainel = (evento) => {
    if (evento.key === 'Escape') {
      if (confirmando) return;
      evento.preventDefault();
      fechar();
      return;
    }
    if (evento.key !== 'ArrowDown' && evento.key !== 'ArrowUp') return;
    const focaveis = [...painelRef.current.querySelectorAll('input, button:not(:disabled)')];
    const atual = focaveis.indexOf(document.activeElement);
    if (atual < 0) return;
    evento.preventDefault();
    const passo = evento.key === 'ArrowDown' ? 1 : -1;
    focaveis[(atual + passo + focaveis.length) % focaveis.length].focus();
  };

  const aoPesquisar = () => {
    atualizarRef.current = true;
    setTermoConsultado(termo.trim());
    busca.recarregar();
  };

  const candidatos = termoValido ? (busca.dados?.resultados ?? null) : null;
  const linhas = candidatos != null ? construirLinhas(candidatos) : null;
  const buscando = termoValido && busca.carregando;
  const erroBusca = termoValido && !buscando && busca.erro != null;
  const sitesFora = (busca.dados?.fontes ?? []).filter((fonte) => fonte.indisponivel).length;
  const dominiosJaMarcados = new Set();

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={gatilhoRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={aberto}
        aria-controls={aberto ? idPainel : undefined}
        onClick={() => setAberto((estava) => !estava)}
        className={`inline-flex h-7 items-center gap-2 rounded-full ${FUNDO_DOS_CONTROLES} pl-2.5 pr-2 text-xs font-semibold outline-none transition-colors hover:text-white aria-expanded:text-white focus-visible:outline-2 focus-visible:outline-neon cursor-pointer`}
      >
        {/* Ponto azul = a fonte remota já respondeu; antes disso só a versão. */}
        {fonteRespondeu && (
          <span
            aria-hidden="true"
            className="h-2 w-2 rounded-full bg-neon shadow-[0_0_0_3px_rgba(32,128,240,0.25)]"
          />
        )}
        {rotulo}
        <ChevronDown
          width={12}
          height={12}
          aria-hidden="true"
          strokeWidth="3"
          className={`transition-transform ${aberto ? 'rotate-180' : ''}`}
        />
      </button>

      {aberto && (
        <div
          ref={painelRef}
          id={idPainel}
          role="dialog"
          aria-label="Fonte e versão"
          onKeyDown={aoTeclarNoPainel}
          className={`absolute left-0 top-full z-10 mt-2 w-[min(26rem,calc(100vw-2rem))] ${CLASSE_PAINEL_FLUTUANTE} text-sm text-white`}
        >
          <div className="p-3">
            <CampoDeBusca
              termo={termo}
              aoMudar={setTermo}
              aoSubmeter={aoPesquisar}
              rotulo="Buscar fontes"
              larguraTotal
              focarAoMontar
            />
          </div>

          {erro && (
            <p role="alert" className="px-4 pb-2 text-sm text-red-400">
              {erro}
            </p>
          )}

          <div aria-live="polite" className="max-h-80 overflow-y-auto">
            {!termoValido && (
              <p className="px-4 py-2 text-ink-muted">Digite um termo e aperte Enter para buscar.</p>
            )}
            {buscando && (
              <div role="status" aria-label="Buscando fontes" className="flex flex-col gap-2 px-4 py-1">
                {[0, 1, 2].map((indice) => (
                  <div key={indice} className="h-10 animate-pulse rounded-lg bg-white/5" />
                ))}
              </div>
            )}
            {erroBusca && (
              <p role="alert" className="px-4 py-2 text-red-400">
                Não foi possível buscar fontes para este termo.{' '}
                <button type="button" onClick={busca.recarregar} className="underline">
                  Tentar novamente
                </button>
              </p>
            )}
            {!buscando && !erroBusca && candidatos != null && candidatos.length === 0 && (
              <p className="px-4 py-2 text-ink-muted">Nenhum resultado para “{termoConsultado}”.</p>
            )}

            {!buscando && !erroBusca && linhas?.map((linha) => {
              const { principal, candidatoPorVersao, confirmada } = linha;
              const versoes = VERSOES.filter((versao) => candidatoPorVersao.has(versao));
              // O ativo é por domínio (só há UM mapeamento por site): marca só
              // a primeira linha de cada domínio pra não acender várias.
              const ativa = principal.dominio === dominioAtivo && !dominiosJaMarcados.has(principal.dominio);
              if (ativa) dominiosJaMarcados.add(principal.dominio);
              const versaoDaLinha = versoes.includes(versaoAtiva) ? versaoAtiva : versoes[0];
              const nome = nomeDaFonte(principal.dominio);
              return (
                <div key={linha.chave} className="flex items-center gap-2 pr-3 hover:bg-white/5">
                  <button
                    type="button"
                    disabled={confirmando}
                    onClick={() => escolher(candidatoPorVersao.get(versaoDaLinha), versaoDaLinha)}
                    aria-label={`Usar ${principal.titulo_exibicao} (${nome}) como ${ROTULO_LONGO[versaoDaLinha]}`}
                    className="flex min-w-0 flex-1 items-center gap-3 py-2.5 pl-4 pr-1 text-left outline-none focus-visible:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer"
                  >
                    <span
                      aria-hidden="true"
                      className={`grid h-4 w-4 shrink-0 place-items-center rounded-full border-2 ${
                        ativa ? 'border-neon' : 'border-[#555]'
                      }`}
                    >
                      {ativa && <span className="h-1.5 w-1.5 rounded-full bg-neon" />}
                    </span>
                    <span className="flex min-w-0 flex-col leading-snug">
                      <span className="font-semibold">{nome}</span>
                      <span className="truncate text-xs text-ink-muted">{principal.titulo_exibicao}</span>
                      {principal.correspondencia_incerta && (
                        <span className="text-xs font-semibold text-amber-300">Correspondência incerta</span>
                      )}
                    </span>
                  </button>
                  <div
                    role="group"
                    aria-label={`Versão em ${nome}`}
                    title={confirmada ? undefined : 'O site não confirma a versão; vale a sua escolha'}
                    className="flex shrink-0 gap-0.5 rounded-lg bg-white/5 p-0.5"
                  >
                    {versoes.map((versao) => {
                      const marcada = ativa && versaoAtiva === versao;
                      return (
                        <button
                          key={versao}
                          type="button"
                          disabled={confirmando}
                          aria-pressed={marcada}
                          aria-label={`Usar ${principal.titulo_exibicao} (${nome}) como ${ROTULO_LONGO[versao]}${confirmada ? '' : ' (site não confirma a versão)'}`}
                          onClick={() => escolher(candidatoPorVersao.get(versao), versao)}
                          className={`h-6 rounded-md px-2 text-xs font-semibold outline-none transition-colors focus-visible:outline-2 focus-visible:outline-neon disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer ${
                            marcada ? 'bg-neon-soft text-white' : 'text-ink-muted hover:text-white'
                          }`}
                        >
                          {ROTULO_CURTO[versao]}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}

            {!buscando && sitesFora > 0 && (
              <p className="px-4 py-2 text-xs text-ink-muted">
                {sitesFora === 1 ? '1 site não respondeu' : `${sitesFora} sites não responderam`} a esta busca.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
