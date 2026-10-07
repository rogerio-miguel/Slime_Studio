import { Link } from 'react-router-dom';

// Item de feed que não é pôster (linha de lançamento, chip do ranking): `<Link>`
// de verdade quando o anime já está no catálogo (`anime_id`), botão que
// materializa quando não — mesma regra de `components/AnimeCard.jsx`, sem a
// moldura de card. Ao contrário do card, mantém o anel de foco de teclado: aqui
// não há decisão de design que o tenha removido.
export default function AtivadorDeAnime({
  item,
  aoAtivar,
  desabilitado,
  className,
  children,
  // Handlers/atributos extras (ex. `onMouseEnter` do palco do Top 10).
  ...propsExtras
}) {
  const classes = `${className} outline-none focus-visible:ring-2 focus-visible:ring-neon`;
  if (item.anime_id != null) {
    return (
      <Link to={`/anime/${item.anime_id}`} className={classes} {...propsExtras}>
        {children}
      </Link>
    );
  }
  return (
    <button
      type="button"
      onClick={aoAtivar}
      disabled={desabilitado}
      {...propsExtras}
      className={`${classes} cursor-pointer text-left disabled:cursor-not-allowed disabled:opacity-50`}
    >
      {children}
    </button>
  );
}
