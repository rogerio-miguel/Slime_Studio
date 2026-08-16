import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ErroDeApi } from '../api/cliente.js';
import {
  confirmarFonte,
  criarJobSite,
  listarAnimes,
  listarEpisodios,
  listarEpisodiosRemotos,
} from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import DialogoDeFonteAmbigua from '../components/DialogoDeFonteAmbigua.jsx';
import LinhaDeEpisodio from '../components/LinhaDeEpisodio.jsx';
import { useFocoAoMontar } from '../hooks/useFocoAoMontar.js';

// Rota "/anime/:id" — grade prontos/não capturados. Clique num episódio não
// capturado dispara a resolução automática de fonte direto (sem formulário
// de URL, ESPECIFICACAO.md §4): `POST /api/admin/jobs` (modo "site") resolve
// e cria o job no mesmo request; se o site tiver mais de um resultado
// possível, `DialogoDeFonteAmbigua` resolve inline e a captura é reenviada.
export default function PaginaDoAnime({ jobsPorEpisodio }) {
  const { id } = useParams();
  const animeId = Number(id);
  const focoTitulo = useFocoAoMontar(id);

  // Sem `GET /api/animes/{id}`: o contrato confirmado só lista todos os
  // animes de uma vez — busca o título aqui na lista já pequena (uso
  // pessoal, não catálogo público em escala).
  const { dados: animes } = useRecurso(listarAnimes, []);
  const anime = animes?.find((item) => item.id === animeId);

  const episodios = useRecurso(() => listarEpisodios(animeId), [animeId]);
  const remotos = useRecurso(() => listarEpisodiosRemotos(animeId), [animeId]);

  const [numeroCapturando, setNumeroCapturando] = useState(null);
  const [erroCaptura, setErroCaptura] = useState(null);
  const [fonteAmbigua, setFonteAmbigua] = useState(null); // { dominio, candidatos, numero }

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

  const episodiosPorNumero = useMemo(() => {
    const mapa = new Map();
    (episodios.dados ?? []).forEach((episodio) => mapa.set(episodio.numero, episodio));
    return mapa;
  }, [episodios.dados]);

  const numeros = useMemo(() => {
    const conjunto = new Set();
    (episodios.dados ?? []).forEach((episodio) => conjunto.add(episodio.numero));
    (remotos.dados ?? []).forEach((remoto) => conjunto.add(remoto.numero));
    return [...conjunto].sort((a, b) => a - b);
  }, [episodios.dados, remotos.dados]);

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
        await criarJobSite({ animeId, numero, tipo: 'regular', versao: 'legendado' });
        episodios.recarregar();
      } catch (erroCapturado) {
        if (erroCapturado instanceof ErroDeApi && erroCapturado.detail?.motivo === 'fonte_ambigua') {
          setFonteAmbigua({ ...erroCapturado.detail, numero });
        } else if (
          erroCapturado instanceof ErroDeApi &&
          erroCapturado.detail?.motivo === 'episodio_ja_existe'
        ) {
          episodios.recarregar();
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
    [animeId, episodios.recarregar]
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

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <Link
        to="/animes"
        className="mb-4 inline-block text-sm text-ink-muted underline outline-none focus-visible:ring-2 focus-visible:ring-neon"
      >
        ← catálogo
      </Link>
      <h1
        ref={focoTitulo}
        tabIndex={-1}
        className="mb-6 text-2xl font-semibold text-white outline-none"
      >
        {anime?.titulo ?? `Anime #${animeId}`}
        {anime?.ano ? ` (${anime.ano})` : ''}
      </h1>

      {remotos.erro && (
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

      <div className="flex flex-col gap-2">
        {numeros.map((numero) => {
          const episodio = episodiosPorNumero.get(numero) ?? null;
          const job = episodio ? jobsPorEpisodio.get(episodio.id) : null;
          return (
            <LinhaDeEpisodio
              key={numero}
              numero={numero}
              episodio={episodio}
              job={job}
              capturando={numeroCapturando === numero}
              aoCapturar={capturar}
              animeId={animeId}
              animeTitulo={anime?.titulo}
            />
          );
        })}
      </div>

      {numeros.length === 0 && !episodios.carregando && !remotos.carregando && (
        <p className="text-sm text-ink-muted">Nenhum episódio encontrado.</p>
      )}

      <DialogoDeFonteAmbigua
        aberto={fonteAmbigua != null}
        dominio={fonteAmbigua?.dominio}
        candidatos={fonteAmbigua?.candidatos}
        aoEscolher={aoConfirmarFonte}
        aoFechar={() => setFonteAmbigua(null)}
      />
    </main>
  );
}
