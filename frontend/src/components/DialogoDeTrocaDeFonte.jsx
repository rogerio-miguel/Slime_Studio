import { useEffect, useRef, useState } from 'react';
import { buscarEmFontes } from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import { nomeDaFonte } from '../fontes.js';

// Quando o site diferencia versão (`candidato.versao != null`), dublado não é
// uma aba do mesmo card — é outra entrada de catálogo com slug próprio (ex.
// AnimesDrive: `tensei-...-ken` e `tensei-...-ken-dublado`,
// extractors/animesdrive.py). Sem agrupar, cada versão vira uma linha
// duplicada no diálogo. Fronteira de token mesma de
// `extractors/versao.py::_REGEX_DUBLADO/_REGEX_LEGENDADO` — mantida em JS
// porque é só apresentação (agrupamento de resultados já retornados), não
// justifica um round-trip novo ao backend.
const REGEX_MARCADOR_VERSAO = /(?:^|[-\s])(?:dublado|dub|legendado|leg)(?:$|[-\s])/g;

function slugBase(identificador) {
  return identificador.toLowerCase().replace(REGEX_MARCADOR_VERSAO, ' ').trim().replace(/[-\s]+/g, ' ');
}

// Agrupa candidatos com versão confirmada (mesma fonte + mesmo slug-base) numa
// única linha com um botão por versão realmente encontrada; candidatos sem
// versão (site não diferencia) continuam uma linha por candidato, igual antes.
function construirLinhas(candidatos) {
  const linhas = [];
  const indicePorChave = new Map();
  for (const candidato of candidatos) {
    if (candidato.versao == null) {
      linhas.push({ tipo: 'individual', candidato });
      continue;
    }
    const chave = `${candidato.dominio}:${slugBase(candidato.identificador)}`;
    let indice = indicePorChave.get(chave);
    if (indice == null) {
      indice = linhas.length;
      indicePorChave.set(chave, indice);
      linhas.push({ tipo: 'grupo', porVersao: new Map() });
    }
    if (!linhas[indice].porVersao.has(candidato.versao)) {
      linhas[indice].porVersao.set(candidato.versao, candidato);
    }
  }
  return linhas;
}

// `<dialog>` nativo, mesmo idioma de DialogoDeFonteAmbigua.jsx/
// DialogoDeConfirmacao.jsx (foco preso, backdrop e Esc de graça, sem lib de
// modal — Escada de Minimalismo, CLAUDE.md §4). Racional completo da troca
// manual de fonte (por que é "solução barata", o que fica de fora) mora em
// PaginaDoAnime.jsx, junto do estado que orquestra este diálogo — este
// arquivo só cuida da busca em fontes (`buscarEmFontes`, hoje o único
// consumidor de `/api/animes/buscar-fontes`) e da apresentação dos candidatos.
//
// Busca automática ao abrir, com o título do anime (`tituloAnime`) — mas
// editável: a variante dublada de um site pode ter título de exibição
// diferente do título "limpo" do anime (ex. AnimesDrive "X Dublado") e não
// bater na busca por padrão. Reenvio só no submit do form (Enter/botão), não
// a cada tecla.
export default function DialogoDeTrocaDeFonte({
  aberto,
  tituloAnime,
  aoConfirmar,
  aoFechar,
  confirmando = false,
  erro = null,
}) {
  const dialogRef = useRef(null);
  const [termo, setTermo] = useState('');
  const [termoSubmetido, setTermoSubmetido] = useState('');

  useEffect(() => {
    const dialogo = dialogRef.current;
    if (!dialogo) return;
    if (aberto && !dialogo.open) dialogo.showModal();
    if (!aberto && dialogo.open) dialogo.close();
  }, [aberto]);

  // Reseta o termo pro título do anime toda vez que o diálogo abre — evita
  // carregar o termo editado (ou os resultados) de uma sessão anterior de
  // troca de fonte pra dentro da próxima abertura.
  useEffect(() => {
    if (!aberto) return;
    setTermo(tituloAnime ?? '');
    setTermoSubmetido(tituloAnime ?? '');
  }, [aberto, tituloAnime]);

  // `useRecurso` (mesmo padrão de Inicio.jsx::buscaEmFontes) em vez de
  // fetch/estado manual: além de eliminar a duplicação, dá acesso a
  // `recarregar()` — necessário pro botão "Buscar" refazer a busca mesmo
  // quando o termo não mudou (retry depois de uma falha, por exemplo), caso
  // em que `termoSubmetido` receberia o mesmo valor primitivo e não
  // dispararia o efeito sozinho.
  const busca = useRecurso(
    () =>
      aberto && termoSubmetido
        ? buscarEmFontes(termoSubmetido)
        : Promise.resolve({ resultados: [] }),
    [aberto, termoSubmetido]
  );
  const candidatos = aberto && termoSubmetido ? (busca.dados?.resultados ?? null) : null;
  const linhas = candidatos != null ? construirLinhas(candidatos) : null;
  const buscando = aberto && Boolean(termoSubmetido) && busca.carregando;
  const erroBusca = aberto && Boolean(termoSubmetido) && busca.erro != null;

  const buscar = (evento) => {
    evento.preventDefault();
    setTermoSubmetido(termo.trim());
    busca.recarregar();
  };

  // Fechar via Esc (evento nativo `cancel`, cancelável) é ignorado enquanto
  // `confirmando` for true — evita abandonar o dialog com a confirmação de
  // fonte ainda em voo no servidor (o erro, se a chamada falhar depois,
  // ficaria setado num componente já fechado e ninguém veria). Clique no
  // backdrop não fecha este dialog de qualquer forma (sem `closedby="any"`);
  // "Cancelar" já fica `disabled` nesse estado, então o guard aqui existe
  // sobretudo pro Esc. Mesmo padrão de DialogoDeConfirmacao.jsx.
  const fechar = (evento) => {
    if (confirmando) {
      evento?.preventDefault();
      return;
    }
    aoFechar();
  };

  return (
    <dialog
      ref={dialogRef}
      onClose={fechar}
      onCancel={fechar}
      aria-labelledby="titulo-troca-fonte"
      className="m-auto w-full max-w-lg rounded-xl border border-neon-soft bg-surface p-6 text-white backdrop:bg-black/70"
    >
      <h2 id="titulo-troca-fonte" className="mb-2 text-base font-semibold">
        Trocar fonte
      </h2>
      <p className="mb-4 text-sm text-ink-muted">Escolha de onde os próximos episódios serão capturados.</p>

      <form onSubmit={buscar} className="mb-4 flex gap-2">
        <label htmlFor="termo-troca-fonte" className="sr-only">
          Termo de busca
        </label>
        <input
          id="termo-troca-fonte"
          type="text"
          value={termo}
          onChange={(evento) => setTermo(evento.target.value)}
          className="flex-1 rounded-lg border border-border-chrome bg-transparent px-3 py-2 text-sm text-white outline-none"
        />
        <button
          type="submit"
          className="rounded-lg border border-border-chrome px-4 py-2 text-sm outline-none transition-colors hover:border-neon"
        >
          Buscar
        </button>
      </form>

      {erro && (
        <p role="alert" className="mb-4 text-sm text-red-400">
          {erro}
        </p>
      )}
      {buscando && <p className="text-sm text-ink-muted">Buscando…</p>}
      {erroBusca && !buscando && (
        <p role="alert" className="mb-4 text-sm text-red-400">
          Não foi possível buscar fontes para este termo — tente novamente.
        </p>
      )}
      {!buscando && !erroBusca && candidatos != null && candidatos.length === 0 && (
        <p className="text-sm text-ink-muted">Nenhum resultado para “{termoSubmetido}”.</p>
      )}

      {!buscando && !erroBusca && linhas != null && linhas.length > 0 && (
        <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto">
          {linhas.map((linha) => {
            if (linha.tipo === 'individual') {
              const candidato = linha.candidato;
              const chave = `${candidato.dominio}:${candidato.identificador}`;
              return (
                <li
                  key={chave}
                  className="flex items-center gap-3 rounded-lg border border-border-chrome p-3"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-white">{candidato.titulo_exibicao}</p>
                    <p className="text-xs text-ink-muted">{nomeDaFonte(candidato.dominio)}</p>
                    {candidato.correspondencia_incerta && (
                      <p className="text-xs font-semibold text-amber-300">Correspondência incerta</p>
                    )}
                  </div>
                  {/* Site não diferencia versão (ex. AnimeFire) — os dois
                  botões continuam existindo, mas o rótulo deixa claro que é a
                  intenção de captura do usuário, não uma confirmação do site. */}
                  <div className="flex flex-none flex-col gap-1">
                    <button
                      type="button"
                      onClick={() => aoConfirmar(candidato, 'legendado')}
                      disabled={confirmando}
                      aria-label={`Baixar ${candidato.titulo_exibicao} (${nomeDaFonte(candidato.dominio)}) como legendado (site não confirma a versão)`}
                      className="rounded-md border border-border-chrome px-3 py-1 text-xs outline-none transition-colors hover:border-neon disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Legendado
                    </button>
                    <button
                      type="button"
                      onClick={() => aoConfirmar(candidato, 'dublado')}
                      disabled={confirmando}
                      aria-label={`Baixar ${candidato.titulo_exibicao} (${nomeDaFonte(candidato.dominio)}) como dublado (site não confirma a versão)`}
                      className="rounded-md border border-border-chrome px-3 py-1 text-xs outline-none transition-colors hover:border-neon disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Dublado
                    </button>
                  </div>
                </li>
              );
            }

            // Grupo: mesma fonte, mesmo slug-base, uma entrada de catálogo por
            // versão (achado de extractors/animesdrive.py). Exibe os dados do
            // candidato legendado quando existir — o nome "limpo", sem sufixo
            // "Dublado" — e um botão só para cada versão que o grupo de fato
            // tem, nunca os dois cegos.
            const principal = linha.porVersao.get('legendado') ?? linha.porVersao.get('dublado');
            const chave = `${principal.dominio}:grupo:${slugBase(principal.identificador)}`;
            return (
              <li
                key={chave}
                className="flex items-center gap-3 rounded-lg border border-border-chrome p-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-white">{principal.titulo_exibicao}</p>
                  <p className="text-xs text-ink-muted">{nomeDaFonte(principal.dominio)}</p>
                  {principal.correspondencia_incerta && (
                    <p className="text-xs font-semibold text-amber-300">Correspondência incerta</p>
                  )}
                </div>
                <div className="flex flex-none flex-col items-end gap-1">
                  {['legendado', 'dublado']
                    .filter((versao) => linha.porVersao.has(versao))
                    .map((versao) => {
                      const candidatoVersao = linha.porVersao.get(versao);
                      const rotulo = versao === 'dublado' ? 'Dublado' : 'Legendado';
                      return (
                        <button
                          key={versao}
                          type="button"
                          onClick={() => aoConfirmar(candidatoVersao, versao)}
                          disabled={confirmando}
                          aria-label={`Usar ${candidatoVersao.titulo_exibicao} (${nomeDaFonte(candidatoVersao.dominio)}) como ${rotulo.toLowerCase()}`}
                          className="rounded-md border border-border-chrome px-3 py-1 text-xs outline-none transition-colors hover:border-neon disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {rotulo}
                        </button>
                      );
                    })}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <button
        type="button"
        onClick={fechar}
        disabled={confirmando}
        className="mt-4 text-xs text-ink-muted underline outline-none disabled:cursor-not-allowed disabled:opacity-50 disabled:no-underline"
      >
        Cancelar
      </button>
    </dialog>
  );
}
