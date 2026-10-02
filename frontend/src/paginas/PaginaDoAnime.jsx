import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ErroDeApi } from '../api/cliente.js';
import {
  confirmarFonte,
  criarAnime,
  criarJobSite,
  listarEpisodios,
  listarEpisodiosRemotos,
  listarRelacionados,
  marcarTodosAssistidos,
  obterAnime,
  removerAnime,
} from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import AnimeCard from '../components/AnimeCard.jsx';
import BarraDeNavegacao from '../components/BarraDeNavegacao.jsx';
import DialogoDeConfirmacao from '../components/DialogoDeConfirmacao.jsx';
import DialogoDeFonteAmbigua from '../components/DialogoDeFonteAmbigua.jsx';
import DialogoDeTrocaDeFonte from '../components/DialogoDeTrocaDeFonte.jsx';
import LinhaDeEpisodio from '../components/LinhaDeEpisodio.jsx';
import MenuDeAcoesDoAnime from '../components/MenuDeAcoesDoAnime.jsx';
import SeletorDeTemporada from '../components/SeletorDeTemporada.jsx';
import SinopseEmFoco from '../components/SinopseEmFoco.jsx';
import { nomeDaFonte } from '../fontes.js';
import { useFocoAoMontar } from '../hooks/useFocoAoMontar.js';
import { useStatusDeCapturaIlha } from '../hooks/useStatusDeCapturaIlha.js';
import BlocoConteudoHero from '../inicio/BlocoConteudoHero.jsx';
import {
  gradienteHero,
  imagemEmAltaResolucao,
  CLASSE_PILL_HERO,
} from '../inicio/CarrosselDestaques.jsx';
import FileiraDeCards from '../inicio/FileiraDeCards.jsx';
import { textoDeProximaTemporada, tituloBaseDeTemporada } from '../inicio/franquia.js';
import { traduzirGenero } from '../inicio/generos.js';
import { PADDING_TITULO } from '../inicio/tamanhoDeCard.js';
import { usePreferencia } from '../player/hooks/usePreferencia.js';

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

// Chave da preferência lista/grade da lista de episódios (persistida por
// `usePreferencia` — mesmo prefixo `slime.` de `slime.preset`/`slime.hudVisivel`).
const CHAVE_MODO_VISUALIZACAO = 'slime.modoVisualizacaoEpisodios';

// Ícones do alternador grade/lista — SVG à mão (Escada de Minimalismo,
// CLAUDE.md §4, mesmo padrão de `player/Icones.jsx`): o `lucide-react` já
// instalado tem `LayoutGrid`/`List` equivalentes, mas nenhum dos dois suporta
// pintar só PARTE do ícone (a lib só preenche a peça inteira ou deixa tudo
// contorno) — sem cobrir a necessidade, mão na massa é o passo certo. Inspirado
// nos ícones `fad fa-th-large`/`fad fa-th-list` de um site de referência
// (2026-09-15) — a proposta inicial era duotone (metade pintada, metade
// contorno) só no `IconeGrade`; o `IconeLista` já nasceu com os 3 marcadores
// sólidos e as barras em opacidade reduzida, e o `IconeGrade` virou 100%
// sólido a pedido do usuário (mesma sessão), sem duotone. `width`/`height`
// (22 na lista, 20 na grade — ajuste fino pedido explícito do usuário,
// mesma sessão: com 22 os blocos cheios da grade pareciam pesados demais
// perto da lista) cabem na caixa útil dentro do `<button>` `h-8 w-8` com
// `border-2` (32px menos 2×2px de borda = 28px, com folga de cada lado): o
// botão passou a ter tamanho FIXO (não mais o padding+conteúdo de antes) só
// pra isso ser possível sem inflar o botão junto. `aria-hidden`: o texto
// acessível vem do `aria-label` de cada <button>.
const propsIconeVisualizacao = {
  viewBox: '0 0 24 24',
  width: 22,
  height: 22,
  'aria-hidden': 'true',
  focusable: 'false',
};

// Os 4 quadrados levam `stroke` além do `fill` (não só fill): sem ele, na
// versão duotone anterior, o par sem preenchimento parecia maior — o SVG
// centraliza o traço em cima do próprio path (1px vaza pra fora, 1px pra
// dentro), então o contorno tinha 1px a mais de borda-a-borda que o
// preenchido puro. Manter o mesmo `stroke`/`strokeWidth` nos 4 (mesmo agora
// que todos são sólidos) preserva essa borda externa idêntica.
function IconeGrade() {
  return (
    <svg {...propsIconeVisualizacao} width={20} height={20}>
      <rect x="3" y="3" width="7" height="7" rx="1" fill="currentColor" stroke="currentColor" strokeWidth="2" />
      <rect x="14" y="3" width="7" height="7" rx="1" fill="currentColor" stroke="currentColor" strokeWidth="2" />
      <rect x="3" y="14" width="7" height="7" rx="1" fill="currentColor" stroke="currentColor" strokeWidth="2" />
      <rect x="14" y="14" width="7" height="7" rx="1" fill="currentColor" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

function IconeLista() {
  return (
    <svg {...propsIconeVisualizacao}>
      <rect x="3" y="3.5" width="5" height="5" rx="1.5" fill="currentColor" />
      <rect x="3" y="9.5" width="5" height="5" rx="1.5" fill="currentColor" />
      <rect x="3" y="15.5" width="5" height="5" rx="1.5" fill="currentColor" />
      <rect x="10.5" y="4" width="10.5" height="4" rx="1.5" fill="currentColor" opacity="0.6" />
      <rect x="10.5" y="10" width="10.5" height="4" rx="1.5" fill="currentColor" opacity="0.6" />
      <rect x="10.5" y="16" width="10.5" height="4" rx="1.5" fill="currentColor" opacity="0.6" />
    </svg>
  );
}

// Rota "/anime/:id" — grade prontos/não capturados. Clique num episódio não
// capturado dispara a resolução automática de fonte direto (sem formulário
// de URL, ESPECIFICACAO.md §4): `POST /api/admin/jobs` (modo "site") resolve
// e cria o job no mesmo request; se o site tiver mais de um resultado
// possível, `DialogoDeFonteAmbigua` resolve inline e a captura é reenviada.
export default function PaginaDoAnime({ jobsPorEpisodio, snapshotId }) {
  const { id } = useParams();
  const animeId = Number(id);
  const navigate = useNavigate();
  const focoTitulo = useFocoAoMontar(id);

  // Navegação client-side não reseta o scroll como um carregamento de página
  // real faria — sem isto, a página do anime herda o scroll de onde o usuário
  // estava (Home/Galeria, ou este mesmo componente reaproveitado ao trocar de
  // anime via "Relacionados", sem remount). `useLayoutEffect` (não
  // `useEffect`): roda antes do primeiro paint, então o salto pra posição 0
  // não chega a ser visível.
  useLayoutEffect(() => {
    window.scrollTo(0, 0);
  }, [animeId]);

  const {
    dados: anime,
    carregando: animeCarregando,
    erro: erroAnime,
    recarregar: recarregarAnime,
  } = useRecurso(() => obterAnime(animeId), [animeId]);
  const animeNaoEncontrado = erroAnime instanceof ErroDeApi && erroAnime.status === 404;

  // Chave 'episodios' (invalidacao.js): recarrega sozinho quando
  // `marcarAssistido`/`marcarTodosAssistidos`/`salvarProgresso`/
  // `liberarEpisodio` resolve — inclusive quando disparado por
  // `PaginaDoPlayer.jsx` já desmontada (saída fire-and-forget do player).
  const episodios = useRecurso(() => listarEpisodios(animeId), [animeId], 'episodios');

  // "Relacionados" (seção abaixo da grade de episódios): recomendações da
  // AniList + relações de franquia não sequenciais. `[]` quando o anime ainda
  // não tem `anilist_id` — `FileiraDeCards` já não renderiza nada pra lista
  // vazia, sem precisar de estado de erro/loading explícito aqui (conteúdo
  // suplementar best-effort, mesmo espírito do backend).
  const relacionados = useRecurso(() => listarRelacionados(animeId), [animeId]);

  // Ativação de um card de "Relacionados" ainda não catalogado: materializa
  // no catálogo local (`POST /api/admin/animes`, get-or-create por slug) e
  // navega pro anime criado — mesmo payload/fluxo de
  // `paginas/Inicio.jsx::materializarEIrPara`, duplicado aqui de propósito
  // (a versão de lá fecha sobre estado só da Home — `chaveEmMaterializacao`,
  // `navigate` da Home — reusar exigiria içar tudo pra um hook compartilhado
  // por uma única chamada). Item já catalogado (`anime.anime_id` presente)
  // nem chama isto — `AnimeCard` renderiza `<Link>` direto nesse caso.
  const [relacionadoEmVoo, setRelacionadoEmVoo] = useState(null);
  const [erroRelacionado, setErroRelacionado] = useState(null);
  const materializarRelacionado = useCallback(
    async (item) => {
      if (relacionadoEmVoo != null) return;
      setRelacionadoEmVoo(item.anilist_id);
      setErroRelacionado(null);
      try {
        const criado = await criarAnime({
          titulo: item.titulo_romaji,
          tituloIngles: item.titulo_ingles ?? undefined,
          anilistId: item.anilist_id ?? undefined,
          capaUrl: item.capa_url ?? item.banner_url ?? undefined,
          bannerUrl: item.banner_url ?? undefined,
          capaCor: item.capa_cor ?? undefined,
          generos: item.generos ?? undefined,
          sinopse: item.sinopse ?? undefined,
          formato: item.formato ?? undefined,
        });
        navigate(`/anime/${criado.id}`);
      } catch (erroCapturado) {
        console.error('falha ao adicionar anime relacionado ao catálogo', erroCapturado);
        setErroRelacionado('Não foi possível adicionar este anime ao catálogo — tente novamente.');
      } finally {
        setRelacionadoEmVoo(null);
      }
    },
    [relacionadoEmVoo, navigate]
  );

  // Guard anti-loop do efeito abaixo: cada par `episodio.id:job.id` cujo job
  // já chegou a `pronto` sem o REST ainda refletir dispara UM `recarregar()`,
  // nunca mais. Sem isto, um episódio que o REST nunca converge pra
  // `pronto`/`liberado` (fonte quebrada, status terminal fora dos dois
  // esperados) mantém a condição `true` e o efeito re-dispara a cada
  // atualização de `episodios.dados` que ele mesmo causou — enxurrada de
  // `GET /episodios`. Zerado ao trocar de anime (efeito de reset mais abaixo).
  const jaRecarregadoRef = useRef(new Set());

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
    const naoVistos = (episodios.dados ?? []).filter((episodio) => {
      const job = jobsPorEpisodio.get(episodio.id);
      if (!job || job.status !== 'pronto') return false;
      if (episodio.status === 'pronto' || episodio.status === 'liberado') return false;
      return !jaRecarregadoRef.current.has(`${episodio.id}:${job.id}`);
    });
    if (naoVistos.length > 0) {
      naoVistos.forEach((episodio) => {
        const job = jobsPorEpisodio.get(episodio.id);
        jaRecarregadoRef.current.add(`${episodio.id}:${job.id}`);
      });
      episodios.recarregar();
    }
    // mesmo caso de `capturar`/`aoConfirmarFonte` mais abaixo: `episodios`
    // inteiro (useRecurso.js) é um literal novo a cada render — declará-lo
    // aqui rodaria o efeito em todo render, não só quando os dados mudam.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobsPorEpisodio, episodios.dados, episodios.recarregar]);

  // `statusCapturaIlha`/`capturaProntaIlha`/`erroCapturaIlha`: os três
  // sinais de captura da ilha, GLOBAL (qualquer anime do app, não só este)
  // — hook compartilhado com Galeria.jsx (hooks/useStatusDeCapturaIlha.js),
  // substitui os toasts "concluído"/erro que existiam em
  // components/Toasts.jsx (removido, 2026-09-27 — os dois migraram pra cá).
  // Antes esta página tinha sua própria versão ESCOPADA a `episodios.dados`
  // (só este anime) — unificada pra global: mais consistente com a Galeria
  // (mesmo texto, mesmo comportamento em qualquer página) e mais simples
  // (sem duplicar a lógica de diffing, sem precisar resetar nada ao trocar
  // de anime).
  const {
    statusCapturaIlha,
    aoClicarStatusCapturaIlha,
    capturaProntaIlha,
    aoClicarCapturaProntaIlha,
    erroCapturaIlha,
    aoClicarErroCapturaIlha,
  } = useStatusDeCapturaIlha(jobsPorEpisodio, snapshotId);

  const [numeroCapturando, setNumeroCapturando] = useState(null);
  const [erroCaptura, setErroCaptura] = useState(null);
  const [fonteAmbigua, setFonteAmbigua] = useState(null); // { dominio, candidatos, numero }

  // Alternador lista/grade da lista de episódios, persistido por navegador via
  // o hook padrão de preferências (try/catch de leitura e escrita já lá
  // dentro). O guard `=== 'grade' ? … : 'lista'` normaliza qualquer valor
  // inesperado no storage (corrupção / edição manual) pros dois únicos modos
  // válidos — mantém `aria-pressed` e o container sempre coerentes.
  const [modoArmazenado, mudarModoVisualizacao] = usePreferencia(CHAVE_MODO_VISUALIZACAO, 'lista');
  const modoVisualizacao = modoArmazenado === 'grade' ? 'grade' : 'lista';

  const [confirmandoRemocao, setConfirmandoRemocao] = useState(false);
  // Modo foco da sinopse (components/SinopseEmFoco.jsx).
  const [sinopseEmFoco, setSinopseEmFoco] = useState(false);
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

  // `versaoAtiva` nasce no default 'legendado' do `useState` e só vira a
  // versão real do anime depois que o efeito de hidratação (mais abaixo)
  // roda. `versaoHidratada` marca esse momento — até lá o fetch de `remotos`
  // fica represado, senão a listagem remota resolve a fonte pra versão errada
  // (ex. anime dublado → `?versao=legendado` → sem `FonteAnime` mapeada →
  // `resolver_fonte_do_anime` varre a cadeia do registro → outra fonte →
  // Cloudflare/502). Reset por `animeId`: a rota "/anime/:id" reaproveita
  // este componente ao navegar entre animes (params mudam, sem remount), e um
  // `versaoHidratada` preso em `true` deixaria `remotos` buscar o anime novo
  // com a `versaoAtiva` do anterior.
  const [versaoHidratada, setVersaoHidratada] = useState(false);
  useEffect(() => {
    setVersaoHidratada(false);
    setVersaoAtiva('legendado');
    jaRecarregadoRef.current = new Set();
  }, [animeId]);

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
    () =>
      versaoHidratada
        ? listarEpisodiosRemotos(animeId, versaoPedida)
        : // Ainda não hidratou a versão — não bate na fonte com um palpite.
          // Promise que nunca resolve: mantém `remotos.carregando` até as deps
          // mudarem (`versaoHidratada` vira true) e a busca real disparar, sem
          // piscar um "nenhum episódio" no intervalo. O cleanup de `useRecurso`
          // descarta esta promise pendente na próxima execução do efeito.
          new Promise(() => {}),
    [animeId, versaoPedida, versaoHidratada]
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
  // do `useState` inicial. Espera os DOIS recursos assentarem
  // (`!animeCarregando && !episodios.carregando`) antes de decidir: até lá a
  // versão real ainda pode chegar por qualquer um dos dois e a escolha seria
  // prematura. Só ao fim marca `versaoHidratada` — o gatilho que libera o
  // fetch de `remotos` (ver acima).
  useEffect(() => {
    if (animeCarregando || episodios.carregando) return;
    if (anime && anime.versao_confirmada_mais_recente != null) {
      setVersaoAtiva(anime.versao_confirmada_mais_recente);
    } else if (episodios.dados && episodios.dados.length > 0) {
      const maisRecente = episodios.dados.reduce((atual, episodio) =>
        !atual || new Date(episodio.criado_em) > new Date(atual.criado_em) ? episodio : atual
      , null);
      setVersaoAtiva(maisRecente.versao);
    }
    setVersaoHidratada(true);
  }, [anime, animeCarregando, episodios.dados, episodios.carregando]);

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
  // Fallback de thumb quando não há still do episódio: a arte do PRÓPRIO
  // anime (TMDB/AniList via `integrations/`). `banner_path` (horizontal,
  // mesmo formato 16/9 do card) antes de `capa_path` (pôster) — mesma
  // prioridade do hero acima.
  const thumbDoAnime = anime?.banner_path ?? anime?.capa_path ?? null;

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
            // Thumb do episódio: a listagem remota (`remotos.dados`) já vem
            // do servidor com o overlay de still do TMDB aplicado, com a
            // arte do anime como fallback quando o TMDB não tem aquele
            // episódio (`api/servicos/fontes.py::_sobrepor_stills_de_
            // episodios`) — nunca mais o thumb cru da fonte de scraping.
            // `thumbDoAnime` aqui é só a rede de segurança do CLIENTE: um
            // episódio que só existe local (`episodioDescartado`, fonte
            // trocada) e não aparece na listagem remota atual, ou a própria
            // listagem ainda carregando/com erro.
            thumb: remotosDoNumero[0]?.thumb_url ?? thumbDoAnime,
            // Título/sinopse: mesma prioridade do thumb acima (remoto — já
            // com o overlay TMDB do servidor — antes do local), mas SEM
            // fallback pra arte do anime: `episodio?.titulo`/`.sinopse` só
            // socorrem quando a listagem remota atual não trouxe este
            // episódio (`episodioDescartado`) ou ainda está carregando/com
            // erro; sem nenhum dos dois, ficam vazios (nunca inventa texto).
            titulo: remotosDoNumero[0]?.titulo ?? episodio?.titulo ?? null,
            sinopse: remotosDoNumero[0]?.sinopse ?? episodio?.sinopse ?? null,
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
        thumb: remoto.thumb_url ?? thumbDoAnime,
        titulo: remoto.titulo ?? null,
        sinopse: remoto.sinopse ?? null,
      }));
    });

    const linhasSemNumero = remotosSemNumero.map((remoto) => ({
      chave: `r-${remoto.rotulo}`,
      numero: null,
      rotulo: remoto.rotulo,
      colisao: false,
      episodio: null,
      thumb: remoto.thumb_url ?? thumbDoAnime,
      titulo: remoto.titulo ?? null,
      sinopse: remoto.sinopse ?? null,
    }));

    return [...linhasNumericas, ...linhasSemNumero];
  }, [episodios.dados, remotos.dados, versaoAtiva, thumbDoAnime]);

  // Estado do botão "Marcar como assistido" (abaixo): `true` só quando toda
  // linha NUMÉRICA da grade (`numero != null` — rótulos não numéricos, ex.
  // "Especial", ficam fora de escopo de captura/assistido e não contam) já
  // tem `assistido_em`, vindo de `episodio` (capturado) ou `episodioDescartado`
  // (liberado/outra fonte — `LinhaDeEpisodio.jsx` já trata os dois como
  // "✓ assistido"). Sem linha nenhuma ainda (anime sem episódios, ou tudo
  // carregando) fica `false` — nesse caso o botão seguir clicável não é
  // confuso, é só irrelevante.
  const tudoAssistido = useMemo(() => {
    const comNumero = linhas.filter((linha) => linha.numero != null);
    return (
      comNumero.length > 0 &&
      comNumero.every((linha) => (linha.episodio ?? linha.episodioDescartado)?.assistido_em != null)
    );
  }, [linhas]);

  // Dados derivados do bloco de conteúdo do hero (estilo AnimeFire, coluna
  // única). `fatos` é a ficha "ano / episódios / fonte / versão" do painel de
  // informações ABAIXO do hero (sinopse + fatos saíram de sobre a arte pra
  // esse painel — a fonte, `nomeDaFonte(remotos.dados.dominio)`, só aparece
  // depois que a listagem remota resolve; até lá o `.filter(Boolean)` a
  // omite);
  // os gêneros saem dela e viram pills próprias (`generosTraduzidos`,
  // até 3, traduzidos por `traduzirGenero` — mesmo recorte do card do
  // carrossel da Home). Declarado aqui (não junto de `anime`) porque a
  // contagem depende de `linhas`, que já une episódios locais + remotos.
  // `AnimeDetalheSaida` não expõe nota/rating — por isso o painel não tem
  // fato de rating, ao contrário do AnimeFire. Rótulo da versão via
  // `ROTULO_VERSAO` (mesmo mapa usado por LinhaDeEpisodio.jsx pra exibir a
  // versão).
  // Título do H1 — quando a franquia tem 2+ temporadas catalogadas, o marcador
  // de temporada sai do título (o seletor de temporada logo abaixo já diz "qual
  // temporada"); `tituloBaseDeTemporada` cobre inclusive o número solto no fim
  // ("... desu 2") que a AniList usa. Franquia de 1 temporada mantém o título
  // cru.
  const tituloExibicao =
    anime?.temporadas && anime.temporadas.length > 1
      ? tituloBaseDeTemporada(anime.titulo, anime.numero_temporada)
      : anime?.titulo;
  // 2ª linha do hero: título em inglês da AniList (`Anime.titulo_ingles`),
  // mesmo par título/subtítulo do carrossel da Home. Recebe o mesmo corte de
  // marcador de temporada que o primário quando a franquia tem seletor; só
  // aparece se existir E divergir do que já está no H1.
  const tituloInglesAjustado =
    anime?.titulo_ingles && anime?.temporadas && anime.temporadas.length > 1
      ? tituloBaseDeTemporada(anime.titulo_ingles, anime.numero_temporada)
      : (anime?.titulo_ingles ?? null);
  const tituloSecundario =
    tituloInglesAjustado && tituloInglesAjustado !== tituloExibicao
      ? tituloInglesAjustado
      : null;
  const generosTraduzidos = (anime?.generos ?? []).slice(0, 3).map((g) => traduzirGenero(g));
  const avisoProximaTemporada = textoDeProximaTemporada(anime?.proxima_temporada);
  const fatos = [
    anime?.ano != null ? { rotulo: 'Ano', valor: String(anime.ano) } : null,
    linhas.length > 0 ? { rotulo: 'Episódios', valor: String(linhas.length) } : null,
    nomeDaFonte(remotos.dados?.dominio)
      ? { rotulo: 'Fonte', valor: nomeDaFonte(remotos.dados.dominio) }
      : null,
    { rotulo: 'Versão', valor: ROTULO_VERSAO[versaoAtiva] ?? versaoAtiva },
  ].filter(Boolean);

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

  // Botão "Marcar como assistido" da barra de controles — marca em lote todo
  // episódio LOCAL do anime (qualquer fonte/versão, não só a ativa) que ainda
  // não tem `assistido_em`, E cria (sem baixar nada) um episódio pra cada
  // número que a fonte ativa lista e o usuário nunca capturou — pedido
  // explícito do usuário: o botão marca TODO episódio disponível, não só os
  // já baixados (`api/servicos/jobs.py::marcar_todos_assistidos`). Sempre
  // disponível (nunca desabilitado por não haver nada pra marcar — só
  // enquanto a chamada está em voo, ver o botão abaixo). Sem diálogo de
  // confirmação: ao contrário de "Remover do catálogo", marcar como assistido
  // não apaga nada e não tem efeito colateral em disco.
  const [marcandoTodosAssistidos, setMarcandoTodosAssistidos] = useState(false);
  const [erroMarcarAssistidos, setErroMarcarAssistidos] = useState(null);

  const aoMarcarTodosAssistidos = useCallback(async () => {
    setMarcandoTodosAssistidos(true);
    setErroMarcarAssistidos(null);
    try {
      // Sem `episodios.recarregar()` explícito no sucesso: `marcarTodosAssistidos`
      // já invalida a chave 'episodios' (invalidacao.js) assim que resolve.
      await marcarTodosAssistidos(animeId, versaoPedida);
    } catch (erroCapturado) {
      // Mesmo segundo passo de `capturar` acima: resolve a fonte remota pra
      // criar os episódios faltantes, então pode bater nos mesmos erros de
      // fonte (o `UPDATE` dos já capturados já rodou nesses casos — só o
      // passo de criar os que faltam falhou). Aqui o `recarregar()` segue
      // manual: a Promise rejeitou, então `invalidar()` (dentro de
      // `marcarTodosAssistidos`) nunca rodou, mas o UPDATE parcial já foi
      // commitado no servidor.
      if (erroCapturado instanceof ErroDeApi && erroCapturado.detail?.motivo === 'fonte_ambigua') {
        setFonteAmbigua({ ...erroCapturado.detail, numero: null });
      } else if (
        erroCapturado instanceof ErroDeApi &&
        erroCapturado.detail?.motivo === 'versao_indisponivel'
      ) {
        setErroMarcarAssistidos(
          `A versão ${erroCapturado.detail.versao} não está disponível nesta fonte — tente trocar de fonte ou de versão.`
        );
      } else {
        console.error('falha ao marcar episódios como assistidos', erroCapturado);
        setErroMarcarAssistidos('Não foi possível marcar os episódios como assistidos — tente novamente.');
      }
      episodios.recarregar();
    } finally {
      setMarcandoTodosAssistidos(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [animeId, versaoPedida, episodios.recarregar]);

  // Remove a franquia INTEIRA: um DELETE por temporada (`anime.temporadas`,
  // já inclui a própria) — mesmo comportamento de `Galeria.jsx::
  // confirmarRemocao`, pedido explícito do usuário (2026-09-23) pra não
  // deixar temporadas irmãs órfãs no catálogo quando a remoção parte da
  // página de UMA temporada específica. Falha no meio (ex. temporada com
  // captura em andamento) para o laço e deixa as já removidas removidas.
  const confirmarRemocao = useCallback(async () => {
    setRemovendo(true);
    setErroRemocao(null);
    const ids = anime?.temporadas?.length ? anime.temporadas.map((t) => t.id) : [animeId];
    try {
      for (const id of ids) {
        await removerAnime(id);
      }
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
  }, [anime, animeId, navigate]);

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
      {/* Sem `termoBusca`/`aoMudarBusca`: esta página não tem uma lista pra
          filtrar, então a caixa de busca nem renderiza (ver
          `components/BarraDeNavegacao.jsx`). `transparente`: sem fundo no topo
          (deixa a arte do hero aparecer sob a navbar), escurece ao rolar.
          `statusCapturaIlha`/`capturaProntaIlha`/`erroCapturaIlha`: ilha
          dinâmica mostra o status ao vivo de captura (ou "pronto"/erro por
          alguns segundos) — GLOBAL (qualquer anime, não só este), mesmo hook
          de Galeria.jsx (hooks/useStatusDeCapturaIlha.js). Prioridade de qual
          mensagem a cápsula mostra quando mais de uma está ativa: ver
          comentário de `mensagemIlha` em BarraDeNavegacao.jsx. */}
      <BarraDeNavegacao
        transparente
        statusCapturaIlha={statusCapturaIlha}
        aoClicarStatusCapturaIlha={aoClicarStatusCapturaIlha}
        capturaProntaIlha={capturaProntaIlha}
        aoClicarCapturaProntaIlha={aoClicarCapturaProntaIlha}
        erroCapturaIlha={erroCapturaIlha}
        aoClicarErroCapturaIlha={aoClicarErroCapturaIlha}
      />
      {/* `bg-black`: mesmo preto sólido de Galeria/Início (pedido explícito do
          usuário — antes esta página ficava em `#17171b`, cor histórica do
          Disney+, porque a grade de episódios em modo grade tem sombra
          própria no pôster que "precisava" do cinza pra aparecer; a sombra
          continua lá, só deixou de ditar o fundo da página). É a MESMA cor em
          que o gradiente do hero (`gradienteHero('#000')` abaixo) se dissolve
          sem emenda — mudar um sem o outro reabre a costura visível que
          motivou trocar `GRADIENTE_HERO`/`GRADIENTE_HERO_SEM_BANNER` de
          constante fixa pra função parametrizada por cor (ver
          inicio/CarrosselDestaques.jsx), hoje chamada com o MESMO `'#000'` nos
          dois lugares. Sem `px` no `<main>` (mesma decisão de
          paginas/Galeria.jsx): o hero é full-bleed e o resto do conteúdo
          repõe o gutter lateral com `paddingInline: PADDING_TITULO`
          (`calc(3.7% + 10px)`, ./inicio/tamanhoDeCard.js) — o MESMO gutter
          percentual da Home e do Meu Catálogo, pra o texto do hero e os cards
          de episódio alinharem com as fileiras/grades do resto do app em
          qualquer viewport. */}
      <main className="min-h-screen bg-black pb-16 pt-24">
        {/* Hero full-bleed estilo AnimeFire (https://animefire.io/anime/…) —
            é o cartão de visita da página: a arte horizontal do anime cobre
            100% da largura. Bloco de conteúdo (pills → título → sinopse →
            fatos, um bloco só — pedido explícito do usuário pra juntar o que
            antes eram dois blocos separados) ancorado embaixo-à-esquerda
            sobre a arte. Sinopse com `line-clamp-3` (via `BlocoConteudoHero`)
            de propósito: o bloco vive DENTRO deste `<header>` de altura fixa
            (`h-svh`, `overflow-hidden`) — sem limitar a sinopse, uma sinopse
            longa estouraria a altura reservada pelo `pb-*` abaixo e ou
            cobriria a grade que espia sob o gradiente, ou seria cortada pelo
            `overflow-hidden` de um jeito imprevisível. Com o clamp, a altura
            do bloco tem um teto conhecido, e o `pb-*` reservado (abaixo) é
            confiável pra QUALQUER anime — sem ele, um `-mb-*` fixo de peek
            teria que crescer até valores gigantes e instáveis por anime
            (tipo `-mb-120`) pra sobrar espaço pra grade espiar. O seletor de
            temporada mora na barra de ações abaixo do hero (ao lado de
            "Trocar fonte"), não aqui. Sem pôster e sem layout de duas
            colunas: o "capa de um lado / texto do outro" do Disney+ saiu.
            Altura `h-svh min-h-[480px]` — MESMA geometria do slide do
            carrossel (inicio/CarrosselDestaques.jsx), pedido explícito do
            usuário (antes era `min-h-[76svh]`, próprio desta página). Sem
            fallback "sem banner" (pedido explícito): anime catalogado sem
            `banner_path` (raro — Kitsu, ou AniList sem `bannerImage`) fica só
            com o gradiente sobre `bg-surface`, sem textura de capa borrada —
            o carrossel da Home ainda trata esse caso (`semBanner`) porque lá
            é comum (feed inteiro, não um anime catalogado específico). Full-
            bleed de graça (o `<main>` não tem mais `px`); `-mt-24` cancela o
            `pt-24` do <main> pra a arte subir por baixo da navbar
            fixa/transparente. `-mb-32`: MESMO peek do carrossel da Home
            (paginas/Inicio.jsx) — com o hero ocupando a viewport inteira
            (`h-svh`), a margem negativa puxa a barra de ações + topo da grade
            de episódios pra dentro do fade da base do hero, deixando-os
            "espiar" sob o gradiente em vez de começar só depois da dobra.
            Pré-requisito pro conteúdo puxado não sumir atrás da arte/gradiente
            (`absolute`, pintam depois): o wrapper logo abaixo tem
            `relative z-10` — mesmo mecanismo do bloco de fileiras da Home.
            `flex flex-col justify-end`: o bloco de conteúdo vive no rodapé e
            o <header> cresce (não corta) se a sinopse empurrar — dentro do
            teto que o clamp já garante. */}
        <header className="relative -mt-24 -mb-32 flex h-svh min-h-[480px] flex-col justify-end overflow-hidden bg-surface">
          {anime?.banner_path && (
            <img
              // `imagemEmAltaResolucao` sobe o backdrop do TMDB de w1280 pra
              // `original` — mesma função e mesmo motivo do hero do carrossel
              // (w1280 sob `object-cover` num hero >=1920px é upscale visível);
              // URL de outra origem passa intacta. `object-top`: a essa altura
              // o `object-cover` centralizado cortaria a cabeça dos
              // personagens no banner.
              src={imagemEmAltaResolucao(anime.banner_path)}
              alt=""
              className="absolute inset-0 h-full w-full object-cover object-top"
            />
          )}
          {/* Gradiente empilhado — o mesmo `::before` do carrossel
              (`gradienteHero`, fonte única em inicio/CarrosselDestaques.jsx):
              3 camadas na cor EXATA do fundo da página, dissolvendo o pé do
              hero no `bg-black` do <main> sem emenda — `'#000'`, o MESMO valor
              que a Home passa à mesma função. Stops em 60/55/70% (pedido
              explícito do usuário, aplicado na função compartilhada — o
              carrossel da Home segue o mesmo design agora, não uma variante
              local). Inline no `style` porque o parser de multi-gradiente
              arbitrário do Tailwind v4 não é confiável. */}
          <div
            className="pointer-events-none absolute inset-0"
            style={{ background: gradienteHero('#000') }}
          />

          {/* Bloco de conteúdo — esqueleto compartilhado com o carrossel da
              Home (inicio/BlocoConteudoHero.jsx: pills → título/subtítulo →
              sinopse → metaExtra). Usa os slots `sinopse` (clamp embutido no
              componente) e `metaExtra` (fatos rotulados — "Ano"/"Episódios"/
              "Fonte"/"Versão" — em vez do `meta` de linha única com "•" que o
              esqueleto também aceita; o rótulo por fato é o formato já
              adotado no resto da página). `relative` pra pintar acima da arte
              e do gradiente (ambos `absolute` e antes no DOM). `pt-24`
              reserva respiro no topo pro gradiente. `pb-10 sm:pb-14
              lg:pb-[18vh] xl:pb-[20vh]`: viewport-relative de propósito (não
              rem fixo) — cresce com a altura da tela, então acompanha o teto
              de altura do bloco (título+subtítulo+sinopse em 3 linhas+fatos)
              em vez de precisar de um valor mágico por breakpoint. Precisa
              ficar ACIMA de 8rem (o `-mb-32` do <header>, peek da barra de
              ações/grade, ver acima) senão o texto fica coberto pelo
              conteúdo puxado pra cima (bug antigo, já visto com `pb-8`). O
              aviso de estreia da próxima temporada (`avisoProximaTemporada`)
              SAIU daqui — mora ao lado do seletor de temporada, na barra de
              controles abaixo (pedido do usuário, 2026-09-21). */}
          <BlocoConteudoHero
            className="relative pb-10 pt-24 sm:pb-14 lg:pb-[18vh] xl:pb-[20vh]"
            // Pills de gênero — ACIMA do título, mesma posição das pills
            // "#N em alta"/"Anime no Catálogo" do carrossel. `CLASSE_PILL_HERO`
            // é a fonte única do estilo (`bg-white/10 backdrop-blur-sm
            // text-white`), a mesma linguagem de pill do hero da Home.
            pills={generosTraduzidos.map((genero) => (
              <span key={genero} className={CLASSE_PILL_HERO}>
                {genero}
              </span>
            ))}
            // `<h1>` espelha o `<h3>` do carrossel: `text-2xl→sm:4xl→lg:5xl`,
            // `font-extrabold`, `line-clamp-2`, `lg:leading-[1.2]` — só que
            // focável (`ref`/`tabIndex=-1`, foco ao montar/trocar de anime).
            titulo={
              <h1
                ref={focoTitulo}
                tabIndex={-1}
                className="mb-1 line-clamp-2 max-w-4xl text-2xl font-extrabold text-white outline-none sm:text-4xl lg:text-5xl lg:leading-[1.2]"
              >
                {tituloExibicao ?? `Anime #${animeId}`}
              </h1>
            }
            // Espelha a linha alternativa do carrossel (`line-clamp-1 text-lg
            // font-bold`).
            tituloSecundario={
              tituloSecundario && (
                <p className="line-clamp-1 max-w-4xl text-lg font-bold text-ink-muted sm:text-xl xl:text-2xl">
                  {tituloSecundario}
                </p>
              )
            }
            // Sinopse com o `line-clamp-3` embutido do esqueleto — teto de
            // altura que faz o `pb-*` acima ser confiável (ver comentário do
            // <header>). `!animeNaoEncontrado` some com ela quando o anime foi
            // removido do catálogo.
            sinopse={!animeNaoEncontrado ? anime?.sinopse : null}
            // O botão só aparece se o `line-clamp` cortou texto (decisão do
            // `BlocoConteudoHero`); abre a sinopse inteira em modo foco.
            acaoSinopse={
              <button
                type="button"
                onClick={() => setSinopseEmFoco(true)}
                aria-haspopup="dialog"
                className="-mt-0.5 inline-flex min-h-9 items-center text-sm font-bold text-neon outline-none transition-colors hover:text-white focus-visible:underline"
              >
                Ler sinopse completa
              </button>
            }
            metaExtra={
              fatos.length > 0 &&
              !animeNaoEncontrado && (
                <div className="flex flex-wrap gap-6">
                  {fatos.map((fato) => (
                    <div key={fato.rotulo} className="flex flex-col gap-0.5">
                      <span className="text-[11px] font-bold uppercase tracking-wide text-ink-muted">
                        {fato.rotulo}
                      </span>
                      <span className="text-sm font-bold text-white sm:text-base">{fato.valor}</span>
                    </div>
                  ))}
                </div>
              )
            }
          />
        </header>

        {/* Conteúdo abaixo do hero (erros, avisos de carregamento, barra de
            controles, grade/lista de episódios). O gutter lateral vem daqui —
            `paddingInline: PADDING_TITULO` (o mesmo do bloco de conteúdo do
            hero e das grades da Home/Meu Catálogo), não de um `px` no <main>,
            que sangraria o hero full-bleed. `relative z-10`: promove este
            bloco pra cima da arte/gradiente do hero (`absolute`, `-mb-32`
            acima) — sem isso o topo dele (barra de ações, puxada pro peek)
            ficaria atrás do hero em vez de sobre o fade, mesmo mecanismo do
            bloco de fileiras da Home (paginas/Inicio.jsx). Os diálogos ficam
            FORA deste wrapper (são overlays fixos, não conteúdo de coluna). */}
        <div className="relative z-10" style={{ paddingInline: PADDING_TITULO }}>
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
        {erroMarcarAssistidos && (
          <p role="alert" className="mb-4 text-sm text-red-400">
            {erroMarcarAssistidos}
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
            {/* Seletor de temporada (Fase 5) — PRIMEIRO controle da barra, à
                esquerda de "Trocar fonte". `anime.temporadas` já vem ordenada
                por número e inclui a atual; trocar de temporada é NAVEGAÇÃO de
                rota (`/anime/:outroId`), a página re-chaveia em `animeId` via
                `useRecurso` e a URL fica compartilhável por temporada. `[]`
                (anime sem irmã de franquia) faz o componente cair pro rótulo
                simples "Temporada N" (sem dropdown) — `numeroTemporadaAtual`/
                `tituloAtual` alimentam só esse caso. Filme/OVA/ONA/especial da
                franquia entra na MESMA lista (`anime.temporadas`) — se agrupa
                no anime original, o componente só acrescenta um selo de
                formato. */}
            {anime?.temporadas && (
              <SeletorDeTemporada
                temporadas={anime.temporadas}
                animeIdAtual={animeId}
                numeroTemporadaAtual={anime.numero_temporada}
                tituloAtual={anime.titulo}
              />
            )}
            {/* Aviso de estreia da próxima temporada da franquia (quando já
                tem data) — ao lado do seletor (pedido do usuário,
                2026-09-21; morava no hero, junto do título). A irmã
                `nao_lancado` fica FORA do seletor, então este é o único
                lugar que a menciona. */}
            {avisoProximaTemporada && (
              <span className="text-[18px] font-semibold text-neon">{avisoProximaTemporada}</span>
            )}
            {/* A fonte ativa (`remotos.dados.dominio`) e a versão
                ("Legendado"/"Dublado") já aparecem na linha meta do hero
                (`ano • N episódios • fonte • versão`) — não repetir aqui. */}
            {anime?.versoes_disponiveis &&
              versaoAtiva !== 'desconhecida' &&
              !anime.versoes_disponiveis.includes(versaoAtiva) && (
              // Hint de cache, não bloqueante — `versoes_disponiveis` reflete
              // o que já está mapeado em `FonteAnime`, não um live-probe. O
              // 409 `versao_indisponivel` (ver `capturar`) é o backstop real
              // quando a versão genuinamente não existe nesta fonte.
              <span className="text-amber-400">pode não estar disponível nesta fonte ainda</span>
            )}
            <div className="ml-auto flex items-center gap-2">
              <div
                className="flex items-center gap-1"
                role="group"
                aria-label="Modo de exibição dos episódios"
              >
                {[
                  { modo: 'grade', rotulo: 'Exibir em grade', Icone: IconeGrade },
                  { modo: 'lista', rotulo: 'Exibir em lista', Icone: IconeLista },
                ].map(({ modo, rotulo, Icone }) => (
                  <button
                    key={modo}
                    type="button"
                    onClick={() => mudarModoVisualizacao(modo)}
                    aria-pressed={modoVisualizacao === modo}
                    aria-label={rotulo}
                    className={`flex h-8 w-8 items-center justify-center rounded-md border-2 outline-none transition-colors cursor-pointer ${
                      modoVisualizacao === modo
                        ? 'border-neon text-white'
                        : 'border-border-chrome text-ink-muted hover:border-neon hover:text-white'
                    }`}
                  >
                    <Icone />
                  </button>
                ))}
              </div>
              {/* "Trocar fonte"/"Marcar como assistido"/"Remover do
                  catálogo" — saíram de botões soltos pra dentro deste menu
                  (`MenuDeAcoesDoAnime`), gatilho ao lado do alternador
                  grade/lista (pedido explícito do usuário, mesma geometria
                  `h-8 w-8`). */}
              <MenuDeAcoesDoAnime
                aoTrocarFonte={() => setTrocandoFonte(true)}
                aoMarcarAssistidos={aoMarcarTodosAssistidos}
                marcandoAssistidos={marcandoTodosAssistidos}
                tudoAssistido={tudoAssistido}
                aoRemover={() => setConfirmandoRemocao(true)}
              />
            </div>
          </div>
        )}

        <div
          className={
            modoVisualizacao === 'grade'
              ? // `gap-x-4 gap-y-6` (era `gap-x-4 gap-y-8`, depois `gap-x-3
                // gap-y-5` — usuário pediu um meio-termo): mesma contagem de
                // colunas (4 no desktop). Mais notável depois que o card de
                // episódio perdeu a sombra que preenchia parte desse espaço
                // (ver comentário de `estilo` em components/LinhaDeEpisodio.jsx).
                // `isolate`: o glow do hover (`-z-10`, BrilhoDaCapa) fica preso a este
                // contexto — sem ele iria parar atrás do fundo de um ancestral.
                'isolate grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-4'
              : 'flex flex-col gap-2'
          }
        >
          {linhas.map((linha) => {
            const {
              chave,
              numero,
              rotulo,
              colisao,
              episodio,
              episodioDescartado,
              thumb,
              titulo,
              sinopse,
            } = linha;
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
                titulo={titulo}
                sinopse={sinopse}
                // `remotos.dados?.dominio` já é o mesmo valor mostrado na linha
                // meta do hero (`ano • N episódios • fonte • versão`) — reusado
                // direto aqui em vez de expor pelo `useMemo` de `linhas`, que não precisa
                // dele pra montar as linhas em si (só `LinhaDeEpisodio` usa,
                // pra anotar a origem de um `episodioDescartado`).
                dominioAtivo={remotos.dados?.dominio ?? null}
                versaoAtiva={versaoAtiva}
                modo={modoVisualizacao}
                job={job}
                capturando={numero != null && numeroCapturando === numero}
                aoCapturar={capturar}
                animeId={animeId}
                animeTitulo={anime?.titulo}
                // Ao contrário de `tituloExibicao` acima (só corta o marcador
                // do H1 com 2+ temporadas catalogadas — o seletor já diz "qual
                // temporada" nesse caso): o player não tem seletor, então
                // mostra sempre que o número é conhecido, mesmo em franquia de
                // temporada única (a pedido do usuário — consistência do
                // cabeçalho independe de quantas temporadas o catálogo já tem).
                numeroTemporada={anime?.numero_temporada ?? null}
              />
            );
          })}
        </div>

        {linhas.length === 0 && !episodios.carregando && !remotos.carregando && (
          <p className="text-sm text-ink-muted">Nenhum episódio encontrado.</p>
        )}
        </div>

        {/* "Relacionados", FORA do wrapper `paddingInline: PADDING_TITULO`
            acima — mesma razão de `paginas/Inicio.jsx`: `FileiraDeCards` já
            traz seu próprio gutter (`CLASSE_GUTTER`/`PADDING_TITULO` em
            `inicio/tamanhoDeCard.js`, o MESMO valor), nesting dobraria o
            respiro lateral. `mt-14` própria (a fileira não tem margem
            externa) — mesmo respiro entre blocos que `space-y-14` dá na
            Home. `erroRelacionado` (falha ao materializar um card, não a
            busca em si — essa já degrada pra `[]` sem erro no backend) sai
            DENTRO do gutter da fileira, não do wrapper acima. */}
        <div className="relative z-10 mt-14">
          <FileiraDeCards
            titulo="Animes Como Este"
            itens={relacionados.dados ?? []}
            tamanho="pequeno"
            comSombra={false}
            chaveDoItem={(item) => item.anilist_id ?? item.titulo_romaji}
            renderItem={(item) => (
              <AnimeCard
                anime={item}
                aoAtivar={() => materializarRelacionado(item)}
                desabilitado={relacionadoEmVoo != null && relacionadoEmVoo === item.anilist_id}
                indicarCatalogado
              />
            )}
          />
          {erroRelacionado && (
            <p role="alert" style={{ paddingInline: PADDING_TITULO }} className="text-sm text-red-400">
              {erroRelacionado}
            </p>
          )}
        </div>

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

        <SinopseEmFoco
          aberta={sinopseEmFoco}
          titulo={tituloExibicao ?? anime?.titulo ?? ''}
          tituloSecundario={tituloSecundario}
          sinopse={anime?.sinopse}
          aoFechar={() => setSinopseEmFoco(false)}
        />

        <DialogoDeConfirmacao
          aberto={confirmandoRemocao}
          titulo="Remover do catálogo"
          mensagem={
            (anime?.temporadas?.length ?? 1) > 1
              ? `Remover "${tituloExibicao ?? `Anime #${animeId}`}" e suas ${anime.temporadas.length} temporadas do catálogo? Todos os episódios e capturas da franquia serão apagados.`
              : `Remover "${anime?.titulo ?? `Anime #${animeId}`}" do catálogo? Episódios e capturas associados serão apagados.`
          }
          erro={erroRemocao}
          aoConfirmar={confirmarRemocao}
          aoFechar={fecharDialogoRemocao}
          confirmando={removendo}
        />
      </main>
    </>
  );
}
