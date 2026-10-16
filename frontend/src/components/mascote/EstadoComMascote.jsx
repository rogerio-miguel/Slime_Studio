import MascoteSlime from './MascoteSlime';

// Estado sem conteúdo com o slime caído: lista vazia, busca sem resultado e erro
// ao carregar (pedido do usuário, 2026-10-15: o mesmo slime pros três, só muda a
// mensagem). `alerta` anuncia a mensagem na hora (`role="alert"`, pra erro); sem
// ele é `status`. O slime é decorativo. `children` é a ação opcional (ex.
// "Limpar filtros", "Tentar novamente").
export default function EstadoComMascote({ mensagem, alerta = false, compacto = false, children }) {
  return (
    <div
      role={alerta ? 'alert' : 'status'}
      className={`flex flex-col items-center gap-4 text-center ${compacto ? 'py-10' : 'py-24'}`}
    >
      <MascoteSlime pose="vazio" />
      <p className="text-base font-semibold text-ink-muted">{mensagem}</p>
      {children}
    </div>
  );
}
