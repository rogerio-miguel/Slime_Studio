import { PRESETS, ESCADA_DE_DEGRADACAO } from './presets.js';

// Presets fora da escada automática de degradação (custo de GPU não
// justifica entrar no fallback por telemetria), mas ainda selecionáveis
// manualmente — ESPECIFICACAO.md §11.3 descreve `aa-vl-denoise` como um
// "knob para fontes com grão".
const PRESETS_EXTRA = ['aa-vl-denoise'];

// Substitui o hub de cards do protótipo (teste/index.html) por um <select>
// embutido na barra de controles — troca de preset em runtime, não
// navegação entre páginas. Primeiro optgroup ordenado por
// ESCADA_DE_DEGRADACAO (do preset mais pesado/melhor qualidade ao mais
// leve), não pela ordem de declaração em PRESETS; segundo optgroup lista os
// presets fora da escada (PRESETS_EXTRA) separadamente, pra não confundir
// com a ordem de fallback automático.
export default function SeletorDePreset({ presetAtual, aoTrocar }) {
  return (
    <select
      value={presetAtual}
      onChange={(event) => aoTrocar(event.target.value)}
      aria-label="Preset de upscaling"
      className="rounded-md border border-border-chrome bg-[#222] px-2 py-1.5 text-sm text-white hover:bg-[#2a2a2a] focus-visible:outline focus-visible:outline-2 focus-visible:outline-white focus-visible:outline-offset-2"
    >
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
