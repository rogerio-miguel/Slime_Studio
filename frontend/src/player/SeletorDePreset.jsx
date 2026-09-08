import { PRESETS, ESCADA_DE_DEGRADACAO } from './presets.js';

// Presets que não entram na escada manual (mudam o *look* da imagem, não só
// o custo), mas ainda selecionáveis — ESPECIFICACAO.md §11.3 descreve
// `aa-vl-denoise` como um "knob para fontes com grão".
const PRESETS_EXTRA = ['aa-vl-denoise'];

// <select> embutido na barra de controles — troca de qualidade em runtime.
// "Automático" (valor 'auto') liga a degradação adaptativa; os demais fixam
// um preset na mão. Optgroup "Presets" ordenado por ESCADA_DE_DEGRADACAO (do
// mais pesado/melhor ao mais leve), não pela ordem de declaração em PRESETS.
export default function SeletorDePreset({ presetAtual, aoTrocar }) {
  return (
    <select
      value={presetAtual}
      onChange={(event) => aoTrocar(event.target.value)}
      aria-label="Qualidade do upscaling"
      className="rounded-md border border-border-chrome bg-[#222] px-2 py-1.5 text-sm text-white hover:bg-[#2a2a2a] focus-visible:outline focus-visible:outline-2 focus-visible:outline-white focus-visible:outline-offset-2"
    >
      <optgroup label="Adaptativo">
        <option value="auto">Automático (ajusta à GPU)</option>
      </optgroup>
      <optgroup label="Presets">
        {ESCADA_DE_DEGRADACAO.map((id) => (
          <option key={id} value={id}>
            {PRESETS[id].label}
          </option>
        ))}
      </optgroup>
      <optgroup label="Extra">
        {PRESETS_EXTRA.map((id) => (
          <option key={id} value={id}>
            {PRESETS[id].label}
          </option>
        ))}
      </optgroup>
    </select>
  );
}
