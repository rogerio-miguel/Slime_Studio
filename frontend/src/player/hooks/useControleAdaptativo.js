import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { DEGRAUS_ADAPTATIVOS } from '../presets.js';

// "ABR para custo de GPU": percorre DEGRAUS_ADAPTATIVOS (presets.js, do melhor
// ao mais leve) reagindo a evidências de que a GPU não está dando conta.
//
//  - Sinal duro: falha de render()/`device.lost`, via degradarPorFalhaDeGpu().
//    Em modo automático degrada em vez de matar o player.
//  - Sinal mole: `pressão` por janela de 3s = quanto a taxa de apresentação
//    do canvas (medidorDeGpu, submits/s) fica abaixo do fps do conteúdo. Se o
//    pipeline não sustenta o fps do vídeo, a apresentação cai — sinal direto,
//    diferente de frames dropados (que medimos ao vivo ser quase cego a
//    shader lento). Sem medidor de apresentação, cai no fallback de frames
//    dropados; sem fps do conteúdo ainda estimado, não decide nada ('aquecendo').
//
//    fps do conteúdo = p20 de um histórico de taxas de decode por janela
//    (`totalVideoFrames`). Em regime o decoder roda a 1x (playback é 1x) →
//    taxa de decode == taxa do conteúdo, independente da carga da GPU. Só
//    passa disso enchendo o buffer no início / pós-seek (lê alto, transiente)
//    — o p20 descarta esse transiente e também glitches que leem baixo. NÃO
//    se usa metadata.mediaTime aqui: nesta stack, quando o pipeline satura o
//    compositor o `<video>` oculto perde frames internamente e o mediaTime
//    por callback infla, fabricando um "fps do conteúdo" que cai com a carga
//    — exatamente quando a métrica precisa ser estável.
//
// Sempre mede (alimenta o HUD mesmo em modo manual); só troca de degrau quando
// `ativo`. `degrauSalvo` semeia o índice inicial; `aoDegrauEstavel(indice)`
// reporta de volta quando um degrau se firma (o chamador persiste).

const JANELA_MS = 3000;
const MIN_FRAMES_NA_JANELA = 20; // Δframes de decode abaixo disso = janela lixo (pausa/buffering)
const LIMIAR_DESCIDA = 0.15; // apresenta ~15% abaixo do conteúdo → degrau apertado
const LIMIAR_SALTO_DUPLO = 0.4; // ~40% abaixo numa janela → desce 2 degraus já
const JANELAS_RUINS_PARA_DESCER = 2; // ~6s confirmando antes de descer 1
const LIMIAR_SUBIDA = 0.05; // dentro de 5% do fps do conteúdo = folga
const JANELAS_BOAS_PARA_ESTAVEL = 5; // ~15s limpos → degrau vira "lembrado"
const JANELAS_BOAS_PARA_SUBIR = 12; // ~36s limpos antes de tentar subir 1 (×paciência)
const COOLDOWN_MS = 5000; // > JANELA_MS: a 1ª janela pós-troca já não conta
const MAX_FALHAS_POR_DEGRAU = 2; // 2 quedas a partir do mesmo degrau travam-no como teto
const DEDUPE_FALHA_GPU_MS = 1500; // sessão encerrada pode reportar `lost` tardio
const DROPADOS_PARA_PRESSAO_MAX = 0.08; // fallback: 8% de frames dropados = pressão 1

// Estimativa do fps do conteúdo pela taxa de decode por janela.
const FPS_CONTEUDO_MIN = 10; // janela abaixo disso = lixo (não é taxa de conteúdo real)
const FPS_CONTEUDO_MAX = 130; // idem acima disso
const HISTORICO_FPS_CONTEUDO = 12; // ~36s de janelas retidas
const JANELAS_PARA_FPS_CONTEUDO = 3; // mínimo pra estimar (evita latch numa janela ruim)
const PERCENTIL_FPS_CONTEUDO = 0.2; // p20: descarta enchimento de buffer (alto) e glitch (baixo)

const PISO = DEGRAUS_ADAPTATIVOS.length - 1;

function clampDegrau(n) {
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(Math.round(n), PISO));
}

function lerDegrauDaUrl() {
  try {
    const bruto = new URLSearchParams(window.location.search).get('degrau');
    return bruto === null ? null : clampDegrau(Number(bruto));
  } catch {
    return null;
  }
}

export function useControleAdaptativo({
  videoRef,
  ativo,
  chaveDeSessao,
  medidorRef,
  degrauSalvo = 0,
  aoDegrauEstavel,
}) {
  const degrauDaUrl = useMemo(lerDegrauDaUrl, []);

  const ativoRef = useRef(ativo);
  const degrauSalvoRef = useRef(degrauSalvo);
  const aoDegrauEstavelRef = useRef(aoDegrauEstavel);

  const calcularInicial = useCallback(
    () => (degrauDaUrl !== null ? degrauDaUrl : clampDegrau(degrauSalvoRef.current)),
    [degrauDaUrl]
  );

  const [indiceDeDegrau, setIndiceDeDegrau] = useState(calcularInicial);
  const [ultimaTroca, setUltimaTroca] = useState(null);
  const [diagnostico, setDiagnostico] = useState({
    pressaoNaJanela: null,
    fpsApresentacao: null,
    fpsConteudo: null,
    estado: 'aquecendo',
  });

  const indiceRef = useRef(indiceDeDegrau);
  const ultimoEstavelRef = useRef(indiceDeDegrau);
  const cooldownAteRef = useRef(0);
  const janelasRuinsRef = useRef(0);
  const janelasBoasRef = useRef(0);
  const falhasPorDegrauRef = useRef({}); // { [indice]: contagem }
  const snapshotRef = useRef(null); // { dropados, total } da amostra anterior
  const ultimaFalhaGpuRef = useRef(0);
  const historicoFpsConteudoRef = useRef([]); // taxas de decode por janela
  const fpsConteudoRef = useRef(null); // p20 do histórico acima, ou null enquanto aquece

  useEffect(() => {
    ativoRef.current = ativo;
  }, [ativo]);
  useEffect(() => {
    degrauSalvoRef.current = degrauSalvo;
  }, [degrauSalvo]);
  useEffect(() => {
    aoDegrauEstavelRef.current = aoDegrauEstavel;
  }, [aoDegrauEstavel]);

  // Aplica um degrau novo e reinicia contadores/cooldown. `ultimaTroca` ganha
  // identidade nova a cada chamada.
  const aplicarDegrau = useCallback((alvo, direcao, motivo) => {
    indiceRef.current = alvo;
    janelasRuinsRef.current = 0;
    janelasBoasRef.current = 0;
    cooldownAteRef.current = Date.now() + COOLDOWN_MS;
    setIndiceDeDegrau(alvo);
    setUltimaTroca({ indice: alvo, direcao, motivo, em: Date.now() });
  }, []);

  const descer = useCallback(
    (passos, motivo) => {
      const origem = indiceRef.current;
      const alvo = Math.min(origem + passos, PISO);
      if (alvo === origem) return false;
      falhasPorDegrauRef.current[origem] = (falhasPorDegrauRef.current[origem] || 0) + 1;
      aplicarDegrau(alvo, 'baixo', motivo);
      return true;
    },
    [aplicarDegrau]
  );

  // Chamado por quem monta a sessão WebGPU quando render() falha / o device é
  // perdido. true = degradou (chamador engole o erro); false = já está no piso
  // (chamador trata como fatal). Dedupe: sessão encerrada pode emitir `lost` tarde.
  const degradarPorFalhaDeGpu = useCallback(() => {
    const agora = Date.now();
    if (agora - ultimaFalhaGpuRef.current < DEDUPE_FALHA_GPU_MS) return true;
    ultimaFalhaGpuRef.current = agora;
    const origem = indiceRef.current;
    if (origem >= PISO) return false;
    falhasPorDegrauRef.current[origem] = MAX_FALHAS_POR_DEGRAU; // trava o degrau de origem
    aplicarDegrau(Math.min(origem + 1, PISO), 'baixo', 'gpu');
    return true;
  }, [aplicarDegrau]);

  // Reset ao trocar de vídeo ou (re)entrar em modo automático.
  useEffect(() => {
    const inicial = calcularInicial();
    indiceRef.current = inicial;
    ultimoEstavelRef.current = inicial;
    janelasRuinsRef.current = 0;
    janelasBoasRef.current = 0;
    falhasPorDegrauRef.current = {};
    snapshotRef.current = null;
    historicoFpsConteudoRef.current = [];
    fpsConteudoRef.current = null;
    cooldownAteRef.current = Date.now() + COOLDOWN_MS;
    ultimaFalhaGpuRef.current = 0;
    setIndiceDeDegrau(inicial);
    setUltimaTroca(null);
  }, [chaveDeSessao, ativo, calcularInicial]);

  // Loop de medição por janela. Roda sempre (HUD lê `diagnostico` em modo
  // manual também); só troca de degrau quando ativoRef.current.
  useEffect(() => {
    const video = videoRef.current;
    if (!video || typeof video.getVideoPlaybackQuality !== 'function') return;

    const aoBuscar = () => {
      cooldownAteRef.current = Date.now() + COOLDOWN_MS;
    };
    video.addEventListener('seeking', aoBuscar);

    const id = setInterval(() => {
      const q = video.getVideoPlaybackQuality();
      const anterior = snapshotRef.current;
      snapshotRef.current = { dropados: q.droppedVideoFrames, total: q.totalVideoFrames };
      if (!anterior) return;

      const deltaDropados = q.droppedVideoFrames - anterior.dropados;
      const deltaTotal = q.totalVideoFrames - anterior.total;
      const emCooldown = Date.now() < cooldownAteRef.current;
      const janelaValida =
        !video.paused && !document.hidden && deltaTotal >= MIN_FRAMES_NA_JANELA;

      // Estima o fps do conteúdo pela taxa de decode. Só janelas de regime
      // (válida, fora de cooldown/pós-seek); o p20 do histórico descarta o
      // enchimento de buffer (lê alto) e glitches (lê baixo).
      const fpsJanela = deltaTotal / (JANELA_MS / 1000);
      if (janelaValida && !emCooldown && fpsJanela >= FPS_CONTEUDO_MIN && fpsJanela <= FPS_CONTEUDO_MAX) {
        const historico = historicoFpsConteudoRef.current;
        historico.push(fpsJanela);
        if (historico.length > HISTORICO_FPS_CONTEUDO) historico.shift();
        if (historico.length >= JANELAS_PARA_FPS_CONTEUDO) {
          const ordenado = [...historico].sort((a, b) => a - b);
          fpsConteudoRef.current = ordenado[Math.floor(ordenado.length * PERCENTIL_FPS_CONTEUDO)];
        }
      }
      const fpsConteudo = fpsConteudoRef.current;

      // Pressão: quanto a apresentação fica abaixo do fps do conteúdo. Com
      // medidor de apresentação + fps do conteúdo já medido, usa a taxa de
      // submits; sem medidor, cai no fallback reativo de frames dropados; sem
      // fps do conteúdo ainda medido, não decide nada (pressao = null).
      const leituraGpu = medidorRef?.current?.ler(JANELA_MS);
      const fpsApresentacao = leituraGpu?.fpsApresentacao ?? null;
      let pressao = null;
      if (janelaValida) {
        if (fpsApresentacao !== null && fpsConteudo) {
          pressao = Math.max(0, Math.min(1, 1 - fpsApresentacao / fpsConteudo));
        } else if (fpsApresentacao === null) {
          pressao = Math.min(1, deltaDropados / deltaTotal / DROPADOS_PARA_PRESSAO_MAX);
        }
      }

      if (!janelaValida || pressao === null) {
        setDiagnostico({
          pressaoNaJanela: null,
          fpsApresentacao,
          fpsConteudo,
          estado: !janelaValida && !emCooldown ? 'pausado' : 'aquecendo',
        });
        return;
      }

      const noTeto =
        (falhasPorDegrauRef.current[indiceRef.current - 1] || 0) >= MAX_FALHAS_POR_DEGRAU;

      let estado;
      if (emCooldown) {
        estado = 'aquecendo';
      } else if (ativoRef.current && janelasRuinsRef.current > 0 && pressao >= LIMIAR_DESCIDA) {
        estado = `${janelasRuinsRef.current} janela apertada`;
      } else if (ativoRef.current && noTeto) {
        estado = 'teto atingido';
      } else {
        estado = 'estável';
      }

      setDiagnostico({ pressaoNaJanela: pressao, fpsApresentacao, fpsConteudo, estado });

      if (!ativoRef.current || emCooldown) return;

      if (pressao >= LIMIAR_SALTO_DUPLO) {
        descer(2, 'apresentacao');
        return;
      }
      if (pressao >= LIMIAR_DESCIDA) {
        janelasBoasRef.current = 0;
        janelasRuinsRef.current += 1;
        if (janelasRuinsRef.current >= JANELAS_RUINS_PARA_DESCER) descer(1, 'apresentacao');
        return;
      }
      janelasRuinsRef.current = 0;
      if (pressao > LIMIAR_SUBIDA) {
        janelasBoasRef.current = 0; // zona neutra entre subir e descer
        return;
      }

      janelasBoasRef.current += 1;

      // Firma o degrau atual como "lembrado" antes de tentar subir.
      if (
        janelasBoasRef.current >= JANELAS_BOAS_PARA_ESTAVEL &&
        indiceRef.current !== ultimoEstavelRef.current
      ) {
        ultimoEstavelRef.current = indiceRef.current;
        aoDegrauEstavelRef.current?.(indiceRef.current);
      }

      // Subida com paciência crescente: cada falha anterior no alvo dobra a espera.
      const alvo = indiceRef.current - 1;
      if (alvo < 0) return;
      const falhasNoAlvo = falhasPorDegrauRef.current[alvo] || 0;
      if (falhasNoAlvo >= MAX_FALHAS_POR_DEGRAU) return;
      if (janelasBoasRef.current >= JANELAS_BOAS_PARA_SUBIR * (1 + falhasNoAlvo)) {
        aplicarDegrau(alvo, 'cima', 'subida');
      }
    }, JANELA_MS);

    return () => {
      clearInterval(id);
      video.removeEventListener('seeking', aoBuscar);
    };
  }, [videoRef, medidorRef, aplicarDegrau, descer]);

  return { indiceDeDegrau, ultimaTroca, diagnostico, degradarPorFalhaDeGpu };
}
