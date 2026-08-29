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

// Divisor que mapeia a diferença média bruta de pixel (0-255 por canal,
// ver uso abaixo) pra uma intensidade de ação normalizada 0..1 — quanto
// menor o divisor, mais sensível o "gatilho" (glow acende com pouco
// movimento). Valor de partida a calibrar visualmente, mesmo espírito do
// comentário em AMBIENT_EDGE_FRACTION acima. O clamp (Math.min(1, ...), no
// ponto de uso) cobre o caso de corte de cena — diferença bruta bem maior
// que a escala não pode virar intensidade > 1.
const AMBIENT_ACAO_ESCALA = 5;

// EMA separado de AMBIENT_SMOOTHING — aquele suaviza COR, este suaviza a
// INTENSIDADE DE AÇÃO que dirige a opacidade do halo (player.css). Precisa
// de constante de tempo própria, bem mais lenta (0.1-0.15, contra 0.3 da
// cor): a opacidade não pode "piscar" a cada frame de ação isolado, só
// crescer/decair como um fade perceptivelmente suave.
const AMBIENT_ACAO_SUAVIZACAO = 0.12;

// Inicia o loop de amostragem sobre `canvas` (2D) a partir de `video`.
// `elementoDeMedida` é o nó do `.frame` (lido via getComputedStyle pra pegar
// --ambient-bleed, ver comentário abaixo). `rvfc` é o rVFC ORIGINAL do
// vídeo (ver topo do arquivo). `aoAtualizarIntensidadeAcao`, opcional, é
// chamado uma vez por frame amostrado com a intensidade de movimento
// suavizada (0..1) — quem não passa esse callback não paga o custo de
// detectar movimento (ver early-return dentro de onFrame). Devolve
// `parar()`, que cancela o frame pendente explicitamente via
// cancelVideoFrameCallback.
export function iniciarGlowAmbiente({ video, canvas, elementoDeMedida, rvfc, aoAtualizarIntensidadeAcao }) {
  const ctx = canvas?.getContext('2d', { alpha: false });
  if (!ctx) return () => {};

  // Margem = onde as faixas de borda são esticadas pra fora; sai da mesma %
  // que o CSS usa pra esticar esse canvas pra fora do .frame
  // (--ambient-bleed), lida daqui em vez de duplicada como constante — sem
  // isso as duas proporções (canvas interno vs. caixa CSS) descasam e o
  // "centro" do bitmap para de bater com a área real do vídeo na tela.
  const bleedRaw = getComputedStyle(elementoDeMedida).getPropertyValue('--ambient-bleed');
  const bleedPct = parseFloat(bleedRaw);
  const bleedFraction = Number.isFinite(bleedPct) ? bleedPct / 100 : 0.3; // 0.3 = fallback do CSS

  const centerW = AMBIENT_CANVAS_WIDTH;
  const centerH = Math.round(centerW * (video.videoHeight / video.videoWidth)) || 18;
  const marginW = Math.max(1, Math.round(centerW * bleedFraction));
  const marginH = Math.max(1, Math.round(centerH * bleedFraction));
  canvas.width = centerW + 2 * marginW;
  canvas.height = centerH + 2 * marginH;

  let handle = null;
  // Frame amostrado anterior (Uint8ClampedArray de getImageData) e último
  // valor suavizado de intensidade — closures novas a cada chamada de
  // iniciarGlowAmbiente, então resetam sozinhas sem lógica extra.
  let bufferAnterior = null;
  let intensidadeSuavizada = 0;

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

      // Detecção de movimento pra dirigir o fade do halo — só roda pra quem
      // passou o callback (early-return de fato: sem isso, todo consumidor
      // de iniciarGlowAmbiente pagaria um getImageData por frame à toa).
      // Canvas já é minúsculo (AMBIENT_CANVAS_WIDTH + margens), então o
      // readback é barato mesmo rodando a cada frame de vídeo.
      if (aoAtualizarIntensidadeAcao) {
        const frameAtual = ctx.getImageData(0, 0, canvas.width, canvas.height).data;

        if (bufferAnterior) {
          // Diferença média absoluta por canal RGB entre este frame e o
          // anterior (alpha pulado — ctx é opaco, `alpha:false`, não carrega
          // informação nenhuma). Soma bruta / nº de amostras = diferença
          // média 0-255, que AMBIENT_ACAO_ESCALA normaliza pra 0..1.
          let somaDiferenca = 0;
          let amostras = 0;
          for (let i = 0; i < frameAtual.length; i += 4) {
            somaDiferenca += Math.abs(frameAtual[i] - bufferAnterior[i]);
            somaDiferenca += Math.abs(frameAtual[i + 1] - bufferAnterior[i + 1]);
            somaDiferenca += Math.abs(frameAtual[i + 2] - bufferAnterior[i + 2]);
            amostras += 3;
          }
          // amostras só é 0 se o canvas não tiver pixel nenhum (edge case
          // que não deveria ocorrer, ver dimensionamento acima) — guarda
          // aqui evita NaN se algum dia ocorrer.
          const diferencaMedia = amostras > 0 ? somaDiferenca / amostras : 0;
          const intensidadeBruta = Math.min(1, diferencaMedia / AMBIENT_ACAO_ESCALA);

          // EMA lenta (AMBIENT_ACAO_SUAVIZACAO) puxando pro valor bruto do
          // frame — com a cena parada, intensidadeBruta cai pra perto de 0
          // e a suavizada decai atrás dela, mesma matemática que faz o halo
          // subir, só que ao contrário.
          intensidadeSuavizada += (intensidadeBruta - intensidadeSuavizada) * AMBIENT_ACAO_SUAVIZACAO;
        }

        bufferAnterior = frameAtual;
        aoAtualizarIntensidadeAcao(intensidadeSuavizada);
      }
    }
    handle = rvfc(onFrame);
  }

  handle = rvfc(onFrame);

  return function parar() {
    if (handle !== null) video.cancelVideoFrameCallback(handle);
  };
}
