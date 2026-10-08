import { ConteudoDaSinopse } from '../SinopseNaIlha.jsx';

// Região que a cápsula ganha ao crescer para baixo e virar o painel da sinopse.
// O contêiner é um `grid` e a altura anima por `grid-template-rows: 0fr -> 1fr`
// (hooks/useSinopseNaCapsula.js cuida das fases e da geometria).
// Sinopse completa. `role="dialog"` à mão (sem <dialog> nativo): o hook cuida de
// foco, Esc e Tab. Qualquer clique fecha, menos com texto selecionado (senão
// copiar um trecho fecharia o painel). Com barra de rolagem o texto ocupa a
// largura que sobra; sem ela, largura fixa para não reflowar no crescimento.
export default function RegiaoDaSinopse({ painel, sinopse }) {
  return (
    <div
      className="grid"
      style={{
        gridTemplateRows: painel.expandida ? '1fr' : '0fr',
        ...painel.estiloGrade,
      }}
    >
      <div
        ref={painel.regiaoRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="titulo-sinopse-ilha"
        tabIndex={-1}
        data-visivel={painel.expandida ? '' : undefined}
        data-rolavel={painel.rolavel ? '' : undefined}
        onClick={() => {
          if (window.getSelection()?.toString() === '') painel.fechar();
        }}
        style={{ maxHeight: 'calc(100dvh - 3rem)' }}
        className="sinopse-ilha-conteudo cursor-pointer text-left text-white outline-none"
      >
        <div style={{ width: painel.rolavel ? undefined : painel.larguraConteudo }}>
          <ConteudoDaSinopse
            titulo={sinopse?.titulo ?? ''}
            tituloSecundario={sinopse?.tituloSecundario}
            sinopse={sinopse?.texto}
          />
        </div>
      </div>
    </div>
  );
}
