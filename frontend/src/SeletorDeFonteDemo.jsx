import { useState } from 'react';
import { useFocoAoMontar } from './hooks/useFocoAoMontar.js';

// Modo debug/fallback permanente (não é andaime descartável — decisão da
// Fase 4, ESPECIFICACAO.md §10): monta a rota "/debug/fonte" (App.jsx),
// pra tocar um arquivo local ou URL arbitrária sem depender do
// catálogo/backend. Arquivo/URL nunca é copiado pro repo nem vira caminho
// absoluto em config; Blob URL é same-origin, não taint no WebGPU.
export default function SeletorDeFonteDemo({ aoEscolherFonte }) {
  const [urlDigitada, setUrlDigitada] = useState('');
  const focoTitulo = useFocoAoMontar();

  function aoEscolherArquivo(event) {
    const arquivo = event.target.files?.[0];
    if (!arquivo) return;
    aoEscolherFonte(URL.createObjectURL(arquivo));
  }

  function aoEnviarUrl(event) {
    event.preventDefault();
    if (!urlDigitada.trim()) return;
    aoEscolherFonte(urlDigitada.trim());
  }

  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-6 px-6 py-16 text-center">
      <h1 ref={focoTitulo} tabIndex={-1} className="text-xl font-medium text-white outline-none">
        Slime Studio
      </h1>
      <p className="text-sm text-[#999]">
        Escolha um arquivo de vídeo local ou cole a URL de um stream (.m3u8) pra testar o player.
      </p>
      <label className="w-full cursor-pointer rounded-md border border-border-chrome bg-[#111] px-4 py-3 text-sm text-white hover:bg-[#1c1c1c]">
        Escolher arquivo de vídeo
        <input type="file" accept="video/*" onChange={aoEscolherArquivo} className="hidden" />
      </label>
      <form onSubmit={aoEnviarUrl} className="flex w-full gap-2">
        <input
          type="url"
          value={urlDigitada}
          onChange={(event) => setUrlDigitada(event.target.value)}
          placeholder="https://.../playlist.m3u8"
          aria-label="URL do vídeo ou stream"
          className="flex-1 rounded-md border border-border-chrome bg-[#111] px-3 py-2 text-sm text-white placeholder:text-[#666]"
        />
        <button
          type="submit"
          className="rounded-md border border-border-chrome bg-[#222] px-4 py-2 text-sm text-white hover:bg-[#2a2a2a]"
        >
          Carregar
        </button>
      </form>
    </div>
  );
}
