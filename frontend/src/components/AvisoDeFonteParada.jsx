import { nomeDaFonte } from '../fontes.js';

// "AnimeFire parece parada: o episódio 5 deveria ter saído há 4 dias." — indício de
// que a fonte parou de publicar (`fonte_parada` de `GET /api/animes/{id}`, calculado
// no backend contra a AniList). É só sugestão: o botão abre "Trocar fonte", nada é
// trocado sozinho.

function textoDoAtraso(horas) {
  if (horas < 48) return `${horas} h`;
  return `${Math.round(horas / 24)} dias`;
}

export default function AvisoDeFonteParada({ fonteParada, aoTrocarFonte }) {
  if (!fonteParada) return null;
  const fonte = nomeDaFonte(fonteParada.dominio) ?? 'A fonte';
  return (
    <p className="flex flex-wrap items-center gap-x-2 text-xs text-amber-300">
      <span>
        {fonte} parece parada: o episódio {fonteParada.episodio_esperado} deveria ter saído há{' '}
        {textoDoAtraso(fonteParada.atraso_horas)}.
      </span>
      <button
        type="button"
        onClick={aoTrocarFonte}
        className="cursor-pointer font-bold text-neon underline-offset-2 outline-none transition-colors hover:text-white focus-visible:underline"
      >
        Trocar fonte
      </button>
    </p>
  );
}
