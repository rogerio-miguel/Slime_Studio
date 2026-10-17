import { useEffect, useRef, useState } from 'react';
import { iniciarSessaoDeRender } from '../motorAnime4k.js';
import { PRESETS, PRESET_PADRAO, calcularDimensoesDaSessao } from '../presets.js';

// Dois efeitos com ciclos de vida bem diferentes:
//
//  - Sessão (device/contexto/inputTexture WebGPU): cara de montar, cara de
//    trocar (reconfigura o swap chain — mesma piscada que esta reescrita
//    existe pra eliminar). Só depende de `dimensoesDaFonte` (novo vídeo) e
//    de `geracaoDeSessao`, um contador que ESTE hook incrementa quando a
//    sessão morre de forma fatal (device.lost inesperado, ou a própria
//    construção falhou) — é o gatilho de "recriar do zero" que antes vinha
//    de graça do `key={presetAtual}` no canvas (removido, ver PlayerAtivo).
//  - Troca de preset: barata (trocarPreset reaproveita device/contexto/
//    inputTexture, só troca o chain de Anime4KPipeline). Depende só de
//    `presetId` — não recria a sessão.
//
// Guard de cancelamento assíncrono no efeito de sessão: se a limpeza deste
// efeito rodar antes de iniciarSessaoDeRender() resolver (StrictMode do dev
// monta/desmonta cada componente duas vezes — main.jsx mantém isso de
// propósito), o device precisa ser destruído assim que existir. Sem isso o
// StrictMode vaza um GPUDevice por mount.
export function useMotorAnime4k({ videoRef, canvasRef, presetId, dimensoesDaFonte, aoFalhar }) {
  const [adaptador, setAdaptador] = useState(null);
  const [medidor, setMedidor] = useState(null);
  const [geracaoDeSessao, setGeracaoDeSessao] = useState(0);

  const sessaoRef = useRef(null);
  // presetId "refletido" no chain ativo da sessão atual — não-reativo de
  // propósito: o efeito de troca só chama trocarPreset quando esse valor
  // diverge do presetId corrente, evitando um trocarPreset redundante logo
  // após a sessão nascer já com o preset inicial certo (ver efeito de troca
  // abaixo). Só avança em sucesso — uma troca que falhou mantém o valor
  // antigo, então uma nova tentativa (ex. presetId mudando de novo) não é
  // silenciosamente pulada por já achar que está "aplicado".
  const presetAplicadoRef = useRef(null);
  // presetId/aoFalhar lidos via ref dentro do efeito de sessão: ele não deve
  // reagir a mudança de preset (é o efeito de troca que faz isso) nem
  // recriar a função de callback a cada render do pai.
  const presetIdRef = useRef(presetId);
  const aoFalharRef = useRef(aoFalhar);
  useEffect(() => {
    presetIdRef.current = presetId;
  }, [presetId]);
  useEffect(() => {
    aoFalharRef.current = aoFalhar;
  }, [aoFalhar]);

  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !dimensoesDaFonte) return;

    let cancelado = false;
    const dimensoes = calcularDimensoesDaSessao(video);
    const presetInicial = PRESETS[presetIdRef.current] ?? PRESETS[PRESET_PADRAO];
    const presetIdInicial = presetIdRef.current;

    // Falha fatal (device.lost inesperado, ou a própria construção da
    // sessão rejeitando): reporta pro chamador via aoFalhar E força uma
    // sessão nova incrementando geracaoDeSessao — precisa acontecer nos
    // dois casos independente do que o chamador decidir fazer com o erro
    // (degradar e continuar, ou matar o player): o device desta sessão já
    // não existe mais, então não há chain nenhum rodando até recriar.
    function tratarFalhaFatal(erro) {
      aoFalharRef.current(erro);
      if (!cancelado) setGeracaoDeSessao((g) => g + 1);
    }

    // Falha ao trocar de preset: o device está vivo e o chain anterior
    // continua rodando (ver motorAnime4k.js trocarPreset) — só precisa
    // degradar o degrau, não recriar sessão nenhuma.
    function aoFalharTroca(erro) {
      aoFalharRef.current(erro);
    }

    iniciarSessaoDeRender({
      video,
      canvas,
      dimensoes,
      presetInicial,
      aoFalharTroca,
      aoFalharSessao: tratarFalhaFatal,
    })
      .then((sessao) => {
        if (cancelado) {
          sessao.encerrar();
          return;
        }
        sessaoRef.current = sessao;
        presetAplicadoRef.current = presetIdInicial;
        setAdaptador(sessao.adaptador);
        setMedidor(sessao.medidor);
      })
      .catch((erro) => {
        if (cancelado) return;
        tratarFalhaFatal(erro);
      });

    return () => {
      cancelado = true;
      sessaoRef.current?.encerrar();
      sessaoRef.current = null;
      presetAplicadoRef.current = null;
      setAdaptador(null);
      setMedidor(null);
    };
    // videoRef/canvasRef são refs estáveis (useRef) — não entram nas deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dimensoesDaFonte, geracaoDeSessao]);

  // Troca de preset em runtime: `adaptador` nas deps (não `presetId` sozinho)
  // garante que este efeito também rode assim que uma sessão nova fica
  // pronta — cobre a corrida de `presetId` ter mudado enquanto a sessão
  // anterior ainda estava sendo (re)construída (presetAplicadoRef guarda o
  // preset com que a sessão nasceu; se já bate com o presetId atual, o
  // early-return abaixo evita reconstruir o mesmo chain à toa).
  useEffect(() => {
    const preset = PRESETS[presetId];
    const sessao = sessaoRef.current;
    if (!preset || !sessao || presetAplicadoRef.current === presetId) return;
    if (sessao.trocarPreset(preset)) {
      presetAplicadoRef.current = presetId;
    }
  }, [presetId, adaptador]);

  return { adaptador, medidor };
}
