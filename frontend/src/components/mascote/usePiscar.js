import { useEffect, useState } from 'react';

const DURACAO_DA_PISCADA_MS = 120;
const ESPERA_ENTRE_PISCADAS_MS = [3000, 8000];
const ESPERA_ATE_A_PRIMEIRA_PISCADA_MS = [2500, 5000];

const sortearEntre = ([minimo, maximo]) => minimo + Math.random() * (maximo - minimo);

// `true` enquanto o slime está de olhos fechados. Fica parado enquanto `ativo`
// for falso (ícone escondido, movimento reduzido) e só começa depois de
// `atrasoInicialMs`, pra não brigar com a entrada pelo mesmo quadro de repouso.
// O intervalo é sorteado em `setTimeout`, e não em CSS, pra nunca ser o mesmo.
export function usePiscar(ativo, atrasoInicialMs = 0) {
  const [piscando, setPiscando] = useState(false);
  useEffect(() => {
    if (!ativo) return undefined;
    let temporizador;
    const agendarProxima = (espera) => {
      temporizador = setTimeout(() => {
        setPiscando(true);
        temporizador = setTimeout(() => {
          setPiscando(false);
          agendarProxima(sortearEntre(ESPERA_ENTRE_PISCADAS_MS));
        }, DURACAO_DA_PISCADA_MS);
      }, espera);
    };
    agendarProxima(atrasoInicialMs + sortearEntre(ESPERA_ATE_A_PRIMEIRA_PISCADA_MS));
    return () => clearTimeout(temporizador);
  }, [ativo, atrasoInicialMs]);
  return ativo && piscando;
}
