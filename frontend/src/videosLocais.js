// Vídeos locais catalogados manualmente — arquivos já em disco
// (public/videos-locais/, servidos estáticos pelo Vite, gitignored), sem
// registro de `Anime`/`Episodio` no backend. Por isso ficam fora do fluxo
// normal de captura (extractors/, Job, HLS): o card aponta direto pro
// arquivo .mp4 e o player (fonteHls.js) já toca qualquer URL que não seja
// .m3u8 nativamente via `video.src`, sem hls.js — nenhuma mudança de player
// foi necessária.
//
// Fonte única de verdade pra `paginas/Galeria.jsx` (lista os cards) e
// `paginas/PaginaDoPlayerLocal.jsx` (resolve `slug` -> arquivo). `slug` é
// só a chave de rota (`/assistir-local/:slug`), não precisa bater com o
// nome do arquivo.
export const VIDEOS_LOCAIS = [
  {
    slug: 'saber-alter-vs-rider',
    titulo: 'Saber Alter VS Rider — Total Sound Re-DESIGN',
    arquivo: '/videos-locais/saber-alter-vs-rider-total-sound-redesign.mp4',
  }
];
