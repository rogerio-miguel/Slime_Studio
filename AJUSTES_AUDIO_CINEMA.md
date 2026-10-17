# Ajustes do Áudio Cinema — guia rápido

Tudo mora em um arquivo só: `frontend/src/player/audioCinema.js`, dentro de
`montarGrafoCinema()`. Edite o número, salve, recarregue a página (Vite faz
hot reload) — não precisa rebuild pra testar em dev. Antes de commitar,
rodar `npm run lint && npm run build` (frontend/).

Unidade dos filtros: `gain.value` é em **dB** (positivo = reforça,
negativo = corta). `frequency.value` é em **Hz**.

## Parâmetros que valem a pena mexer

Os de timbre são constantes no topo do arquivo (`GRAVE_*`, `HARMONICOS_*`,
`PRESENCA_GANHO_DB`, `CINEMA_WET_LEVEL`); o resto está em `montarGrafoCinema()`.

| Quero...                              | Constante / nó                       | Valor atual | Mexa assim |
|----------------------------------------|--------------------------------------|-------------|------------|
| Mais grave / menos grave                | `GRAVE_GANHO_DB` (`bassShelf.gain`)  | `11` (dB)   | O compressor vem ANTES do realce, então o grave extra não "bombeia" o resto; o limitador final (-2 dB) cobre os picos. |
| Onde o grave começa a reforçar          | `GRAVE_FREQ_HZ`                      | `110` (Hz)  | Menor (ex. 80) = só sub/impacto; maior (ex. 130) = mais quente, mas invade voz masculina grave. |
| Grave "sentido" em fone pequeno         | `HARMONICOS_GANHO`                   | `0.4`       | Harmônicos do grave (o ouvido reconstrói a fundamental). `0` desliga; acima de ~0.5 vira "zumbido". |
| Clareza de voz                          | `PRESENCA_GANHO_DB` (3 kHz)          | `2.5` (dB)  | Subir deixa a voz mais à frente; passar de ~4 volta o estridente. |
| Volume geral do modo cinema             | `CINEMA_WET_LEVEL`                   | `1.3`       | Acima de ~1.4 o limitador final passa a trabalhar >2 dB e a distorção começa; prefira subir o grave. |
| Vozes mais "limpas"/menos abafadas      | `mudCut.gain`                        | `-2` (dB)   | Mais negativo (-3, -4) tira "mud" grave-médio. Passar de -4 deixa o som fino. |
| Fone mais "dentro da cabeça" (mono-ish) | `crossL.gain` / `crossR.gain`        | `0.35`      | Subir (0.45-0.5) = mais mistura entre canais. Descer (0.2) = estéreo mais largo. |

## O que evitar mexer sem necessidade

- Ordem da cadeia (compressor → grave → mud → presença): o compressor antes do
  realce é de propósito; trocar a ordem reabre o efeito de abafamento.
- `compressor.attack` (`0.025`): ataque lento preserva o transiente. Deixar
  mais rápido volta a comprimir o ataque; o `limitador.attack` (`0.003`) é o
  que pega pico agudo.
- `subsonic.frequency` (`30`Hz): só corta subgrave inaudível/rumble.
- Filtros do crossfeed (`shelfL`/`shelfR`, `delayL`/`delayR`): controlam
  imagem estéreo pra fone; só mexer por queixa de imagem estéreo, e aí use
  `crossL`/`crossR`.

## Receitas rápidas

- **"Quero ainda mais grave":** `GRAVE_GANHO_DB` pra cima (11 já é o teto recomendado), mais nada.
- **"Tá bom mas baixo":** `CINEMA_WET_LEVEL` até ~1.4; além disso suba o grave.
- **"Voz meio abafada/enterrada":** `PRESENCA_GANHO_DB` pra 3-3.5 ou `mudCut.gain` pra -3.
