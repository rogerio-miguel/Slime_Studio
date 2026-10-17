// HUD de telemetria — overlay somente leitura sobre o vídeo. Posicionamento
// não é load-bearing o bastante pra justificar CSS próprio (D5): Tailwind +
// os tokens de cor "verde HUD" definidos em index.css (@theme).
function Linha({ rotulo, valor }) {
  return (
    <div className="whitespace-nowrap">
      <span className="mr-1.5 text-hud-dim">{rotulo}</span>
      <span className="text-white">{valor}</span>
    </div>
  );
}

export default function HudTelemetria({ visivel, modo, presetLabel, resolucao, telemetria, diagnostico, passes }) {
  if (!visivel) return null;

  const { cadenciaMs, dropped, total, gpu } = telemetria;
  const fpsApr = diagnostico?.fpsApresentacao;
  const fpsCont = diagnostico?.fpsConteudo;

  return (
    <div
      role="status"
      className="absolute top-2 right-2 rounded-md border border-border-chrome bg-black/70 px-3 py-2 text-[0.78rem] leading-relaxed text-hud-bright [font-variant-numeric:tabular-nums] pointer-events-none"
    >
      <Linha rotulo="modo" valor={modo} />
      <Linha rotulo="preset" valor={presetLabel} />
      <Linha rotulo="canvas" valor={resolucao} />
      <Linha
        rotulo="frame a cada"
        valor={cadenciaMs !== null ? `${cadenciaMs.toFixed(1)} ms (cadência, não custo de GPU)` : '—'}
      />
      <Linha rotulo="dropped/total" valor={dropped !== null ? `${dropped} / ${total}` : '—'} />
      {diagnostico && (
        <>
          <Linha
            rotulo="fps apr/conteúdo"
            valor={
              fpsApr != null
                ? `${fpsApr.toFixed(0)} / ${fpsCont != null ? fpsCont.toFixed(0) : '…'} · ${passes} passes`
                : `— · ${passes} passes`
            }
          />
          <Linha
            rotulo="pressão (3s)"
            valor={
              diagnostico.pressaoNaJanela !== null
                ? `${(diagnostico.pressaoNaJanela * 100).toFixed(0)} %`
                : '—'
            }
          />
          <Linha rotulo="estado" valor={diagnostico.estado} />
        </>
      )}
      <Linha rotulo="gpu" valor={gpu} />
    </div>
  );
}
