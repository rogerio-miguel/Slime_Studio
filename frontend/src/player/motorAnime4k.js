// Mesmo pacote CJS-only de presets.js (ver comentário completo lá sobre
// import de namespace em vez de default) — aqui só precisamos de `render`,
// não dos blocos de shader.
import * as Anime4K from 'anime4k-webgpu';

const { render } = Anime4K;

// --- Interceptador de rVFC por geração (D2) --------------------------------
//
// render() da lib cria um GPUDevice próprio e inicia um
// requestVideoFrameCallback (rVFC) recursivo sem devolver handle de parada.
// Trocar de preset em runtime sem tratamento vaza device + deixa o laço rVFC
// anterior vivo (chamando um pipeline que não existe mais). Instalamos o
// interceptador uma única vez por elemento <video>: cada sessão de render
// ganha um número de geração, avançada tanto no INÍCIO de
// iniciarSessaoDeRender (invalida qualquer sessão anterior antes do await
// render(), determinístico independente da ordem de resolução das Promises
// — necessário pra sobreviver ao StrictMode: mount1 → cleanup1 assíncrono →
// mount2 pode fazer as duas chamadas capturarem a mesma geração se o avanço
// só acontecesse em encerrar()) quanto em encerrar() (mata a própria sessão
// quando não há uma nova pra suceder). Quando a geração muda, o callback
// guardado do rVFC para de rodar — e, por isso, para de re-registrar a si
// mesmo (a cadeia da lib só continua porque cada callback pede o próximo de
// dentro de si mesmo).
const registrosRvfcPorVideo = new WeakMap();

function garantirInterceptadorRvfc(video) {
  let registro = registrosRvfcPorVideo.get(video);
  if (registro) return registro;

  const rvfcOriginal = video.requestVideoFrameCallback.bind(video);
  registro = { geracao: 0, rvfcOriginal };
  registrosRvfcPorVideo.set(video, registro);

  video.requestVideoFrameCallback = (cb) => {
    const geracaoDoRegistro = registro.geracao;
    return rvfcOriginal((now, meta) => {
      if (geracaoDoRegistro !== registro.geracao) return; // sessão morta: não roda e, por isso, não re-registra
      cb(now, meta);
    });
  };

  return registro;
}

// HUD (useTelemetriaDeVideo.js) e glow (GlowAmbiente.jsx) chamam o rVFC
// ORIGINAL devolvido aqui, não o intercept acima — ficam imunes ao ciclo de
// vida do pipeline Anime4K, que é o comportamento certo: eles amostram o
// <video> fonte, não o resultado do pipeline WebGPU.
export function obterRvfcOriginal(video) {
  return garantirInterceptadorRvfc(video).rvfcOriginal;
}

// --- Captura dos handles reais de GPUAdapter/GPUDevice (D4) ----------------
//
// render() da anime4k-webgpu@1.0.0 (bundle CJS sem API pública documentada)
// não devolve o GPUDevice nem qualquer handle pra ele — cria e encapsula
// tudo internamente via navigator.gpu.requestAdapter()/adapter.requestDevice().
// Captura via patch de instância (não de GPUAdapter.prototype: o blast
// radius fica restrito ao adapter realmente devolvido por essa chamada, mais
// fácil de revisar do que alterar o protótipo global) pra recuperar os
// handles reais usados pelo pipeline. Restaurado assim que render() resolve
// (D4, chamado por iniciarSessaoDeRender abaixo) — senão N trocas de preset
// empilham N wrappers.
function capturarHandlesGpu() {
  const requestAdapterOriginal = navigator.gpu.requestAdapter.bind(navigator.gpu);
  let adapterCapturado = null;
  let deviceCapturado = null;

  navigator.gpu.requestAdapter = async (...args) => {
    const adapter = await requestAdapterOriginal(...args);
    if (adapter) {
      adapterCapturado = adapter;
      const requestDeviceOriginal = adapter.requestDevice.bind(adapter);
      adapter.requestDevice = async (...deviceArgs) => {
        const device = await requestDeviceOriginal(...deviceArgs);
        deviceCapturado = device;
        return device;
      };
    }
    return adapter;
  };

  return {
    restaurar: () => {
      navigator.gpu.requestAdapter = requestAdapterOriginal;
    },
    obterAdapter: () => adapterCapturado,
    obterDevice: () => deviceCapturado,
  };
}

// Destrói o device ativo explicitamente ao sair da página, em vez de
// depender do navegador reciclar sozinho: recarregar rápido (ex. preset
// travando) empilha GPUDevices vivos, já que render() nunca chama destroy()
// sozinho. `event.persisted` indica que a página está indo pro bfcache (não
// sendo destruída de fato) — nesse caso destruir o device quebraria a
// página se o usuário voltar com o botão "voltar", então pulamos.
let dispositivoAtivo = null;

window.addEventListener('pagehide', (event) => {
  if (event.persisted) return;
  dispositivoAtivo?.destroy();
});

// Inicia uma sessão de render do pipeline Anime4K sobre `video`/`canvas` para
// `preset` (objeto de presets.js, já resolvido pelo chamador — ver D1),
// mirando `dimensoes` (já calculadas pelo chamador via
// calcularDimensoesDeSaida). Já avança a geração do interceptador de rVFC
// antes do await render() (D2, ver comentário acima) — invalida qualquer
// sessão anterior sobre o mesmo <video> assim que esta começa. Devolve
// `{ encerrar, adaptador }`: `encerrar()` avança a geração de novo (mata a
// cadeia da lib quando não há sessão nova pra suceder) e destrói o
// GPUDevice capturado; `adaptador` é o GPUAdapter real (usado pelo HUD, ver
// useTelemetriaDeVideo.js). Falha em render() destrói o device capturado
// (se algum existir) e propaga o erro via `aoFalhar` (recebe um Error),
// nunca em silêncio.
export async function iniciarSessaoDeRender({ video, canvas, preset, dimensoes, aoFalhar }) {
  const registroRvfc = garantirInterceptadorRvfc(video);
  registroRvfc.geracao += 1;

  canvas.width = dimensoes.width;
  canvas.height = dimensoes.height;
  // `dimensoes` só dimensiona o canvas — o blit da lib reduz a saída do
  // último bloco pra esse tamanho. O preset não precisa mais dele.
  const pipelineBuilder = preset.build();

  // Captura síncrona, antes do await, pra garantir que o patch já esteja
  // instalado quando render() pedir o adapter internamente.
  const captura = capturarHandlesGpu();

  try {
    await render({ video, canvas, pipelineBuilder });
  } catch (err) {
    captura.restaurar();
    captura.obterDevice()?.destroy();
    aoFalhar(new Error(`Falha ao inicializar WebGPU: ${err.message}`));
    return { encerrar: () => {}, adaptador: null };
  }
  captura.restaurar();

  const device = captura.obterDevice();
  const adaptador = captura.obterAdapter();

  if (!device) {
    console.error('[Anime4K] Falha ao capturar GPUDevice — vazamento de GPU NÃO resolvido nesta sessão.');
  }

  dispositivoAtivo = device;

  device?.lost.then((info) => {
    if (info.reason === 'destroyed') return; // esperado: foi o nosso próprio destroy() em encerrar()/pagehide
    aoFalhar(new Error(`GPU perdeu o device (${info.reason}): ${info.message}`));
  });
  device?.addEventListener('uncapturederror', (event) => {
    console.error('[Anime4K] WebGPU uncaptured error:', event.error);
  });

  function encerrar() {
    registroRvfc.geracao += 1;
    device?.destroy();
    if (dispositivoAtivo === device) dispositivoAtivo = null;
  }

  return { encerrar, adaptador };
}
