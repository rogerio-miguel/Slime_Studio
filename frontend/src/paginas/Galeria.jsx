import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ErroDeApi } from '../api/cliente.js';
import { criarAnime, listarAnimes } from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import AnimeCard from '../components/AnimeCard.jsx';
import { useFocoAoMontar } from '../hooks/useFocoAoMontar.js';
import { useSessao } from '../sessao/SessaoContexto.jsx';

// Rota "/" — catálogo. Cadastro de anime é um formulário mínimo (título +
// ano) direto pra `POST /api/admin/animes`: sem busca-e-confirma no
// AniList/Kitsu (integrations/ ainda não existe, fora de escopo desta
// fase — ver `backend/api/rotas/animes.py`), então este é o único jeito de
// popular o catálogo pela UI.
export default function Galeria() {
  const navigate = useNavigate();
  const { sair } = useSessao();
  const focoTitulo = useFocoAoMontar();
  const { dados: animes, carregando, erro, recarregar } = useRecurso(listarAnimes, []);

  const [tituloNovo, setTituloNovo] = useState('');
  const [anoNovo, setAnoNovo] = useState('');
  const [criando, setCriando] = useState(false);
  const [erroCriacao, setErroCriacao] = useState(null);

  const aoCriarAnime = useCallback(
    async (event) => {
      event.preventDefault();
      if (!tituloNovo.trim() || criando) return;
      setCriando(true);
      setErroCriacao(null);
      try {
        const anime = await criarAnime({
          titulo: tituloNovo.trim(),
          ano: anoNovo ? Number(anoNovo) : undefined,
        });
        setTituloNovo('');
        setAnoNovo('');
        recarregar();
        navigate(`/anime/${anime.id}`);
      } catch (erroCapturado) {
        console.error('falha ao criar anime', erroCapturado);
        if (erroCapturado instanceof ErroDeApi && Array.isArray(erroCapturado.detail)) {
          const referenteAoAno = erroCapturado.detail.some((item) => item.loc?.includes('ano'));
          setErroCriacao(
            referenteAoAno
              ? 'Ano inválido — informe um número inteiro.'
              : 'Dados inválidos — verifique o formulário.'
          );
        } else {
          setErroCriacao('Não foi possível adicionar o anime — tente novamente.');
        }
      } finally {
        setCriando(false);
      }
    },
    [tituloNovo, anoNovo, criando, recarregar, navigate]
  );

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <h1 ref={focoTitulo} tabIndex={-1} className="text-2xl font-semibold text-white outline-none">
          Slime Studio
        </h1>
        <button
          type="button"
          onClick={() => sair()}
          className="text-sm text-ink-muted underline outline-none focus-visible:ring-2 focus-visible:ring-neon"
        >
          Sair
        </button>
      </header>

      <form onSubmit={aoCriarAnime} className="mb-8 flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="titulo-novo-anime" className="text-xs text-ink-muted">
            Novo anime
          </label>
          <input
            id="titulo-novo-anime"
            value={tituloNovo}
            onChange={(event) => setTituloNovo(event.target.value)}
            placeholder="Título"
            className="rounded-md border border-border-chrome bg-surface px-3 py-2 text-sm text-white outline-none focus-visible:border-neon focus-visible:ring-2 focus-visible:ring-neon"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="ano-novo-anime" className="text-xs text-ink-muted">
            Ano
          </label>
          <input
            id="ano-novo-anime"
            type="number"
            min="1900"
            max={new Date().getFullYear() + 1}
            step="1"
            value={anoNovo}
            onChange={(event) => setAnoNovo(event.target.value)}
            placeholder="opcional"
            className="w-24 rounded-md border border-border-chrome bg-surface px-3 py-2 text-sm text-white outline-none focus-visible:border-neon focus-visible:ring-2 focus-visible:ring-neon"
          />
        </div>
        <button
          type="submit"
          disabled={criando}
          className="rounded-md border border-neon-soft bg-surface px-4 py-2 text-sm font-semibold text-neon outline-none transition-colors hover:border-neon disabled:cursor-not-allowed disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-neon"
        >
          {criando ? 'Adicionando…' : 'Adicionar'}
        </button>
        {erroCriacao && (
          <p role="alert" className="w-full text-sm text-red-400">
            {erroCriacao}
          </p>
        )}
      </form>

      {carregando && <p className="text-sm text-ink-muted">Carregando catálogo…</p>}
      {erro && (
        <div
          role="alert"
          className="mb-6 rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300"
        >
          Não foi possível carregar o catálogo.{' '}
          <button type="button" onClick={recarregar} className="underline">
            Tentar novamente
          </button>
        </div>
      )}
      {!carregando && !erro && animes?.length === 0 && (
        <p className="text-sm text-ink-muted">Nenhum anime cadastrado ainda.</p>
      )}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
        {animes?.map((anime) => (
          <AnimeCard key={anime.id} anime={anime} />
        ))}
      </div>
    </main>
  );
}
