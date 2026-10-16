import { useEffect, useState } from 'react';

// Nenhuma piscada dura igual à outra. Um quadro de meio-fechado entre aberto e
// fechado foi tentado e tirado a pedido (o olho virava um pixel).
const DURACAO_DA_PISCADA_MS = [90, 150];
const CHANCE_DE_PISCADA_DUPLA = 0.08;
const RESPIRO_DA_PISCADA_DUPLA_MS = [90, 180];
const ESPERA_ENTRE_PISCADAS_MS = [2500, 9500];
const ESPERA_ATE_A_PRIMEIRA_PISCADA_MS = [2500, 5000];

const sortearEntre = ([minimo, maximo]) => minimo + Math.random() * (maximo - minimo);
// O quadrado do sorteio empurra a maioria das esperas pro lado curto, com uma
// longa de vez em quando: um intervalo uniforme dá um ritmo que o olho percebe.
const sortearComMaisCurtas = ([minimo, maximo]) => minimo + Math.random() ** 2 * (maximo - minimo);

// `true` enquanto o slime está de olhos fechados. Fica parado enquanto `ativo`
// for falso (ícone escondido, movimento reduzido) e só começa depois de
// `atrasoInicialMs`, pra não brigar com a entrada pelo mesmo quadro de repouso.
// Os tempos são sorteados em `setTimeout`, e não em CSS, pra nunca serem os
// mesmos. Raramente (8%) pisca duas vezes seguidas, com um respiro curto.
export function usePiscar(ativo, atrasoInicialMs = 0) {
  const [piscando, setPiscando] = useState(false);
  useEffect(() => {
    if (!ativo) return undefined;
    let temporizador;
    const piscarUmaVez = (aoTerminar) => {
      setPiscando(true);
      temporizador = setTimeout(() => {
        setPiscando(false);
        aoTerminar();
      }, sortearEntre(DURACAO_DA_PISCADA_MS));
    };
    const agendarProxima = (espera) => {
      temporizador = setTimeout(() => {
        piscarUmaVez(() => {
          const proximaEspera = () => agendarProxima(sortearComMaisCurtas(ESPERA_ENTRE_PISCADAS_MS));
          if (Math.random() >= CHANCE_DE_PISCADA_DUPLA) {
            proximaEspera();
            return;
          }
          temporizador = setTimeout(
            () => piscarUmaVez(proximaEspera),
            sortearEntre(RESPIRO_DA_PISCADA_DUPLA_MS),
          );
        });
      }, espera);
    };
    agendarProxima(atrasoInicialMs + sortearEntre(ESPERA_ATE_A_PRIMEIRA_PISCADA_MS));
    return () => clearTimeout(temporizador);
  }, [ativo, atrasoInicialMs]);
  return ativo && piscando;
}
