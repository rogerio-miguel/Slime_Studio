import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ErroDeApi } from '../api/cliente.js';
import {
  confirmarFonte,
  criarJobSite,
  listarEpisodios,
  listarEpisodiosRemotos,
  obterAnime,
  removerAnime,
} from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import BarraDeNavegacao from '../components/BarraDeNavegacao.jsx';
import DialogoDeConfirmacao from '../components/DialogoDeConfirmacao.jsx';
import DialogoDeFonteAmbigua from '../components/DialogoDeFonteAmbigua.jsx';
import DialogoDeTrocaDeFonte from '../components/DialogoDeTrocaDeFonte.jsx';
import LinhaDeEpisodio from '../components/LinhaDeEpisodio.jsx';
import { useFocoAoMontar } from '../hooks/useFocoAoMontar.js';

// Rótulo legível de `versaoAtiva`/`Episodio.versao` — inclui 'desconhecida'
// (fonte NAO_DIFERENCIADA, o backend nunca finge saber qual versão foi
// capturada). Fallback `?? versaoAtiva` cobre um valor futuro não mapeado
// aqui sem quebrar a renderização.
const ROTULO_VERSAO = {
  legendado: 'Legendado',
  dublado: 'Dublado',
  desconhecida: 'Desconhecida (site não confirma)',
};

// backend/core/enums.py::SITE_LOCAL — mesmo valor de string, espelhado aqui
// (padrão já usado em ROTULOS_STATUS de LinhaDeEpisodio.jsx).
const SITE_LOCAL = 'local';

// Um episódio local só conta como "já capturado" pra grade quando pertence à
// fonte/versão ativas — senão, depois de uma troca de fonte (`Trocar fonte`),
// episódios baixados da fonte ANTIGA continuam aparecendo como "prontos" na
// grade nova (grudados), escondendo que a fonte atual ainda não tem aquele
// número capturado. Descartado pelo predicado, o episódio não some da grade
// (`linhas` abaixo usa os números locais sem filtrar na união com os
// remotos) — só deixa de contar como captura, caindo no ramo remoto/não
// capturado. Deliberadamente conservador quando o domínio ainda é
// desconhecido (`dominioAtivo == null`: loading/erro/fonte ambígua da
// listagem remota) — não filtra por domínio nesse caso, pra não piscar um
// falso "nada capturado" enquanto a fonte remota ainda está sendo resolvida.
function pertenceAFonteAtiva(episodio, { dominioAtivo, versaoAtiva }) {
  if (episodio.site_origem === SITE_LOCAL) return true;
  if (dominioAtivo == null) return true;
  if (episodio.site_origem !== dominioAtivo) return false;
  return episodio.versao === versaoAtiva || episodio.versao === 'desconhecida';
}

// Rota "/anime/:id" — grade prontos/não capturados. Clique num episódio não
// capturado dispara a resolução automática de fonte direto (sem formulário
// de URL, ESPECIFICACAO.md §4): `POST /api/admin/jobs` (modo "site") resolve
// e cria o job no mesmo request; se o site tiver mais de um resultado
// possível, `DialogoDeFonteAmbigua` resolve inline e a captura é reenviada.
export default function PaginaDoAnime({ jobsPorEpisodio }) {
  const { id } = useParams();
  const animeId = Number(id);
  const navigate = useNavigate();
  const focoTitulo = useFocoAoMontar(id);

  const {
    dados: anime,
    erro: erroAnime,
    recarregar: recarregarAnime,
  } = useRecurso(() => obterAnime(animeId), [animeId]);
  const animeNaoEncontrado = erroAnime instanceof ErroDeApi && erroAnime.status === 404;

  const episodios = useRecurso(() => listarEpisodios(animeId), [animeId]);

  // Sem isto, LinhaDeEpisodio.jsx (ramo `episodio.status === 'pronto'`) fica
  // preso ao status local desatualizado até um refresh manual da página,
  // mesmo o WebSocket já sabendo que o job terminou — os outros status
  // (baixando/upscaling/etc.) já são reativos via `job?.status` direto
  // (LinhaDeEpisodio.jsx), só a transição pra "pronto" depende de refetch.
  // Auto-encerra: depois do recarregar, `episodio.status` já bate com
  // `job.status` e a condição para de disparar. `'liberado'` (backend/
  // core/enums.py::StatusEpisodio, mesmo literal usado sem importar o enum
  // em LinhaDeEpisodio.jsx) precisa ficar de fora dessa exclusão: é um
  // estado TERMINAL (episódio assistido até o fim, feature
  // "liberação automática") que nunca converge pra `'pronto'` como os
  // demais status intermediários — o `Job` daquele download continua
  // `pronto` pra sempre, então sem esta exclusão a condição ficaria presa em
  // `true` permanentemente pra qualquer episódio liberado, e como
  // `jobsPorEpisodio` é o Map global de `/ws/admin` (todos os jobs do app,
  // referência nova a cada `job_atualizado`, não só desta página) o efeito
  // dispararia `episodios.recarregar()` a cada tick de QUALQUER job ativo no
  // sistema.
  useEffect(() => {
    const algumProntoNaoRefletido = (episodios.dados ?? []).some((episodio) => {
      const job = jobsPorEpisodio.get(episodio.id);
      return job?.status === 'pronto' && episodio.status !== 'pronto' && episodio.status !== 'liberado';
    });
    if (algumProntoNaoRefletido) episodios.recarregar();
    // mesmo caso de `capturar`/`aoConfirmarFonte` mais abaixo: `episodios`
    // inteiro (useRecurso.js) é um literal novo a cada render — declará-lo
    // aqui rodaria o efeito em todo render, não só quando os dados mudam.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobsPorEpisodio, episodios.dados, episodios.recarregar]);

  const [numeroCapturando, setNumeroCapturando] = useState(null);
  const [erroCaptura, setErroCaptura] = useState(null);
  const [fonteAmbigua, setFonteAmbigua] = useState(null); // { dominio, candidatos, numero }

  const [confirmandoRemocao, setConfirmandoRemocao] = useState(false);
  const [removendo, setRemovendo] = useState(false);
  const [erroRemocao, setErroRemocao] = useState(null);

  // Troca manual de fonte por site — solução barata pedida explicitamente em
  // vez da modelagem completa (versão como parte da chave de resolução de
  // fonte). `FonteAnime` (backend/models/fonte_anime.py) tem PK composta
  // (anime_id, site_dominio) com só UM `identificador_no_site` por par —
  // confirmar uma fonte aqui SOBRESCREVE o que já estava mapeado pra aquele
  // domínio (troca, não soma) — não dá pra guardar legendado e dublado do
  // mesmo site ao mesmo tempo. `versaoAtiva` é só o rótulo que o usuário
  // escolheu pra essa fonte (nunca inferido do texto do candidato — heurística
  // tipo `.includes('dublado')` quebraria silenciosamente com outra
  // convenção de site): `Episodio.versao` já era só rótulo antes desta
  // frente (nome de arquivo/pasta + identidade do episódio no banco, não
  // influencia qual fonte é resolvida — `extractors/resolucao.py`), então
  // aqui só passamos a alimentá-lo com a escolha real em vez do hardcode
  // anterior. Modelagem completa (versão dentro da chave de `FonteAnime`/
  // `resolver_fonte_do_anime`, com migration, permitindo dublado E legendado
  // do mesmo domínio ao mesmo tempo) é trabalho futuro documentado, não
  // implementado aqui — mesmo espírito do docstring de escopo em
  // `backend/extractors/animesdrive.py`.
  const [trocandoFonte, setTrocandoFonte] = useState(false);
  const [confirmandoTrocaFonte, setConfirmandoTrocaFonte] = useState(false);
  const [erroTrocaFonte, setErroTrocaFonte] = useState(null);
  const [versaoAtiva, setVersaoAtiva] = useState('legendado');

  // `versaoAtiva` pode ser 'desconhecida' (episódio mais recente veio de uma
  // fonte NAO_DIFERENCIADA) — válido pra EXIBIÇÃO (`ROTULO_VERSAO` já trata),
  // mas `resolver_fonte_do_anime` rejeita `DESCONHECIDA` como versão PEDIDA
  // (só aceita LEGENDADO/DUBLADO, `ValueError` não tratado vira 500 —
  // `extractors/resolucao.py`). Toda chamada de API que carrega "qual versão
  // eu quero" usa este valor grampeado, nunca `versaoAtiva` cru; convenção
  // "sem confirmação = legendado" é a mesma já usada no restante do sistema
  // pra ausência de marcador.
  const versaoPedida = versaoAtiva === 'desconhecida' ? 'legendado' : versaoAtiva;

  // Declarado depois de `versaoPedida` de propósito: a listagem remota agora
  // reflete a versão ativa (senão a grade mostraria episódios da versão
  // errada quando o usuário troca) — precisa da variável já existir.
  const remotos = useRecurso(
    () => listarEpisodiosRemotos(animeId, versaoPedida),
    [animeId, versaoPedida]
  );

  // Hidrata `versaoAtiva` com prioridade: 1) `anime.versao_confirmada_mais_recente`
  // (a fonte confirmada mais recentemente via "Trocar fonte" — pode ainda não
  // ter gerado nenhum download; `null` = anime sem nenhuma `FonteAnime`
  // mapeada ainda, cai pro item 2); 2) na ausência dele, o episódio LOCAL mais
  // recentemente capturado (`episodios.dados`, traz `EpisodioSaida.versao` —
  // backend/api/esquemas.py). Critério de "mais recente" pro episódio é
  // `criado_em`, não `numero`: nada garante que os episódios sejam capturados
  // em ordem crescente (ex. usuário troca pra dublado e recaptura um episódio
  // antigo por último). `anime` e `episodios.dados` chegam de forma
  // assíncrona e independente (`useRecurso`, cada um pode chegar antes ou
  // depois do outro) — um único efeito reagindo aos dois evita que um rode
  // depois do outro com dado desatualizado e sobrescreva a prioridade acima
  // com dois efeitos concorrentes. Sem nenhuma das duas fontes ainda (anime
  // sem fonte mapeada E sem episódio capturado), mantém o default 'legendado'
  // do `useState` inicial.
  useEffect(() => {
    if (anime && anime.versao_confirmada_mais_recente != null) {
      setVersaoAtiva(anime.versao_confirmada_mais_recente);
      return;
    }
    if (!episodios.dados || episodios.dados.length === 0) return;
    const maisRecente = episodios.dados.reduce((atual, episodio) =>
      !atual || new Date(episodio.criado_em) > new Date(atual.criado_em) ? episodio : atual
    , null);
    setVersaoAtiva(maisRecente.versao);
  }, [anime, episodios.dados]);

  // A própria listagem remota (não só a captura) pode bater em ambiguidade
  // na primeira visita a um anime recém-criado (`episodios-remotos` também
  // chama `resolver_fonte_do_anime`) — sem isto a página ficaria presa num
  // "tentar novamente" que nunca resolve sozinho. `numero: null` sinaliza
  // pra `aoConfirmarFonte` que é a listagem que deve ser refeita, não uma
  // captura pendente.
  useEffect(() => {
    if (remotos.erro instanceof ErroDeApi && remotos.erro.detail?.motivo === 'fonte_ambigua') {
      setFonteAmbigua({ ...remotos.erro.detail, numero: null });
    }
  }, [remotos.erro]);

  // Uma linha por posição de episódio, na ordem em que aparecem na grade.
  // `numero` sozinho não é suficiente como chave: mais de um rótulo remoto
  // pode mapear pro mesmo `numero` inteiro (ex. "7" e "07" — dedup por
  // rótulo cru em `extractors/base.py::EpisodioRemoto`, não mais por
  // `int(numero)`) — colapsar os dois numa célula só esconderia de volta a
  // divergência que esta frente existe pra corrigir. Quando isso acontece
  // E o número ainda não tem captura local (`!episodio`), uma linha por
  // rótulo é gerada, com `colisao: true` (todas disparando captura pelo
  // mesmo `numero` — o contrato de captura não distingue rótulo; o backend
  // resolve a ambiguidade de forma determinística e loga, ver
  // `extractors/servico.py`/`api/servicos/jobs.py`). Se já existe captura
  // local pro número, cai no caso de linha única abaixo (`episodio` truthy)
  // e uma eventual colisão remota fica sem representação própria na grade —
  // limitação residual conhecida, não resolvida por exigir estender o
  // contrato de captura por rótulo (fora do escopo desta frente). Rótulo não
  // numérico (`numero: null`) sempre vira uma linha à parte, no fim.
  const linhas = useMemo(() => {
    const dominioAtivo = remotos.dados?.dominio ?? null;
    // Todos os episódios locais por número, SEM filtro — usado abaixo pra
    // recuperar o episódio descartado por `pertenceAFonteAtiva` quando a
    // linha precisa dele (badge "assistido"/botão "Recapturar" em
    // LinhaDeEpisodio.jsx), já que `episodiosPorNumero` (filtrado, logo
    // abaixo) não o carrega mais.
    const todosLocaisPorNumero = new Map();
    (episodios.dados ?? []).forEach((episodio) => todosLocaisPorNumero.set(episodio.numero, episodio));

    const episodiosPorNumero = new Map();
    (episodios.dados ?? [])
      .filter((episodio) => pertenceAFonteAtiva(episodio, { dominioAtivo, versaoAtiva }))
      .forEach((episodio) => episodiosPorNumero.set(episodio.numero, episodio));

    const remotosPorNumero = new Map();
    const remotosSemNumero = [];
    (remotos.dados?.episodios ?? []).forEach((remoto) => {
      if (remoto.numero == null) {
        remotosSemNumero.push(remoto);
        return;
      }
      const lista = remotosPorNumero.get(remoto.numero) ?? [];
      lista.push(remoto);
      remotosPorNumero.set(remoto.numero, lista);
    });

    // União com os números locais SEM filtro (não `episodiosPorNumero.keys()`,
    // já filtrado acima): garante que um episódio descartado por
    // `pertenceAFonteAtiva` ainda gera uma linha (cai no ramo "não capturado"
    // logo abaixo) mesmo quando a listagem remota atual não inclui esse
    // número — nunca some da grade.
    const numerosOrdenados = [
      ...new Set([
        ...(episodios.dados ?? []).map((episodio) => episodio.numero),
        ...remotosPorNumero.keys(),
      ]),
    ].sort((a, b) => a - b);

    const linhasNumericas = numerosOrdenados.flatMap((numero) => {
      const episodio = episodiosPorNumero.get(numero) ?? null;
      // Só existe episódio descartado quando o filtrado (`episodio`) é nulo —
      // se `episodio` já é truthy, `todosLocaisPorNumero.get(numero)` é o
      // MESMO objeto (não há dois locais por número), então reatribuí-lo aqui
      // faria `LinhaDeEpisodio` tratar status "baixando"/"falhou" etc. como
      // "assistido/recapturar" por engano.
      const episodioDescartado = episodio ? null : (todosLocaisPorNumero.get(numero) ?? null);
      const remotosDoNumero = remotosPorNumero.get(numero) ?? [];
      if (episodio || remotosDoNumero.length <= 1) {
        return [
          {
            chave: `n-${numero}`,
            numero,
            rotulo: remotosDoNumero[0]?.rotulo ?? String(numero),
            colisao: false,
            episodio,
            episodioDescartado,
            // Thumb do episódio: preferir a do episódio já capturado
            // (`capa_path`, gravada na captura), depois a do descartado por
            // fonte/versão, e só então a da listagem remota atual. `null`
            // quando nenhuma fonte tem imagem — `LinhaDeEpisodio` omite a img.
            thumb:
              episodio?.capa_path ??
              episodioDescartado?.capa_path ??
              remotosDoNumero[0]?.thumb_url ??
              null,
          },
        ];
      }
      return remotosDoNumero.map((remoto) => ({
        chave: `n-${numero}-${remoto.rotulo}`,
        numero,
        rotulo: remoto.rotulo,
        colisao: true,
        episodio: null,
        episodioDescartado,
        thumb: remoto.thumb_url ?? null,
      }));
    });

    const linhasSemNumero = remotosSemNumero.map((remoto) => ({
      chave: `r-${remoto.rotulo}`,
      numero: null,
      rotulo: remoto.rotulo,
      colisao: false,
      episodio: null,
      thumb: remoto.thumb_url ?? null,
    }));

    return [...linhasNumericas, ...linhasSemNumero];
  }, [episodios.dados, remotos.dados, versaoAtiva]);

  // Fluxo de criação de job em modo "site" é síncrono no servidor e pode
  // levar até ~120s (resolver fonte + listar episódios dentro do próprio
  // request) — sem timeout curto, sem retry automático (abortar o fetch
  // client-side não cancela o job já criado no backend), botão desabilitado
  // enquanto dura.
  const capturar = useCallback(
    async (numero) => {
      setNumeroCapturando(numero);
      setErroCaptura(null);
      try {
        await criarJobSite({ animeId, numero, tipo: 'regular', versao: versaoPedida });
        episodios.recarregar();
      } catch (erroCapturado) {
        if (erroCapturado instanceof ErroDeApi && erroCapturado.detail?.motivo === 'fonte_ambigua') {
          setFonteAmbigua({ ...erroCapturado.detail, numero });
        } else if (
          erroCapturado instanceof ErroDeApi &&
          erroCapturado.detail?.motivo === 'episodio_ja_existe'
        ) {
          episodios.recarregar();
        } else if (
          erroCapturado instanceof ErroDeApi &&
          erroCapturado.detail?.motivo === 'versao_indisponivel'
        ) {
          setErroCaptura(
            `A versão ${erroCapturado.detail.versao} não está disponível nesta fonte para este anime — tente trocar de fonte ou de versão.`
          );
        } else {
          console.error('falha ao capturar episódio', erroCapturado);
          setErroCaptura(`Não foi possível capturar o episódio ${numero} — tente novamente.`);
        }
      } finally {
        setNumeroCapturando(null);
      }
    },
    // `episodios.recarregar` é a única parte de `episodios` usada aqui e é
    // estável (useRecurso.js: useCallback com deps vazias) — declarar o
    // objeto inteiro satisfaria o eslint mas o recriaria a cada render
    // (useRecurso.js devolve um literal novo sempre), anulando a memoização.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [animeId, episodios.recarregar, versaoPedida]
  );

  const aoConfirmarFonte = useCallback(
    async (candidato) => {
      if (!fonteAmbigua) return;
      const { dominio, numero } = fonteAmbigua;
      setFonteAmbigua(null);
      try {
        await confirmarFonte(animeId, {
          dominio,
          identificador: candidato.identificador,
          tituloExibicao: candidato.titulo_exibicao,
          url: candidato.url,
          versao: candidato.versao ?? null,
        });
        if (numero != null) {
          await capturar(numero);
        } else {
          remotos.recarregar();
        }
      } catch (erroCapturado) {
        console.error('falha ao confirmar fonte', erroCapturado);
        setErroCaptura('Não foi possível confirmar a fonte — tente novamente.');
      }
    },
    // mesmo caso de `capturar` acima: `remotos.recarregar` é estável,
    // listar `remotos` inteiro só recriaria a callback a cada render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fonteAmbigua, animeId, capturar, remotos.recarregar]
  );

  const confirmarRemocao = useCallback(async () => {
    setRemovendo(true);
    setErroRemocao(null);
    try {
      await removerAnime(animeId);
      navigate('/animes');
    } catch (erroCapturado) {
      if (erroCapturado instanceof ErroDeApi && erroCapturado.detail?.motivo === 'job_em_execucao') {
        setErroRemocao('Este anime tem uma captura em andamento — aguarde terminar antes de remover.');
      } else {
        console.error('falha ao remover anime do catálogo', erroCapturado);
        setErroRemocao('Não foi possível remover este anime — tente novamente.');
      }
    } finally {
      setRemovendo(false);
    }
  }, [animeId, navigate]);

  // Fecha o dialog (cancelar, ou Esc/backdrop via DialogoDeConfirmacao) e
  // limpa `erroRemocao` junto — sem isto, um erro de uma tentativa anterior
  // "vazaria" pra próxima abertura do dialog.
  const fecharDialogoRemocao = useCallback(() => {
    setConfirmandoRemocao(false);
    setErroRemocao(null);
  }, []);

  // Confirma a fonte escolhida pro domínio do candidato (sobrescreve
  // `FonteAnime` desse domínio, ver comentário do bloco de estado acima) e
  // grava `versao` como o rótulo ativo pras próximas capturas. Diferente de
  // `aoConfirmarFonte` (fluxo de ambiguidade automática, que sempre segue
  // pra `capturar` de um episódio específico): aqui não há captura pendente
  // — só troca a fonte e fecha o diálogo; a lista remota é atualizada porque
  // pode ter mudado (domínio diferente do que estava resolvido antes).
  const aoConfirmarTrocaDeFonte = useCallback(
    async (candidato, versao) => {
      setConfirmandoTrocaFonte(true);
      setErroTrocaFonte(null);
      try {
        // `versao` enviado ao servidor é a verdade que a API já conhece
        // sobre ESTE candidato (`candidato.versao`, round-trip de
        // `buscar-fontes`) — não o `versao` recebido como argumento aqui, que
        // é a escolha/intenção de captura do usuário e serve só pra
        // `setVersaoAtiva` abaixo. Os dois podem divergir quando o site não
        // diferencia (`candidato.versao === null` mas o usuário escolheu
        // 'legendado'/'dublado' manualmente nos dois botões do diálogo).
        await confirmarFonte(animeId, {
          dominio: candidato.dominio,
          identificador: candidato.identificador,
          tituloExibicao: candidato.titulo_exibicao,
          url: candidato.url,
          versao: candidato.versao ?? null,
        });
        setVersaoAtiva(versao);
        setTrocandoFonte(false);
        // Não é redundante mesmo com `remotos` agora dependendo de
        // `versaoAtiva`: se o usuário troca de domínio SEM trocar de versão
        // (ex. legendado no site A → legendado no site B), `versaoAtiva` não
        // muda, o efeito de `remotos` não dispara sozinho, e sem este
        // `recarregar()` explícito a grade continuaria mostrando a listagem
        // do domínio antigo.
        remotos.recarregar();
      } catch (erroCapturado) {
        console.error('falha ao trocar fonte', erroCapturado);
        setErroTrocaFonte('Não foi possível confirmar esta fonte — tente novamente.');
      } finally {
        setConfirmandoTrocaFonte(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [animeId, remotos.recarregar]
  );

  const fecharDialogoTrocaDeFonte = useCallback(() => {
    setTrocandoFonte(false);
    setErroTrocaFonte(null);
  }, []);

  return (
    <>
      {/* `fase="revelado"` fixo, mesmo uso de `paginas/Galeria.jsx` — não há
          scrub de vídeo aqui, a navbar já nasce visível/interativa. Sem
          `termoBusca`/`aoMudarBusca`: esta página não tem uma lista pra
          filtrar, então a caixa de busca nem renderiza (ver
          `components/BarraDeNavegacao.jsx`). */}
      <BarraDeNavegacao fase="revelado" />
      <main className="px-6 pb-16 pt-24 md:px-10">
        {/* Header ampliado — vira o conteúdo central da página (capa e
            título maiores, mais respiro) em vez de um preâmbulo estreito
            acima da grade; lista de episódios continua abaixo, sem herdar
            essa largura (max-w-4xl no container da lista, mais adiante) pra
            não esticar linha de episódio a ponto de ficar ilegível em telas
            largas. */}
        <header className="mb-10 flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex flex-col gap-6 sm:flex-row sm:items-start">
            {anime?.capa_path && (
              <img
                src={anime.capa_path}
                alt=""
                className="h-56 w-40 flex-none rounded-lg border border-neon-soft object-cover sm:h-72 sm:w-52"
              />
            )}
            <div>
              <h1
                ref={focoTitulo}
                tabIndex={-1}
                className="mb-3 text-3xl font-semibold text-white outline-none sm:text-4xl md:text-5xl"
              >
                {anime?.titulo ?? `Anime #${animeId}`}
                {anime?.ano ? ` (${anime.ano})` : ''}
              </h1>
              {anime?.sinopse && (
                <p className="max-w-2xl text-sm text-ink-muted sm:text-base">{anime.sinopse}</p>
              )}
            </div>
          </div>
          {!animeNaoEncontrado && (
            <button
              type="button"
              onClick={() => setConfirmandoRemocao(true)}
              className="flex-none rounded-lg border border-red-500/60 px-4 py-2 text-sm text-red-400 outline-none transition-colors hover:border-red-400 hover:bg-red-950/40 focus-visible:ring-2 focus-visible:ring-neon"
            >
              Remover do catálogo
            </button>
          )}
        </header>

        {erroAnime && (
          <div
            role="alert"
            className="mb-4 rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300"
          >
            {animeNaoEncontrado ? (
              'Este anime não foi encontrado — pode ter sido removido do catálogo.'
            ) : (
              <>
                Não foi possível carregar os dados do anime.{' '}
                <button type="button" onClick={recarregarAnime} className="underline">
                  Tentar novamente
                </button>
              </>
            )}
          </div>
        )}
        {remotos.erro && !animeNaoEncontrado && (
          <div
            role="alert"
            className="mb-4 rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300"
          >
            {remotos.erro instanceof ErroDeApi && remotos.erro.status === 404 ? (
              'Este anime não foi encontrado — pode ter sido removido do catálogo.'
            ) : (
              <>
                Não foi possível consultar a fonte remota.{' '}
                <button type="button" onClick={remotos.recarregar} className="underline">
                  Tentar novamente
                </button>
              </>
            )}
          </div>
        )}
        {erroCaptura && (
          <p role="alert" className="mb-4 text-sm text-red-400">
            {erroCaptura}
          </p>
        )}
        {episodios.carregando && <p className="text-sm text-ink-muted">Carregando episódios…</p>}
        {remotos.carregando && (
          <p className="text-sm text-ink-muted">
            Consultando a fonte remota — isso pode levar até um minuto…
          </p>
        )}
        {!animeNaoEncontrado && (
          <div className="mb-4 flex flex-wrap items-center gap-3 text-xs text-ink-muted">
            {remotos.dados?.dominio && <span>Episódios resolvidos via <span className="font-bold">{remotos.dados.dominio}</span></span>}
            <span>Baixando como: <span className="font-bold">{ROTULO_VERSAO[versaoAtiva] ?? versaoAtiva}</span></span>
            {anime?.versoes_disponiveis &&
              versaoAtiva !== 'desconhecida' &&
              !anime.versoes_disponiveis.includes(versaoAtiva) && (
              // Hint de cache, não bloqueante — `versoes_disponiveis` reflete
              // o que já está mapeado em `FonteAnime`, não um live-probe. O
              // 409 `versao_indisponivel` (ver `capturar`) é o backstop real
              // quando a versão genuinamente não existe nesta fonte.
              <span className="text-amber-400">pode não estar disponível nesta fonte ainda</span>
            )}
            <button
              type="button"
              onClick={() => setTrocandoFonte(true)}
              className="rounded-md border border-border-chrome px-3 py-1 text-xs text-ink-muted outline-none transition-colors hover:border-neon hover:text-white focus-visible:ring-2 focus-visible:ring-neon"
            >
              Trocar fonte
            </button>
          </div>
        )}

        <div className="flex flex-col gap-2">
          {linhas.map(({ chave, numero, rotulo, colisao, episodio, episodioDescartado, thumb }) => {
            const job = episodio ? jobsPorEpisodio.get(episodio.id) : null;
            return (
              <LinhaDeEpisodio
                key={chave}
                numero={numero}
                rotulo={rotulo}
                colisao={colisao}
                episodio={episodio}
                episodioDescartado={episodioDescartado}
                thumb={thumb}
                // `remotos.dados?.dominio` já é o mesmo valor usado na linha
                // "Episódios resolvidos via {…}" acima — reusado direto aqui
                // em vez de expor pelo `useMemo` de `linhas`, que não precisa
                // dele pra montar as linhas em si (só `LinhaDeEpisodio` usa,
                // pra anotar a origem de um `episodioDescartado`).
                dominioAtivo={remotos.dados?.dominio ?? null}
                versaoAtiva={versaoAtiva}
                job={job}
                capturando={numero != null && numeroCapturando === numero}
                aoCapturar={capturar}
                animeId={animeId}
                animeTitulo={anime?.titulo}
              />
            );
          })}
        </div>

        {linhas.length === 0 && !episodios.carregando && !remotos.carregando && (
          <p className="text-sm text-ink-muted">Nenhum episódio encontrado.</p>
        )}

        <DialogoDeFonteAmbigua
          aberto={fonteAmbigua != null}
          dominio={fonteAmbigua?.dominio}
          candidatos={fonteAmbigua?.candidatos}
          aoEscolher={aoConfirmarFonte}
          aoFechar={() => setFonteAmbigua(null)}
        />

        <DialogoDeTrocaDeFonte
          aberto={trocandoFonte}
          tituloAnime={anime?.titulo ?? ''}
          aoConfirmar={aoConfirmarTrocaDeFonte}
          aoFechar={fecharDialogoTrocaDeFonte}
          confirmando={confirmandoTrocaFonte}
          erro={erroTrocaFonte}
        />

        <DialogoDeConfirmacao
          aberto={confirmandoRemocao}
          titulo="Remover do catálogo"
          mensagem={`Remover "${anime?.titulo ?? `Anime #${animeId}`}" do catálogo? Episódios e capturas associados serão apagados.`}
          erro={erroRemocao}
          aoConfirmar={confirmarRemocao}
          aoFechar={fecharDialogoRemocao}
          confirmando={removendo}
        />
      </main>
    </>
  );
}
