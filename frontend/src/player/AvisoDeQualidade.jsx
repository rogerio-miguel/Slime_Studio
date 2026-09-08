import { useEffect, useState } from 'react';

// NÃO montado no momento (a pedido do usuário — as trocas automáticas são
// frequentes o bastante pra que o aviso incomode mais do que informe).
// Mantido pronto: reintroduzir = voltar a renderizar <AvisoDeQualidade> em
// PlayerAtivo.jsx passando `ultimaTroca` de useControleAdaptativo.

function montarTexto(troca, label) {
  if (troca.direcao === 'cima') return `Qualidade restaurada: ${label}`;
  if (troca.motivo === 'gpu') return `GPU sobrecarregada — qualidade reduzida: ${label}`;
  return `Qualidade reduzida para manter a fluidez: ${label}`;
}

// Aviso efêmero quando a degradação automática troca de degrau. Vive dentro
// do .frame (não no Shell como Toasts.jsx, que é acoplado a jobs de captura e
// fica fora do fullscreen). role=status + aria-live: anuncia a troca pro
// leitor de tela sem roubar foco dos controles do player. Sem animação — não
// precisa de guarda de prefers-reduced-motion.
export default function AvisoDeQualidade({ ultimaTroca, label }) {
  const [visivel, setVisivel] = useState(false);

  // Deps em `ultimaTroca` (identidade nova a cada troca, ver useControleAdaptativo).
  useEffect(() => {
    if (!ultimaTroca) return;
    setVisivel(true);
    const id = setTimeout(() => setVisivel(false), 4000);
    return () => clearTimeout(id);
  }, [ultimaTroca]);

  if (!visivel || !ultimaTroca) return null;

  const texto = montarTexto(ultimaTroca, label);

  return (
    <div
      role="status"
      aria-live="polite"
      className="absolute bottom-20 left-4 rounded-lg border border-border-chrome bg-black/70 px-4 py-2 text-sm text-white pointer-events-none"
    >
      {texto}
    </div>
  );
}
