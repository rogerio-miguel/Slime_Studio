# Ajustes do Áudio Cinema — guia rápido

Tudo mora em um arquivo só: `frontend/src/player/audioCinema.js`, dentro de
`montarGrafoCinema()`. Edite o número, salve, recarregue a página (Vite faz
hot reload) — não precisa rebuild pra testar em dev. Antes de commitar,
rodar `npm run lint && npm run build` (frontend/).

Unidade dos filtros: `gain.value` é em **dB** (positivo = reforça,
negativo = corta). `frequency.value` é em **Hz**.

## Parâmetros que valem a pena mexer

| Quero...                              | Nó / linha                          | Valor atual | Mexa assim |
|----------------------------------------|--------------------------------------|-------------|------------|
| Mais grave / menos grave                | `bassShelf.gain`                     | `8` (dB)    | Subir até ~10-11 é seguro (compressor+limiter cobrem). Acima disso, o grave começa a "engolir" o resto — ajuste `compressor.threshold` junto (ver abaixo) se acontecer. |
| Onde o grave começa a reforçar          | `bassShelf.frequency`                | `90` (Hz)   | Menor (ex. 70) = só o "grave grave" (impacto, sub); maior (ex. 120) = grave mais presente/quente, mas pode invadir voz masculina grave. |
| Mais agudo / menos agudo                | `trebleShelf.gain`                   | `-5` (dB)   | Mais negativo (ex. -7, -8) = mais macio/abafado. Mais perto de 0 = mais brilho, risco de voltar o estridente. Não passe de 0 sem motivo — foi o que causou a queixa original. |
| A partir de onde corta o agudo          | `trebleShelf.frequency`              | `6000` (Hz) | Menor (ex. 4500-5000) = corta mais cedo, som mais "fechado"/quente. Maior (ex. 7500-8000) = mantém mais brilho, corta só o extremo. |
| Volume geral do modo cinema             | `CINEMA_WET_LEVEL` (topo do arquivo) | `1.5`       | Sobe volume percebido de tudo (grave e agudo já tratados) igualmente. Se for aumentar bastante (>1.8), teste com trecho bem alto — o `limiter` protege de estouro, mas em excesso ele começa a "espremer" audivelmente. |
| Vozes mais "limpas"/menos abafadas      | `mudCut.gain`                        | `-2` (dB)   | Mais negativo (ex. -3, -4) = tira mais "mud" grave-médio, voz mais clara. Passar de -4 pode deixar o som fino. |
| Fone mais "dentro da cabeça" (mono-ish) | `crossL.gain` / `crossR.gain`        | `0.35`      | Subir (ex. 0.45-0.5) = mais mistura entre canais, som mais central/menos "extremo". Descer (ex. 0.2) = estéreo mais largo/separado. |

## O que evitar mexer sem necessidade

- `compressor.attack` (`0.004`) e `limiter.attack` (`0.002`): já ajustados pra
  pegar transiente agudo rápido. Deixar mais lento (subir o valor) reabre a
  brecha que causava o agudo estourado.
- `subsonic.frequency` (`30`Hz): só corta subgrave inaudível/rumble. Sem
  motivo pra tocar.
- Filtros do crossfeed (`shelfL`/`shelfR`, `delayL`/`delayR`): controlam
  imagem estéreo pra fone, não têm relação com o problema de agudo/grave já
  resolvido — só mexer se a queixa for especificamente sobre imagem estéreo
  (som "de dentro da cabeça" demais ou de menos), aí use `crossL`/`crossR`
  acima em vez destes.

## Receitas rápidas

- **"Quero ainda mais grave, sem perder o resto":** só `bassShelf.gain` pra
  cima (9-10), mais nada.
- **"Ainda incomoda um pouco no agudo":** `trebleShelf.gain` mais negativo
  (-6 ou -7) antes de mexer em qualquer outra coisa.
- **"Tá bom mas baixo":** `CINEMA_WET_LEVEL` pra 1.6-1.7, não mexer no resto.
- **"Voz meio abafada/enterrada":** `mudCut.gain` pra -3.
