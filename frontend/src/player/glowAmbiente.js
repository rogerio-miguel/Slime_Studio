// Ambient glow — amostra do <video> FONTE (estilo YouTube Ambient Mode), não
// do canvas de saída do WebGPU: decisão deliberada pra ficar 100% desacoplado
// do pipeline anime4k-webgpu, que já roda no limite da GPU (RX 580, ver
// ESPECIFICACAO.md §11/§12). Canvas2D é barato e não disputa device/VRAM com
// o WebGPU. Usa o rVFC ORIGINAL (parâmetro `rvfc`, não
// `video.requestVideoFrameCallback` direto) — motorAnime4k.js intercepta
// esse método por geração (D2) pra matar a cadeia do pipeline Anime4K ao
// trocar de preset; o glow precisa continuar rodando através dessas trocas,
// então fica imune ao intercept.

// Poucos pixels de propósito: drawImage encolhendo já faz a "média de cor"
// da cena sem calcular nada na mão, e menos pixels = amostragem mais barata.
const AMBIENT_CANVAS_WIDTH = 32;

// Fração do vídeo-fonte considerada "borda" pra amostragem — só essa faixa
// (não a cena inteira) alimenta o halo de cada lado. É o que dá a sensação
// de continuação: céu claro no topo do quadro vira halo claro só em cima,
// chão escuro embaixo vira halo escuro só embaixo, em vez de uma média
// única do frame borrando os 4 lados pra cor igual.
const AMBIENT_EDGE_FRACTION = 0.01;

// Cada draw funde só 30% do frame novo sobre o que já estava no canvas
// (globalAlpha < 1, sem limpar antes) — sem isso, mesmo a 24fps, corte de
// cena/movimento rápido faz a cor "pular" em vez de fluir. Média móvel
// exponencial: converge pra cor real em poucos frames, mas suaviza a
// transição — mais "extensão do vídeo" do que fotos soltas trocando. Cada
// uma das 9 regiões abaixo (centro, 4 bordas, 4 cantos) é disjunta das
// outras no canvas, então essa suavização por região continua correta —
// nenhum draw pisa na área que outro acabou de atualizar.
const AMBIENT_SMOOTHING = 0.3;

// Inicia o loop de amostragem sobre `canvas` (2D) a partir de `video`.
// `elementoDeMedida` é o nó do `.frame` (lido via getComputedStyle pra pegar
// --ambient-bleed, ver comentário abaixo). `rvfc` é o rVFC ORIGINAL do
// vídeo (ver topo do arquivo). Devolve `parar()`, que cancela o frame
// pendente explicitamente via cancelVideoFrameCallback.
export function iniciarGlowAmbiente({ video, canvas, elementoDeMedida, rvfc }) {
  const ctx = canvas?.getContext('2d', { alpha: false });
  if (!ctx) return () => {};

  // Margem = onde as faixas de borda são esticadas pra fora; sai da mesma %
  // que o CSS usa pra esticar esse canvas pra fora do .frame
  // (--ambient-bleed), lida daqui em vez de duplicada como constante — sem
  // isso as duas proporções (canvas interno vs. caixa CSS) descasam e o
  // "centro" do bitmap para de bater com a área real do vídeo na tela.
  const bleedRaw = getComputedStyle(elementoDeMedida).getPropertyValue('--ambient-bleed');
  const bleedPct = parseFloat(bleedRaw);
  const bleedFraction = Number.isFinite(bleedPct) ? bleedPct / 100 : 0.1; // 0.1 = fallback do CSS

  const centerW = AMBIENT_CANVAS_WIDTH;
  const centerH = Math.round(centerW * (video.videoHeight / video.videoWidth)) || 18;
  const marginW = Math.max(1, Math.round(centerW * bleedFraction));
  const marginH = Math.max(1, Math.round(centerH * bleedFraction));
  canvas.width = centerW + 2 * marginW;
  canvas.height = centerH + 2 * marginH;

  let handle = null;

  function onFrame() {
    // Aba em segundo plano: sem efeito visível pra justificar o custo de
    // amostrar o vídeo.
    if (!document.hidden) {
      const vw = video.videoWidth;
      const vh = video.videoHeight;
      const edgeW = Math.max(1, Math.round(vw * AMBIENT_EDGE_FRACTION));
      const edgeH = Math.max(1, Math.round(vh * AMBIENT_EDGE_FRACTION));

      ctx.globalAlpha = AMBIENT_SMOOTHING;

      // Centro: frame inteiro.
      ctx.drawImage(video, marginW, marginH, centerW, centerH);

      // Bordas: só a faixa mais próxima de cada lado do vídeo, esticada pra
      // fora — a peça central do efeito "continuação" (ver AMBIENT_EDGE_FRACTION).
      ctx.drawImage(video, 0, 0, vw, edgeH, marginW, 0, centerW, marginH); // topo
      ctx.drawImage(video, 0, vh - edgeH, vw, edgeH, marginW, marginH + centerH, centerW, marginH); // baixo
      ctx.drawImage(video, 0, 0, edgeW, vh, 0, marginH, marginW, centerH); // esquerda
      ctx.drawImage(video, vw - edgeW, 0, edgeW, vh, marginW + centerW, marginH, marginW, centerH); // direita

      // Cantos: amostra do canto do vídeo, esticada no quadrado do canto —
      // sem isso os 4 retângulos de borda acima deixam os cantos do halo
      // sem desenho nenhum (cor de fundo do canvas, nunca atualizada).
      ctx.drawImage(video, 0, 0, edgeW, edgeH, 0, 0, marginW, marginH); // topo-esquerda
      ctx.drawImage(video, vw - edgeW, 0, edgeW, edgeH, marginW + centerW, 0, marginW, marginH); // topo-direita
      ctx.drawImage(video, 0, vh - edgeH, edgeW, edgeH, 0, marginH + centerH, marginW, marginH); // baixo-esquerda
      ctx.drawImage(video, vw - edgeW, vh - edgeH, edgeW, edgeH, marginW + centerW, marginH + centerH, marginW, marginH); // baixo-direita
    }
    handle = rvfc(onFrame);
  }

  handle = rvfc(onFrame);

  return function parar() {
    if (handle !== null) video.cancelVideoFrameCallback(handle);
  };
}
