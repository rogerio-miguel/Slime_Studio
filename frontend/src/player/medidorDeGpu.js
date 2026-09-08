// Mede o custo real de GPU do pipeline Anime4K interceptando
// device.queue.submit + onSubmittedWorkDone(), sem forkar a lib nem usar
// timestamp-query (que exigiria mexer nos descritores de pass internos de
// render(), que não controlamos).
//
// render() cria um GPUDevice exclusivo por sessão — a fila é só nossa, então
// isto mede O NOSSO trabalho. Carga de outros apps ainda atrasa a GPU, o que
// é o comportamento certo pra um controlador adaptativo.
//
// Duração medida = t0 antes do submit até onSubmittedWorkDone() resolver
// (GPU terminou tudo enfileirado até ali). Essa resolução passa por IPC do
// processo de GPU e cai numa task da main thread: 0,2–1 ms de ruído e
// sensível a main thread ocupada. Por isso as leituras usam p50 da janela,
// nunca a média.

const ORCAMENTO_MIN_MS = 1000 / 60; // 60 fps
const ORCAMENTO_MAX_MS = 50; // nenhum conteúdo real passa disso (~20 fps)
const MEMORIA_MS = 4000; // buffer de amostras retido

function percentil(ordenados, p) {
  if (ordenados.length === 0) return null;
  const i = Math.min(ordenados.length - 1, Math.floor((p / 100) * ordenados.length));
  return ordenados[i];
}

// Instala o medidor sobre `device`. Devolve { disponivel, ler, encerrar }.
// `encerrar()` DEVE ser chamado antes de device.destroy() — senão as
// promessas de onSubmittedWorkDone em voo rejeitam em massa (uma por frame
// enfileirado) e poluem o console.
export function instalarMedidorDeGpu(device) {
  const fila = device.queue;
  const submitOriginal = fila.submit.bind(fila);

  let ativo = true;
  let patchOk = true;
  let orcamentoMs = ORCAMENTO_MAX_MS; // só ratcheia pra baixo, até o intervalo nominal do vídeo
  const duracoes = []; // { t, ms }
  const submits = []; // performance.now() de cada submit

  try {
    fila.submit = (buffers) => {
      const t0 = performance.now();
      submitOriginal(buffers);
      if (!ativo) return;
      submits.push(t0);
      fila.onSubmittedWorkDone().then(
        () => {
          if (ativo) duracoes.push({ t: performance.now(), ms: performance.now() - t0 });
        },
        () => {
          // device destruído rejeita as promessas em voo — engolir aqui é
          // obrigatório, senão vira uma unhandled rejection por frame.
        }
      );
    };
  } catch (err) {
    patchOk = false;
    console.warn(
      '[medidorDeGpu] não foi possível interceptar queue.submit — modo preditivo indisponível:',
      err?.message
    );
  }

  function podar(agora) {
    while (duracoes.length && agora - duracoes[0].t > MEMORIA_MS) duracoes.shift();
    while (submits.length && agora - submits[0] > MEMORIA_MS) submits.shift();
  }

  return {
    disponivel: patchOk,

    // Snapshot pra HUD/política. `janelaMs` = janela do p50 de duração.
    // Devolve null se o patch não pegou (chamador cai no caminho reativo).
    ler(janelaMs = 1000) {
      if (!patchOk || !ativo) return null;
      const agora = performance.now();
      podar(agora);

      const msJanela = duracoes
        .filter((d) => agora - d.t <= janelaMs)
        .map((d) => d.ms)
        .sort((a, b) => a - b);
      const p50Ms = percentil(msJanela, 50);

      const intervalos = [];
      for (let i = 1; i < submits.length; i += 1) intervalos.push(submits[i] - submits[i - 1]);
      intervalos.sort((a, b) => a - b);
      const p10Intervalo = percentil(intervalos, 10);
      if (p10Intervalo !== null) {
        // Orçamento de frame = menor intervalo robusto entre submits já visto
        // (o nominal do vídeo em folga). Ratcheia só pra baixo: quando a GPU
        // satura os intervalos crescem, e deixá-los inflar o orçamento
        // mascararia justamente a saturação que se quer detectar.
        const candidato = Math.min(Math.max(p10Intervalo, ORCAMENTO_MIN_MS), ORCAMENTO_MAX_MS);
        orcamentoMs = Math.min(orcamentoMs, candidato);
      }

      const submitsPorSegundo = submits.filter((t) => agora - t <= 1000).length;
      const ocupacao = p50Ms === null ? null : p50Ms / orcamentoMs;

      return { p50Ms, orcamentoMs, ocupacao, submitsPorSegundo, amostras: msJanela.length };
    },

    encerrar() {
      ativo = false;
      if (!patchOk) return;
      try {
        delete fila.submit; // volta ao método do protótipo — nunca reatribuir (deixaria own property viva)
      } catch {
        /* non-configurable: nada a fazer, o guard `ativo` já neutralizou */
      }
    },
  };
}
