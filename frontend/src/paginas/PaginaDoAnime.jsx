import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import SeletorDeTemporada from '../components/SeletorDeTemporada.jsx';
import { useFocoAoMontar } from '../hooks/useFocoAoMontar.js';
import {
  GRADIENTE_HERO,
  GRADIENTE_HERO_SEM_BANNER,
  imagemEmAltaResolucao,
  CLASSE_PILL_HERO,
} from '../inicio/CarrosselDestaques.jsx';
import { tituloBaseDeTemporada } from '../inicio/franquia.js';
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

// Instância única de módulo (recriar `Intl.*` por render é caro) — mesmo padrão
// de `inicio/CartaoDeEstreia.jsx`.
const fmtDataEstreia = new Intl.DateTimeFormat('pt-BR', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

// "2ª temporada estreia em 4 de outubro de 2026" a partir de
// `anime.proxima_temporada` (`AnimeDetalheSaida`) — a temporada seguinte da
// franquia que ainda não saiu. Com `estreia_em` (ISO `YYYY-MM-DD`, parse com
// `T00:00:00` pra cair na meia-noite LOCAL, mesmo motivo de `CartaoDeEstreia.jsx`)
// mostra a data completa; sem ela, degrada pro ano (`proxima.ano`) — "estreia em
// 2026" —, igual ao passo 4 de `CartaoDeEstreia.textoDeEstreia`. `null` = nada a
// anunciar (o hero não renderiza a linha).
function textoDeProximaTemporada(proxima) {
  if (!proxima) return null;
  const ordinal =
    proxima.numero_temporada != null ? `${proxima.numero_temporada}ª temporada` : proxima.titulo;
  if (proxima.estreia_em) {
    const data = new Date(`${proxima.estreia_em}T00:00:00`);
    if (!Number.isNaN(data.getTime())) {
      return `${ordinal} estreia em ${fmtDataEstreia.format(data)}`;
    }
  }
  if (proxima.ano) return `${ordinal} estreia em ${proxima.ano}`;
  return null;
}

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

// Ícones inline do alternador lista/grade — sem lib de ícones (Escada de
// Minimalismo, CLAUDE.md §4; mesmo padrão de `player/Icones.jsx`).
// `aria-hidden`: o texto acessível vem do `aria-label` de cada <button>.
const propsIconeVisualizacao = {
  viewBox: '0 0 24 24',
  width: 16,
  height: 16,
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': 'true',
  focusable: 'false',
};

function IconeLista() {
  return (
    <svg {...propsIconeVisualizacao}>
      <line x1="8" y1="6" x2="21" y2="6" />
      <line x1="8" y1="12" x2="21" y2="12" />
      <line x1="8" y1="18" x2="21" y2="18" />
      <line x1="3" y1="6" x2="3.01" y2="6" />
      <line x1="3" y1="12" x2="3.01" y2="12" />
      <line x1="3" y1="18" x2="3.01" y2="18" />
    </svg>
  );
}

function IconeGrade() {
  return (
    <svg {...propsIconeVisualizacao}>
      <rect x="3" y="3" width="7" height="7" />
      <rect x="14" y="3" width="7" height="7" />
      <rect x="3" y="14" width="7" height="7" />
      <rect x="14" y="14" width="7" height="7" />
    </svg>
  );
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
    carregando: animeCarregando,
    erro: erroAnime,
    recarregar: recarregarAnime,
  } = useRecurso(() => obterAnime(animeId), [animeId]);
  const animeNaoEncontrado = erroAnime instanceof ErroDeApi && erroAnime.status === 404;

  const episodios = useRecurso(() => listarEpisodios(animeId), [animeId]);

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

  // Dados derivados do bloco de conteúdo do hero (estilo AnimeFire, coluna
  // única). `meta` é a linha stacked "ano • N episódios • versão" logo abaixo
  // do título; os gêneros saem dela e viram pills próprias (`generosTraduzidos`,
  // até 3, traduzidos por `traduzirGenero` — mesmo recorte do card do
  // carrossel da Home). Declarado aqui (não junto de `anime`) porque a
  // contagem depende de `linhas`, que já une episódios locais + remotos.
  // `AnimeDetalheSaida` (backend/api/esquemas.py) não expõe título
  // alternativo/romaji nem nota — por isso o hero não tem linha de subtítulo
  // nem rating, ao contrário do AnimeFire. Rótulo da versão via `ROTULO_VERSAO`
  // (mesmo mapa usado por LinhaDeEpisodio.jsx pra exibir a versão).
  // Título do H1 — quando a franquia tem 2+ temporadas catalogadas, o marcador
  // de temporada sai do título (o seletor de temporada logo abaixo já diz "qual
  // temporada"); `tituloBaseDeTemporada` cobre inclusive o número solto no fim
  // ("... desu 2") que a AniList usa. Franquia de 1 temporada mantém o título
  // cru.
  const tituloExibicao =
    anime?.temporadas && anime.temporadas.length > 1
      ? tituloBaseDeTemporada(anime.titulo, anime.numero_temporada)
      : anime?.titulo;
  const generosTraduzidos = (anime?.generos ?? []).slice(0, 3).map((g) => traduzirGenero(g));
  const avisoProximaTemporada = textoDeProximaTemporada(anime?.proxima_temporada);
  const meta = [
    anime?.ano,
    linhas.length > 0
      ? `${linhas.length} episódio${linhas.length === 1 ? '' : 's'}`
      : null,
    ROTULO_VERSAO[versaoAtiva] ?? versaoAtiva,
  ]
    .filter(Boolean)
    .join(' • ');

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
          `components/BarraDeNavegacao.jsx`). `transparente`: sem fundo no topo
          (deixa a arte do hero aparecer sob a navbar), escurece ao rolar. */}
      <BarraDeNavegacao fase="revelado" transparente />
      {/* `bg-[#17171b]` + `min-h-screen`: mesmo fundo do `<main>` de
          paginas/Galeria.jsx (fonte da verdade — cor do `body` do Disney+) e a
          MESMA cor em que o gradiente do hero (`GRADIENTE_HERO`) se dissolve
          sem emenda. É ele que faz a drop shadow dos cards da grade de
          episódios aparecer; sobre um preto mais fechado a sombra 69% preta
          some. Sem `px` no `<main>` (mesma decisão de paginas/Galeria.jsx): o
          hero é full-bleed e o resto do conteúdo repõe o gutter lateral com
          `paddingInline: PADDING_TITULO` (`calc(3.7% + 10px)`, ./inicio/
          tamanhoDeCard.js) — o MESMO gutter percentual da Home e do Meu
          Catálogo, pra o texto do hero e os cards de episódio alinharem com as
          fileiras/grades do resto do app em qualquer viewport. */}
      <main className="min-h-screen bg-[#17171b] pb-16 pt-24">
        {/* Hero full-bleed estilo AnimeFire (https://animefire.io/anime/…) —
            é o cartão de visita da página: a arte horizontal do anime cobre
            100% da largura, e o bloco de conteúdo fica empilhado numa ÚNICA
            coluna (título → linha meta → pills de gênero → sinopse) ancorada
            embaixo-à-esquerda sobre a arte. Sem pôster e sem layout de duas
            colunas: o "capa de um lado / texto do outro" do Disney+ saiu.
            Altura ~76svh (NÃO a viewport inteira): a barra de controles e o
            topo da primeira fileira de cards de episódio já espiam acima da
            dobra. Full-bleed de graça (o `<main>` não tem mais `px`); `-mt-24`
            cancela o `pt-24` do <main> pra a arte subir por baixo da navbar
            fixa/transparente. `min-h` em `svh` espelha o hero do carrossel
            (inicio/CarrosselDestaques.jsx). `mb-6` curto: a seção de episódios
            encosta logo abaixo. `flex flex-col justify-end`: o bloco de
            conteúdo vive no rodapé e o <header> cresce (não corta) se a
            sinopse empurrar. O fallback "sem banner" espelha o `semBanner` do
            carrossel: a cor dominante da capa (`capa_cor`, `bg-surface` quando
            null — Kitsu ou `color: null` da AniList) vira o fundo, com a
            própria capa borrada/escurecida por cima como textura e o gradiente
            ganhando uma camada extra à esquerda (`GRADIENTE_HERO_SEM_BANNER`)
            pra manter o texto legível. */}
        <header className="relative -mt-24 mb-6 flex min-h-[76svh] flex-col justify-end overflow-hidden">
          {anime?.banner_path ? (
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
          ) : (
            <div
              className="absolute inset-0 bg-surface"
              style={anime?.capa_cor ? { backgroundColor: anime.capa_cor } : undefined}
            >
              {anime?.capa_path && (
                <img
                  src={anime.capa_path}
                  alt=""
                  className="absolute inset-0 h-full w-full scale-125 object-cover object-top opacity-70 blur-lg brightness-[0.5]"
                />
              )}
            </div>
          )}
          {/* Gradiente empilhado — o mesmo `::before` do carrossel
              (`GRADIENTE_HERO` / `GRADIENTE_HERO_SEM_BANNER`, fonte única em
              inicio/CarrosselDestaques.jsx): 3 (ou 4, sem banner) camadas com a
              cor EXATA do fundo da página, dissolvendo o pé e a esquerda do
              hero no `#17171b` do <main> sem emenda. Inline no `style` porque o
              parser de multi-gradiente arbitrário do Tailwind v4 não é
              confiável. */}
          <div
            className="pointer-events-none absolute inset-0"
            style={{ background: anime?.banner_path ? GRADIENTE_HERO : GRADIENTE_HERO_SEM_BANNER }}
          />

          {/* Bloco de conteúdo — coluna única ancorada no rodapé do hero
              (`justify-end` no <header>). `relative` pra pintar acima da arte e
              do gradiente (ambos `absolute` e antes no DOM). `pt-24` reserva
              respiro no topo pro gradiente. `paddingInline: PADDING_TITULO` é o
              MESMO gutter do wrapper do conteúdo abaixo do hero (e da Home/Meu
              Catálogo) — o título alinha exatamente com a borda dos cards de
              episódio. */}
          <div
            style={{ paddingInline: PADDING_TITULO }}
            className="relative flex flex-col items-start gap-4 pb-10 pt-24"
          >
            <h1
              ref={focoTitulo}
              tabIndex={-1}
              className="max-w-4xl text-4xl font-semibold text-white outline-none sm:text-5xl lg:text-6xl"
            >
              {tituloExibicao ?? `Anime #${animeId}`}
            </h1>
            {avisoProximaTemporada && (
              // Aviso de estreia da próxima temporada da franquia (quando já
              // tem data) — logo abaixo do título, antes do seletor. A irmã
              // `nao_lancado` fica FORA do seletor, então este é o único lugar
              // que a menciona. Pill neon translúcida, no idioma de
              // `CLASSE_PILL_HERO`.
              <p className="inline-flex items-center text-sm font-semibold text-neon backdrop-blur-sm">
                {avisoProximaTemporada}
              </p>
            )}
            {/* Seletor de temporada (Fase 5) — `anime.temporadas` é a lista das
                temporadas irmãs da franquia (mesmo `serie_ancora` OU slug do
                título base, já ordenada por número, inclui a atual). Trocar de
                temporada é NAVEGAÇÃO de rota (`/anime/:outroId`): a página
                inteira já re-chaveia em `animeId` via `useRecurso`, e a URL
                fica compartilhável por temporada. Dropdown no idioma do
                AnimeFire; só renderiza com 2+ temporadas catalogadas (guard
                interno do componente também). */}
            {anime?.temporadas && (
              <SeletorDeTemporada temporadas={anime.temporadas} animeIdAtual={animeId} />
            )}
            {meta && <p className="text-sm text-ink-muted sm:text-base">{meta}</p>}
            {generosTraduzidos.length > 0 && (
              // Pills de gênero — reusam `CLASSE_PILL_HERO` (fonte única do
              // carrossel: `bg-white/10 backdrop-blur-sm text-white`), a mesma
              // linguagem de pill do hero da Home.
              <div className="flex flex-wrap gap-2">
                {generosTraduzidos.map((genero) => (
                  <span key={genero} className={CLASSE_PILL_HERO}>
                    {genero}
                  </span>
                ))}
              </div>
            )}
            {anime?.sinopse && (
              // `line-clamp-3`: segura o <header> perto de 76svh mesmo com
              // sinopse longa (ele é `min-h` e cresceria com o texto),
              // preservando o "episódios espiando" acima da dobra.
              <p className="line-clamp-3 max-w-2xl text-sm text-ink-muted sm:text-base">
                {anime.sinopse}
              </p>
            )}
          </div>
        </header>

        {/* Conteúdo abaixo do hero (erros, avisos de carregamento, barra de
            controles, grade/lista de episódios). O gutter lateral vem daqui —
            `paddingInline: PADDING_TITULO` (o mesmo do bloco de conteúdo do
            hero e das grades da Home/Meu Catálogo), não de um `px` no <main>,
            que sangraria o hero full-bleed. Os diálogos ficam FORA deste
            wrapper (são overlays fixos, não conteúdo de coluna). */}
        <div style={{ paddingInline: PADDING_TITULO }}>
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
            {/* A versão ativa ("Legendado"/"Dublado") já aparece na linha meta
                do hero (`ano • N episódios • versão`) — não repetir aqui. */}
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
              className="rounded-md border-2 border-border-chrome px-3 py-1 text-xs text-ink-muted outline-none transition-colors hover:border-neon hover:text-white focus-visible:ring-2 focus-visible:ring-neon"
            >
              Trocar fonte
            </button>
            {/* "Remover do catálogo" — ação destrutiva, mora aqui ao lado de
                "Trocar fonte" (não mais num canto do hero). Mesma geometria de
                pill da barra (`rounded-md border-2 px-3 py-1 text-xs`), só o
                tom vermelho a diferencia. */}
            <button
              type="button"
              onClick={() => setConfirmandoRemocao(true)}
              className="rounded-md border-2 border-red-500/50 px-3 py-1 text-xs text-red-400 outline-none transition-colors hover:border-red-400 hover:text-red-300 focus-visible:ring-2 focus-visible:ring-neon"
            >
              Remover do catálogo
            </button>
            <div
              className="ml-auto flex items-center gap-1"
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
                  className={`rounded-md border-2 p-1.5 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-neon ${
                    modoVisualizacao === modo
                      ? 'border-neon text-white'
                      : 'border-border-chrome text-ink-muted hover:border-neon hover:text-white'
                  }`}
                >
                  <Icone />
                </button>
              ))}
            </div>
          </div>
        )}

        <div
          className={
            modoVisualizacao === 'grade'
              ? 'grid grid-cols-2 gap-x-4 gap-y-8 sm:grid-cols-3 lg:grid-cols-4'
              : 'flex flex-col gap-2'
          }
        >
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
                modo={modoVisualizacao}
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
