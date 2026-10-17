import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ROTULOS_STATUS, tomDoStatus } from '../components/LinhaDeEpisodio.jsx';

// Quanto tempo a notificação "episódio pronto" fica visível antes de sumir
// sozinha — mesmo valor usado pela notificação "novos episódios"
// (Galeria.jsx::DURACAO_NOTIFICACAO_NOVOS_EPS_MS).
const DURACAO_NOTIFICACAO_CAPTURA_PRONTA_MS = 5000;

// Notificação de ERRO (`erroCapturaIlha` abaixo) fica um pouco mais — o texto
// tende a ser mais longo ("{Anime} — episódio N: Falhou na extração") e o
// usuário precisa de mais tempo pra decidir se vale clicar. Sem risco de
// perder a informação de qualquer jeito: o card do episódio na página do
// anime já guarda o alerta de forma PERMANENTE (sem timer,
// `LinhaDeEpisodio.jsx::OverlayDeStatus`, tom "alerta") — esta notificação é
// só o aviso imediato, não a única fonte da informação.
const DURACAO_NOTIFICACAO_ERRO_CAPTURA_MS = 6000;

// Título do anime cortado nas 2 primeiras palavras (pedido do usuário,
// testado ao vivo: o título cheio de animes com nome longo transborda a
// cápsula — SeletorEmMenu.jsx tem um teto de largura fixo, `max-w-[320px]`,
// pra não disparar a própria transição de largura a cada troca de mensagem,
// ver comentário lá). "…" só quando corta de verdade — um título de 1-2
// palavras passa intacto.
function tituloCurto(titulo) {
  const palavras = titulo.split(' ');
  return palavras.length <= 2 ? titulo : `${palavras.slice(0, 2).join(' ')}…`;
}

// Os dois sinais de captura da ilha dinâmica (BarraDeNavegacao.jsx,
// `statusCapturaIlha`/`capturaProntaIlha`) — GLOBAL, cruza QUALQUER anime do
// app, direto do Map de WS (`jobsPorEpisodio`, App.jsx::Shell ->
// useEventosDeJobs.js) que já alimentava `components/Toasts.jsx` (o toast
// "concluído" saiu de lá, pedido do usuário, pra virar a notificação daqui).
// Hook único usado por Galeria.jsx e PaginaDoAnime.jsx (e Home, quando
// entrar) — antes cada página tinha sua própria cópia da lógica de diffing;
// consolidado aqui pra não duplicar (Escada de Minimalismo, CLAUDE.md §4) e
// pra garantir que as duas páginas mostrem exatamente o mesmo estado, não
// duas versões ligeiramente diferentes.
//
// `statusCapturaIlha` (contínuo, clicável): rótulo do PRIMEIRO job em
// progresso encontrado no Map inteiro — "{Anime} — episódio N: {Status}".
// Sem timer: some sozinho assim que nenhum job do Map está mais em
// progresso (não precisa saber POR QUE parou — terminou, falhou, ou o Map
// mudou por qualquer outro motivo). Clique (`aoClicarStatusCapturaIlha`) leva
// pra página DAQUELE anime (`job.anime_id`, backend/api/eventos.py —
// `_COLUNAS_JOB`), pedido do usuário: some não faz sentido navegar de novo
// pra onde você já está, então compara com `useParams().id` da rota atual
// (só a rota "/anime/:id" tem esse param — em qualquer outra página o
// clique sempre navega).
//
// `capturaProntaIlha` (transitório, clicável): diffing contra o snapshot
// anterior via ref (mesmo padrão que `Toasts.jsx` já usava) — só conta
// TRANSIÇÃO pra `pronto` (não todo job já pronto). Um único episódio
// concluído na mesma leva vira notificação com alvo de clique (`episodioId`,
// navega direto pro player); mais de um ao mesmo tempo é caso raro e a
// mensagem genérica fica sem alvo (ambíguo qual player abrir).
//
// `erroCapturaIlha` (transitório, clicável): mesmo diffing, mesma referência
// (`anterioresRef` compartilhado com `capturaProntaIlha` — um único Map de
// "antes", não dois, pra não duplicar a leitura do mesmo snapshot) — só
// conta TRANSIÇÃO pro tom "alerta" (`tomDoStatus`, cobre
// `falhou`/`falhou_extracao`/`aguardando_intervencao`). Migrado de
// `components/Toasts.jsx` (pedido do usuário, 2026-09-27): antes um toast
// solto no canto da tela, agora a mesma cápsula da navbar, com PRIORIDADE
// MÁXIMA na fila de `hooks/useFilaDaIlha.js` — falha não se
// autorresolve como um "pronto", então tampa até a notificação de sucesso
// enquanto estiver visível. Clique (`aoClicarErroCapturaIlha`) leva pra
// página do anime (`job.anime_id`), mesmo alvo de `aoClicarStatusCapturaIlha`
// — e sempre dispensa a notificação, mesmo quando já está na página (ao
// contrário do status contínuo, este é um aviso pontual: uma vez visto, não
// precisa ficar ocupando a cápsula).
//
// `snapshotId` (App.jsx::Shell -> eventos/useEventosDeJobs.js): usado só pra
// saber QUANDO resetar `anterioresRef` sem notificar — bug real medido
// (2026-09-27): a referência costumava semear no PRIMEIRO EFEITO deste hook,
// que roda logo no mount, ANTES da conexão WS existir de verdade — nesse
// momento `jobsPorEpisodio` é sempre o Map vazio do `useState` inicial de
// `useEventosDeJobs`, nunca o snapshot real. Quando o snapshot de verdade
// chegava (podendo já trazer jobs `falhou`/`aguardando_intervencao`/`pronto`
// pré-existentes, dentro da janela de 10min do backend,
// `api/eventos.py::_JANELA_JOBS_FINALIZADOS_MIN`), o efeito já tinha
// "gastado" seu único reset no Map vazio anterior — e diffava o snapshot
// inteiro contra "nada", dizendo que TODOS aqueles jobs tinham acabado de
// mudar agora mesmo. Resultado: notificação falsa (às vezes "N episódios com
// falha" genérico) piscando assim que a página carrega ou reconecta, sem
// nenhuma falha nova de verdade. Fix: `snapshotId` incrementa só quando
// `useEventosDeJobs` processa uma mensagem tipo "snapshot" (conexão inicial
// OU qualquer reconexão) — o efeito abaixo reseta a referência toda vez que
// ele muda, e só faz diff de verdade quando `jobsPorEpisodio` muda com o
// MESMO `snapshotId` (ou seja, uma mensagem "job_atualizado" ao vivo). Um
// SEGUNDO ref (`primeiraExecucaoRef`, ver o efeito) cobre a mesma armadilha
// quando é a PÁGINA que troca, não a conexão: `snapshotId` é compartilhado
// entre Inicio/Galeria/PaginaDoAnime (vem do App.jsx), então ao navegar pra
// uma página nova o valor já pode estar em qualquer número > 0 — só o
// "primeira vez que ESTA instância do hook roda" garante o reset, já que
// `snapshotId !== ultimoSnapshotIdRef.current` sozinho dava falso (os dois
// nasciam iguais).
export function useStatusDeCapturaIlha(jobsPorEpisodio, snapshotId) {
  const navigate = useNavigate();
  const { id: idDaRotaAtual } = useParams();

  const jobEmProgresso = useMemo(() => {
    for (const job of jobsPorEpisodio.values()) {
      if (tomDoStatus(job.status) === 'progresso') return job;
    }
    return null;
  }, [jobsPorEpisodio]);

  const statusCapturaIlha = jobEmProgresso
    ? `${tituloCurto(jobEmProgresso.anime_titulo)} — episódio ${jobEmProgresso.episodio_numero}: ${
        ROTULOS_STATUS[jobEmProgresso.status] ?? jobEmProgresso.status
      }`
    : null;

  // Já estar na página daquele anime (mesmo `id` da rota atual) é um no-op —
  // `Number(idDaRotaAtual)` porque `useParams` sempre devolve string; fora
  // da rota "/anime/:id" o param nem existe (`undefined`), `Number(undefined)`
  // é `NaN`, nunca bate com um `anime_id` real, então o clique sempre navega.
  const aoClicarStatusCapturaIlha = useCallback(() => {
    if (jobEmProgresso == null) return;
    if (Number(idDaRotaAtual) === jobEmProgresso.anime_id) return;
    navigate(`/anime/${jobEmProgresso.anime_id}`);
  }, [jobEmProgresso, idDaRotaAtual, navigate]);

  const [capturaProntaIlha, setCapturaProntaIlha] = useState(null); // { texto, episodioId } | null
  const [erroCapturaIlha, setErroCapturaIlha] = useState(null); // { texto, animeId } | null
  const anterioresRef = useRef(new Map());
  const ultimoSnapshotIdRef = useRef(snapshotId);
  const primeiraExecucaoRef = useRef(true);
  useEffect(() => {
    // `primeiraExecucaoRef`: cobre o MONTE desta instância específica do
    // hook, independente do valor de `snapshotId` — bug real medido
    // (2026-09-27), passo 2: PaginaDoAnime.jsx monta com sua PRÓPRIA
    // `anterioresRef` vazia, mas `snapshotId` já podia estar em qualquer
    // valor > 0 (herdado do App.jsx, compartilhado entre TODAS as páginas —
    // só reflete quando o WS resincronizou, não quando ESTE componente
    // nasceu). Sem este ref, `snapshotId !== ultimoSnapshotIdRef.current`
    // (ambos inicializados com o MESMO valor corrente) dava falso — a
    // instância nova pulava direto pro diff, comparando o Map cheio contra
    // sua baseline vazia e alegando que TODOS os jobs tinham acabado de
    // mudar. Com isto, o PRIMEIRO efeito de qualquer instância sempre reseta
    // sem notificar; só depois disso um `snapshotId` novo (reconexão de
    // verdade) também reseta.
    if (primeiraExecucaoRef.current || snapshotId !== ultimoSnapshotIdRef.current) {
      primeiraExecucaoRef.current = false;
      ultimoSnapshotIdRef.current = snapshotId;
      anterioresRef.current = jobsPorEpisodio;
      return;
    }
    const anteriores = anterioresRef.current;
    const concluidos = [];
    const falhas = [];
    for (const [episodioId, job] of jobsPorEpisodio) {
      const statusAnterior = anteriores.get(episodioId)?.status;
      if (statusAnterior === job.status) continue;
      if (job.status === 'pronto') {
        concluidos.push({ episodioId, numero: job.episodio_numero, animeTitulo: job.anime_titulo });
      } else if (tomDoStatus(job.status) === 'alerta') {
        falhas.push({
          animeId: job.anime_id,
          numero: job.episodio_numero,
          animeTitulo: job.anime_titulo,
          status: job.status,
        });
      }
    }
    anterioresRef.current = jobsPorEpisodio;

    if (concluidos.length === 1) {
      const [unico] = concluidos;
      setCapturaProntaIlha({
        texto: `${tituloCurto(unico.animeTitulo)} — episódio ${unico.numero} pronto`,
        episodioId: unico.episodioId,
      });
    } else if (concluidos.length > 1) {
      setCapturaProntaIlha({ texto: `${concluidos.length} episódios prontos`, episodioId: null });
    }

    if (falhas.length === 1) {
      const [unica] = falhas;
      setErroCapturaIlha({
        texto: `${tituloCurto(unica.animeTitulo)} — episódio ${unica.numero}: ${
          ROTULOS_STATUS[unica.status] ?? unica.status
        }`,
        animeId: unica.animeId,
      });
    } else if (falhas.length > 1) {
      setErroCapturaIlha({ texto: `${falhas.length} episódios com falha`, animeId: null });
    }
  }, [jobsPorEpisodio, snapshotId]);

  // Some sozinha alguns segundos depois de aparecer (o timer manda, não
  // navegação nem scroll — mesmo padrão de `notificacaoNovosEps`,
  // Galeria.jsx).
  useEffect(() => {
    if (!capturaProntaIlha) return undefined;
    const tempo = setTimeout(() => setCapturaProntaIlha(null), DURACAO_NOTIFICACAO_CAPTURA_PRONTA_MS);
    return () => clearTimeout(tempo);
  }, [capturaProntaIlha]);

  // Mesmo padrão de timer, duração própria (ver DURACAO_NOTIFICACAO_ERRO_CAPTURA_MS).
  useEffect(() => {
    if (!erroCapturaIlha) return undefined;
    const tempo = setTimeout(() => setErroCapturaIlha(null), DURACAO_NOTIFICACAO_ERRO_CAPTURA_MS);
    return () => clearTimeout(tempo);
  }, [erroCapturaIlha]);

  // Clique na notificação (BarraDeNavegacao.jsx): vai direto pro player
  // quando um único episódio disparou; com mais de um, só dispensa.
  const aoClicarCapturaProntaIlha = useCallback(() => {
    if (capturaProntaIlha?.episodioId != null) {
      navigate(`/assistir/${capturaProntaIlha.episodioId}`);
    }
    setCapturaProntaIlha(null);
  }, [capturaProntaIlha, navigate]);

  // Clique no aviso de erro: leva pra página do anime (exceto se já estiver
  // nela, mesmo critério de `aoClicarStatusCapturaIlha`) e sempre dispensa —
  // aviso pontual, não faz sentido continuar ocupando a cápsula depois de
  // visto. Sem `animeId` (mais de uma falha na mesma leva, alvo ambíguo), só
  // dispensa.
  const aoClicarErroCapturaIlha = useCallback(() => {
    if (erroCapturaIlha?.animeId != null && Number(idDaRotaAtual) !== erroCapturaIlha.animeId) {
      navigate(`/anime/${erroCapturaIlha.animeId}`);
    }
    setErroCapturaIlha(null);
  }, [erroCapturaIlha, idDaRotaAtual, navigate]);

  return {
    statusCapturaIlha,
    aoClicarStatusCapturaIlha,
    capturaProntaIlha: capturaProntaIlha?.texto ?? null,
    aoClicarCapturaProntaIlha,
    erroCapturaIlha: erroCapturaIlha?.texto ?? null,
    aoClicarErroCapturaIlha,
  };
}
