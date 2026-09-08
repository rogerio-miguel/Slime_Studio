import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { DEGRAUS_ADAPTATIVOS } from '../presets.js';

// "ABR para custo de GPU": percorre DEGRAUS_ADAPTATIVOS (presets.js, do melhor
// ao mais leve) reagindo a duas evidências de que a GPU não está dando conta.
//
//  - Sinal duro: falha de render()/`device.lost`, entregue por quem chama via
//    degradarPorFalhaDeGpu(). Em modo automático isso degrada em vez de matar
//    o player.
//  - Sinal mole: fração de frames dropados por janela de ~3s
//    (video.getVideoPlaybackQuality()). Pode subestimar saturação de GPU (mede
//    o que o <video> dropou, não o shader atrasando) — por isso a política
//    abaixo é conservadora e o HUD expõe o número cru pra calibração ao vivo.
//
// Sempre mede (alimenta o HUD mesmo em modo manual); só troca de degrau quando
// `ativo`. O índice de degrau é estado deste hook — PlayerAtivo só deriva o
// preset a partir dele.
//
// `degrauSalvo` semeia o índice inicial (piso que a GPU aguentou na última
// sessão, persistido pelo chamador) pra não sondar do topo toda vez;
// `aoDegrauEstavel(indice)` reporta de volta quando um degrau se firma.

const JANELA_MS = 3000;
const MIN_FRAMES_NA_JANELA = 20; // abaixo disso a janela é lixo (pausa, buffering)
const LIMIAR_DESCIDA = 0.06; // 6% de frames dropados na janela
const LIMIAR_SALTO_DUPLO = 0.25; // 25% numa única janela → desce 2 degraus já
const JANELAS_RUINS_PARA_DESCER = 2; // ~6s confirmando antes de descer 1
const LIMIAR_SUBIDA = 0.005; // janela "boa" = < 0.5% dropado
const JANELAS_BOAS_PARA_ESTAVEL = 5; // ~15s limpos → degrau vira "lembrado"
const JANELAS_BOAS_PARA_SUBIR = 12; // ~36s limpos antes de tentar subir 1 (×paciência)
const COOLDOWN_MS = 5000; // > JANELA_MS: a 1ª janela pós-troca já não conta
const MAX_FALHAS_POR_DEGRAU = 2; // 2 quedas a partir do mesmo degrau travam-no como teto
const DEDUPE_FALHA_GPU_MS = 1500; // sessão encerrada pode reportar `lost` tardio

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
    quedaNaJanela: null,
    dropadosNaJanela: 0,
    totalNaJanela: 0,
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
  // identidade nova a cada chamada — serve de chave pro aviso ao usuário.
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

  // Chamado por quem monta a sessão WebGPU quando render() falha ou o device é
  // perdido. Devolve true se conseguiu degradar (chamador engole o erro), false
  // se já está no piso (chamador trata como fatal). Dedupe curto: uma sessão
  // recém-encerrada pode emitir `lost` depois da troca.
  const degradarPorFalhaDeGpu = useCallback(() => {
    const agora = Date.now();
    if (agora - ultimaFalhaGpuRef.current < DEDUPE_FALHA_GPU_MS) return true;
    ultimaFalhaGpuRef.current = agora;
    const origem = indiceRef.current;
    if (origem >= PISO) return false;
    // Falha dura de GPU: trava o degrau de origem como teto (não só +1 no contador).
    falhasPorDegrauRef.current[origem] = MAX_FALHAS_POR_DEGRAU;
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
    cooldownAteRef.current = Date.now() + COOLDOWN_MS;
    ultimaFalhaGpuRef.current = 0;
    setIndiceDeDegrau(inicial);
    setUltimaTroca(null);
  }, [chaveDeSessao, ativo, calcularInicial]);

  // Loop de medição por janela. Roda sempre (HUD lê `diagnostico` em modo
  // manual também); só chama descer()/subir quando ativoRef.current.
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

      if (!janelaValida) {
        setDiagnostico({
          quedaNaJanela: null,
          dropadosNaJanela: 0,
          totalNaJanela: Math.max(deltaTotal, 0),
          estado: emCooldown ? 'aquecendo' : 'pausado',
        });
        return;
      }

      const queda = deltaDropados / deltaTotal;
      const noTeto =
        (falhasPorDegrauRef.current[indiceRef.current - 1] || 0) >= MAX_FALHAS_POR_DEGRAU;

      let estado;
      if (emCooldown) {
        estado = 'aquecendo';
      } else if (ativoRef.current && janelasRuinsRef.current > 0 && queda >= LIMIAR_DESCIDA) {
        estado = `${janelasRuinsRef.current} janela ruim`;
      } else if (ativoRef.current && noTeto) {
        estado = 'teto atingido';
      } else {
        estado = 'estável';
      }

      setDiagnostico({
        quedaNaJanela: queda,
        dropadosNaJanela: deltaDropados,
        totalNaJanela: deltaTotal,
        estado,
      });

      if (!ativoRef.current || emCooldown) return;

      if (queda >= LIMIAR_SALTO_DUPLO) {
        descer(2, 'dropados');
        return;
      }
      if (queda >= LIMIAR_DESCIDA) {
        janelasBoasRef.current = 0;
        janelasRuinsRef.current += 1;
        if (janelasRuinsRef.current >= JANELAS_RUINS_PARA_DESCER) descer(1, 'dropados');
        return;
      }
      janelasRuinsRef.current = 0;
      if (queda > LIMIAR_SUBIDA) {
        janelasBoasRef.current = 0; // zona neutra entre subir e descer
        return;
      }

      janelasBoasRef.current += 1;

      // Firma o degrau atual como "lembrado" bem antes de tentar subir — o
      // chamador persiste isso e a próxima sessão começa perto do que a GPU
      // aguenta, não do topo.
      if (
        janelasBoasRef.current >= JANELAS_BOAS_PARA_ESTAVEL &&
        indiceRef.current !== ultimoEstavelRef.current
      ) {
        ultimoEstavelRef.current = indiceRef.current;
        aoDegrauEstavelRef.current?.(indiceRef.current);
      }

      // Subida com paciência crescente: cada falha anterior no degrau-alvo
      // dobra a espera; MAX_FALHAS trava.
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
  }, [videoRef, aplicarDegrau, descer]);

  return { indiceDeDegrau, ultimaTroca, diagnostico, degradarPorFalhaDeGpu };
}
