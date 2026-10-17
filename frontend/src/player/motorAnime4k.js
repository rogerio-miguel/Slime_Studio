// Este arquivo não importa `anime4k-webgpu` diretamente — só consome o
// formato `Anime4KPipeline` (updateParam/pass/getOutputTexture, ver
// node_modules/anime4k-webgpu/lib/pipelines/interfaces.d.ts) através de
// `preset.build()` (presets.js, dono do import da lib — ver comentário lá
// sobre import de namespace em vez de default). Aqui reimplementamos por
// cima o que a função `render()` da lib fazia, em vez de chamá-la — ver
// racional abaixo.
import { instalarMedidorDeGpu } from './medidorDeGpu.js';

// --- Dono do device e do laço de frame -------------------------------------
//
// A lib `anime4k-webgpu` só expõe `render(options): Promise<void>` — sem API
// de reconfiguração, sem devolver o GPUDevice, sem cancelar o próprio laço
// de requestVideoFrameCallback (rVFC). Isso forçava, na versão anterior
// deste arquivo, três hacks só para sobreviver a troca de preset em runtime:
// interceptar rVFC por geração pra matar o laço da chamada anterior,
// remontar o `<canvas>` inteiro (via `key`) pra forçar um WebGPUContext
// virgem a cada troca, e monkey-patch de `navigator.gpu.requestAdapter`/
// `adapter.requestDevice` só pra recuperar o GPUDevice real que `render()`
// não devolve. Cada troca de degrau recriava a sessão WebGPU inteira —
// visível como uma piscada de tela.
//
// O corpo de `render()` usa só a interface pública `Anime4KPipeline`
// (`updateParam`/`pass`/`getOutputTexture`, ver
// node_modules/anime4k-webgpu/lib/pipelines/interfaces.d.ts) sobre um device/
// contexto/inputTexture que ela mesma monta uma vez por chamada. Passamos a
// montar esse device/contexto/inputTexture UMA VEZ por vídeo (não por
// preset) e a chamar só `preset.build()(device, inputTexture)` pra obter a
// lista de pipelines — o resto (loop de frame, blit final) é nosso, cópia
// fiel do que o bundle da lib faz (conferido via grep no bundle: mesmos
// dois WGSL triviais abaixo, mesma sequência de chamadas WebGPU).
//
// Os dois shaders de blit (fullscreen quad + sample direto) são reescritos
// aqui a partir do comportamento observado do bundle da anime4k-webgpu
// (MIT, https://github.com/Anime4KWebBoost/Anime4K-WebGPU) — não copiados
// literalmente, mas equivalentes: um triângulo/quad de tela cheia sem
// vertex buffer (posições geradas por índice) e um fragment que só amostra
// a textura de entrada.
const BLIT_VERTEX_WGSL = `
struct VertexOutput {
  @builtin(position) position: vec4<f32>,
  @location(0) fragUV: vec2<f32>,
};

@vertex
fn main(@builtin(vertex_index) vertexIndex: u32) -> VertexOutput {
  var pos = array<vec2<f32>, 6>(
    vec2<f32>(-1.0, -1.0), vec2<f32>(1.0, -1.0), vec2<f32>(-1.0, 1.0),
    vec2<f32>(-1.0, 1.0), vec2<f32>(1.0, -1.0), vec2<f32>(1.0, 1.0),
  );
  var uv = array<vec2<f32>, 6>(
    vec2<f32>(0.0, 1.0), vec2<f32>(1.0, 1.0), vec2<f32>(0.0, 0.0),
    vec2<f32>(0.0, 0.0), vec2<f32>(1.0, 1.0), vec2<f32>(1.0, 0.0),
  );
  var out: VertexOutput;
  out.position = vec4<f32>(pos[vertexIndex], 0.0, 1.0);
  out.fragUV = uv[vertexIndex];
  return out;
}
`;

const BLIT_FRAGMENT_WGSL = `
@group(0) @binding(0) var mySampler: sampler;
@group(0) @binding(1) var myTexture: texture_2d<f32>;

@fragment
fn main(@location(0) fragUV: vec2<f32>) -> @location(0) vec4<f32> {
  return textureSampleBaseClampToEdge(myTexture, mySampler, fragUV);
}
`;

// --- D5: liberação manual das texturas do chain trocado ---------------------
//
// Os `Anime4KPipeline` da lib não têm `destroy()` e guardam suas texturas
// internas sob nomes que variam por classe (`outputTexture` na maioria,
// `texture` em BilateralMean, `textures` — array — em DoG; pipelines
// compostos guardam sub-pipelines aninhados em `pipelines`, um array —
// confirmado via grep no bundle: `this.outputTexture=`, `this.texture=`,
// `this.textures=[...]`, `this.pipelines=[...]`). Sem uma API de destroy,
// walk recursivo genérico em vez de um destroy por classe: menos código e
// não quebra se uma versão futura da lib renomear um campo interno.
//
// `preservar` é o conjunto de objetos que NUNCA podem ser destruídos mesmo
// se aparecerem no walk: a `inputTexture` compartilhada (referenciada por
// múltiplos blocos do chain, ex. `this.inputTexture` em DoG/BilateralMean)
// e device/adapter/queue (não deveriam aparecer aqui, mas o walk é
// defensivo mesmo assim). Falha em qualquer etapa não deve arrebentar a
// troca de preset — só degrada pra GC (log, nunca throw): "destruir de
// menos" vaza VRAM até o preset trocar de novo; "destruir demais" derruba o
// chain que ainda está em uso.
function ehGpuDevice(valor) {
  return typeof GPUDevice !== 'undefined' && valor instanceof GPUDevice;
}
function ehGpuAdapter(valor) {
  return typeof GPUAdapter !== 'undefined' && valor instanceof GPUAdapter;
}
function ehGpuQueue(valor) {
  return typeof GPUQueue !== 'undefined' && valor instanceof GPUQueue;
}

// Exportado: presets.js também precisa (montarPipeline usa pra limpar
// blocos já construídos quando um bloco NO MEIO da chain falha ao alocar —
// ver comentário lá).
export function destruirTexturasDoChain(pipelines, preservar) {
  const visitados = new WeakSet();

  function visitar(valor) {
    if (!valor || typeof valor !== 'object') return;
    if (visitados.has(valor)) return;
    visitados.add(valor);

    if (ehGpuDevice(valor) || ehGpuAdapter(valor) || ehGpuQueue(valor)) return;

    if (typeof GPUTexture !== 'undefined' && valor instanceof GPUTexture) {
      if (preservar.has(valor)) return;
      valor.destroy();
      return;
    }
    if (typeof GPUBuffer !== 'undefined' && valor instanceof GPUBuffer) {
      if (preservar.has(valor)) return;
      valor.destroy();
      return;
    }

    if (Array.isArray(valor)) {
      for (const item of valor) visitar(item);
      return;
    }

    // Só objetos "planos" (instâncias das próprias classes da lib ou
    // literais) — evita descer em GPUCommandEncoder/GPUBindGroup/etc. que
    // não seguram texturas próprias e não precisam ser percorridos, mas
    // não faz mal percorrer mesmo assim (Object.values de um GPU* nativo
    // devolve vazio ou primitivos).
    for (const chave of Object.keys(valor)) {
      try {
        visitar(valor[chave]);
      } catch {
        // Getter que lança, propriedade não acessível etc. — ignora e segue.
      }
    }
  }

  try {
    for (const pipeline of pipelines) visitar(pipeline);
  } catch (err) {
    console.warn('[Anime4K] Falha ao liberar texturas do chain anterior — degradando para GC:', err?.message);
  }
}

// Destrói o device ativo explicitamente ao sair da página, em vez de
// depender do navegador reciclar sozinho: recarregar rápido (ex. preset
// travando) empilha GPUDevices vivos se nada chamar destroy(). `event.persisted`
// indica que a página está indo pro bfcache (não sendo destruída de fato) —
// nesse caso destruir o device quebraria a página se o usuário voltar com o
// botão "voltar", então pulamos.
let dispositivoAtivo = null;

window.addEventListener('pagehide', (event) => {
  if (event.persisted) return;
  dispositivoAtivo?.destroy();
});

// Espera o vídeo ter frame disponível pra copiar (mesmo ponto de partida do
// bundle da lib). Usa addEventListener (não `video.onloadeddata =`, que
// atropelaria qualquer outro handler já pendurado ali — erro real do bundle
// da lib, não repetido aqui) com `{ once: true }`.
function aguardarFrameDisponivel(video) {
  if (video.readyState >= video.HAVE_FUTURE_DATA) return Promise.resolve();
  return new Promise((resolve) => {
    video.addEventListener('loadeddata', () => resolve(), { once: true });
  });
}

// Monta bind group layout + pipeline de blit (2 WGSL nossos, ver acima) +
// sampler linear — uma vez por sessão, reaproveitados a cada troca de
// preset (só o bind group em si — que aponta pra textura de saída do chain
// ativo — é recriado por troca).
function montarBlit(device, format) {
  const bindGroupLayout = device.createBindGroupLayout({
    entries: [
      { binding: 0, visibility: GPUShaderStage.FRAGMENT, sampler: {} },
      { binding: 1, visibility: GPUShaderStage.FRAGMENT, texture: {} },
    ],
  });

  const pipeline = device.createRenderPipeline({
    layout: device.createPipelineLayout({ bindGroupLayouts: [bindGroupLayout] }),
    vertex: { module: device.createShaderModule({ code: BLIT_VERTEX_WGSL }), entryPoint: 'main' },
    fragment: {
      module: device.createShaderModule({ code: BLIT_FRAGMENT_WGSL }),
      entryPoint: 'main',
      targets: [{ format }],
    },
    primitive: { topology: 'triangle-list' },
  });

  const sampler = device.createSampler({ magFilter: 'linear', minFilter: 'linear' });

  return { bindGroupLayout, pipeline, sampler };
}

function montarBindGroup(device, blit, outputTexture) {
  return device.createBindGroup({
    layout: blit.bindGroupLayout,
    entries: [
      { binding: 0, resource: blit.sampler },
      { binding: 1, resource: outputTexture.createView() },
    ],
  });
}

// Inicia uma sessão de render do pipeline Anime4K sobre `video`/`canvas`,
// já pronta pra apresentar `presetInicial` (objeto de presets.js). Dona do
// GPUDevice/GPUCanvasContext/inputTexture pela vida inteira da sessão — só
// morre em `encerrar()`. `dimensoes` (já calculadas pelo chamador, ver
// calcularDimensoesDaSessao em presets.js) fixam o canvas uma única vez:
// redimensionar reconfigura o swap chain WebGPU, o mesmo custo visual do
// problema que esta reescrita resolve.
//
// Devolve `{ trocarPreset, encerrar, adaptador, medidor }`.
// `trocarPreset(preset)` é síncrono e troca o chain ativo sem recriar
// device/contexto/inputTexture — é isso que elimina a piscada. Falhas:
//  - falha ao CONSTRUIR a sessão inicial (device/contexto/1º chain): chamada
//    rejeita a Promise, chamador trata como fatal.
//  - falha em `trocarPreset` (novo chain não construiu, ex. sem VRAM): o
//    chain anterior CONTINUA rodando, o erro é reportado via `aoFalharTroca`
//    (não fatal — quem chama decide degradar o degrau).
//  - `device.lost` (motivo != 'destroyed') ou `uncapturederror`: sessão
//    inteira morta, reportado via `aoFalharSessao` (fatal — chamador precisa
//    recriar a sessão do zero).
export async function iniciarSessaoDeRender({ video, canvas, dimensoes, presetInicial, aoFalharTroca, aoFalharSessao }) {
  await aguardarFrameDisponivel(video);

  const adapter = await navigator.gpu.requestAdapter();
  if (!adapter) throw new Error('WebGPU indisponível: nenhum GPUAdapter encontrado.');
  const device = await adapter.requestDevice();

  canvas.width = dimensoes.width;
  canvas.height = dimensoes.height;

  const ctx = canvas.getContext('webgpu');
  const format = navigator.gpu.getPreferredCanvasFormat();
  ctx.configure({ device, format, alphaMode: 'premultiplied' });

  const inputTexture = device.createTexture({
    size: [video.videoWidth, video.videoHeight, 1],
    format: 'rgba16float',
    usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST | GPUTextureUsage.RENDER_ATTACHMENT,
  });

  const blit = montarBlit(device, format);

  const medidor = instalarMedidorDeGpu(device);

  dispositivoAtivo = device;

  let sessaoViva = true;

  device.lost.then((info) => {
    if (info.reason === 'destroyed') return; // esperado: foi o nosso próprio destroy() em encerrar()/pagehide
    if (!sessaoViva) return;
    sessaoViva = false;
    aoFalharSessao(new Error(`GPU perdeu o device (${info.reason}): ${info.message}`));
  });
  // Só log: `uncapturederror` não é `device.lost` — o device continua válido,
  // só a operação específica que gerou o erro foi abortada. Tratar como
  // fatal aqui reconstruiria a sessão inteira (a piscada que esta reescrita
  // existe pra eliminar) por um erro que não mata nada.
  device.addEventListener('uncapturederror', (event) => {
    console.error('[Anime4K] WebGPU uncaptured error:', event.error);
  });

  let pipelinesAtivos;
  let bindGroupAtivo;
  try {
    pipelinesAtivos = presetInicial.build()(device, inputTexture);
    bindGroupAtivo = montarBindGroup(device, blit, pipelinesAtivos.at(-1).getOutputTexture());
  } catch (err) {
    // Chain inicial não construiu — sessão inteira não nasce. Limpa o
    // device (medidor primeiro, mesma ordem de encerrar() abaixo) e propaga
    // via rejeição da Promise: quem chama trata igual a qualquer outra falha
    // fatal de construção (useMotorAnime4k não tem sessão nenhuma pra
    // marcar como "morta", só precisa saber que não há sessão).
    medidor.encerrar();
    device.destroy();
    if (dispositivoAtivo === device) dispositivoAtivo = null;
    throw new Error(`Falha ao inicializar WebGPU: ${err.message}`);
  }

  // Devolve true em sucesso, false se o chain novo falhou ao construir —
  // quem chama (useMotorAnime4k) usa o retorno pra decidir se marca este
  // preset como "aplicado" ou tenta de novo numa próxima mudança de estado.
  function trocarPreset(preset) {
    let novosPipelines;
    let novoBindGroup;
    try {
      novosPipelines = preset.build()(device, inputTexture);
      // getOutputTexture()/montarBindGroup ainda podem falhar depois do chain
      // montar — mesmo try, mesma limpeza: nada foi comitado em pipelinesAtivos/
      // bindGroupAtivo ainda, então o chain anterior continua íntegro.
      novoBindGroup = montarBindGroup(device, blit, novosPipelines.at(-1).getOutputTexture());
    } catch (err) {
      // Chain novo não terminou de construir. `preset.build()` (presets.js,
      // montarPipeline) já limpa por conta própria qualquer bloco parcial
      // que tenha alocado textura antes do bloco que falhou — então
      // `novosPipelines` normalmente chega aqui como `undefined` (a
      // atribuição acima nunca completou). O guard abaixo é só um
      // backstop defensivo caso algum `build()` no futuro não passe pelo
      // mesmo caminho de limpeza, ou caso o chain tenha montado mas
      // getOutputTexture()/montarBindGroup tenha falhado depois.
      if (Array.isArray(novosPipelines)) {
        destruirTexturasDoChain(novosPipelines, new Set([inputTexture]));
      }
      aoFalharTroca(new Error(`Falha ao trocar preset: ${err.message}`));
      return false;
    }

    const pipelinesAnteriores = pipelinesAtivos;
    pipelinesAtivos = novosPipelines;
    bindGroupAtivo = novoBindGroup;

    destruirTexturasDoChain(pipelinesAnteriores, new Set([inputTexture]));
    return true;
  }

  let pausado = false;

  function frame() {
    if (pausado) return;
    if (!video.paused) {
      device.queue.copyExternalImageToTexture({ source: video }, { texture: inputTexture }, [video.videoWidth, video.videoHeight]);
    }
    const encoder = device.createCommandEncoder();
    pipelinesAtivos.forEach((p) => p.pass(encoder));
    const renderPass = encoder.beginRenderPass({
      colorAttachments: [
        {
          view: ctx.getCurrentTexture().createView(),
          clearValue: { r: 0, g: 0, b: 0, a: 1 },
          loadOp: 'clear',
          storeOp: 'store',
        },
      ],
    });
    renderPass.setPipeline(blit.pipeline);
    renderPass.setBindGroup(0, bindGroupAtivo);
    renderPass.draw(6);
    renderPass.end();
    device.queue.submit([encoder.finish()]);
    video.requestVideoFrameCallback(frame);
  }
  video.requestVideoFrameCallback(frame);

  function encerrar() {
    sessaoViva = false;
    pausado = true;
    medidor.encerrar(); // antes do destroy: solta o patch de submit e para de coletar
    device.destroy();
    if (dispositivoAtivo === device) dispositivoAtivo = null;
  }

  return { trocarPreset, encerrar, adaptador: adapter, medidor };
}
