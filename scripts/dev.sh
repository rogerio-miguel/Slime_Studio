#!/usr/bin/env bash
# Liga API + worker (backend) e o servidor de dev do Vite (frontend) numa janela só,
# e abre o frontend numa aba/janela normal do seu Brave (perfil padrão, com todas as
# flags/sessão que você já tem — sem isso o WebGPU do player não inicializa).
# Fechar esta janela de terminal derruba os três processos.
set -uo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
URL_FRONTEND="http://localhost:5173"
PIDS=()

parar() {
    echo
    echo "Encerrando..."
    for pid in "${PIDS[@]}"; do
        pkill -TERM -P "$pid" 2>/dev/null
        kill -TERM "$pid" 2>/dev/null
    done
    wait 2>/dev/null
}
trap parar EXIT INT TERM HUP

esperar_url() {
    local url="$1" tentativas=60
    while ! curl -s -o /dev/null "$url"; do
        tentativas=$((tentativas - 1))
        [ "$tentativas" -le 0 ] && return 1
        sleep 0.5
    done
}

# Garante o lançador "Slime Studio" no menu de aplicativos do GNOME (dá pra fixar na
# barra). Só (re)gera se faltar ou se apontar para outro clone, então rodar de novo é
# barato. O ícone vai embutido aqui para este continuar sendo o único arquivo.
garantir_lancador() {
    command -v gnome-terminal >/dev/null || return 0
    local apps="$HOME/.local/share/applications"
    local icones="$HOME/.local/share/icons/hicolor/scalable/apps"
    local desktop="$apps/slime-studio-dev.desktop"
    grep -qsF "\"$RAIZ/scripts/dev.sh\"" "$desktop" && [ -f "$icones/slime-studio.svg" ] && return 0

    echo "== Instalando o lançador do Slime Studio =="
    mkdir -p "$apps" "$icones"
    # viewBox quadrado: o mascote é 16x11 e o GNOME esticaria a imagem num quadrado.
    cat > "$icones/slime-studio.svg" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -2 16 16" width="256" height="256" shape-rendering="crispEdges">
  <title>Mascote do Slime Studio</title>
  <path fill="#ff7518" d="M6 2h4v1h-4zM4 3h1v1h-1zM7 3h5v1h-5zM3 4h1v1h-1zM7 4h6v1h-6zM2 5h12v1h-12zM2 6h12v1h-12zM2 7h2v1h-2zM6 7h4v1h-4zM12 7h2v1h-2zM2 8h12v1h-12zM2 9h12v1h-12zM3 10h10v1h-10z"/>
  <path fill="#404040" d="M5 0h6v1h-6zM3 1h2v1h-2zM11 1h2v1h-2zM2 2h1v1h-1zM13 2h1v1h-1zM1 3h1v1h-1zM14 3h1v1h-1zM0 4h2v1h-2zM14 4h2v1h-2zM0 5h2v1h-2zM14 5h2v1h-2zM0 6h2v1h-2zM14 6h2v1h-2zM0 7h2v1h-2zM14 7h2v1h-2zM1 8h1v1h-1zM14 8h1v1h-1z"/>
  <path fill="#ffac74" d="M5 3h2v1h-2zM4 4h3v1h-3z"/>
</svg>
SVG
    cat > "$desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Slime Studio
Comment=Liga API, worker e frontend do Slime Studio
Exec=env GDK_BACKEND=x11 gnome-terminal --class=SlimeStudio --title="Slime Studio — dev" -- "$RAIZ/scripts/dev.sh"
Icon=slime-studio
Terminal=false
Categories=Development;
StartupNotify=true
StartupWMClass=SlimeStudio
DESKTOP
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1
    update-desktop-database "$apps" >/dev/null 2>&1
    LANCADOR_CRIADO=1
}
garantir_lancador

# Recém-criado: reabre pelo lançador e sai. Assim a janela já nasce com a classe e o
# ícone do app (rodado de um terminal qualquer, a barra mostraria o ícone do terminal).
# Se o gtk-launch falhar, segue nesta janela mesmo.
if [ "${LANCADOR_CRIADO:-0}" = 1 ] && command -v gtk-launch >/dev/null; then
    if gtk-launch slime-studio-dev >/dev/null 2>&1; then
        echo "Lançador criado — reabrindo o Slime Studio por ele."
        trap - EXIT
        exit 0
    fi
fi

echo "== API (http://127.0.0.1:8000) =="
(cd "$RAIZ/backend" && uv run python -m api) &
PIDS+=("$!")

echo "== Worker =="
(cd "$RAIZ/backend" && uv run python -m worker) &
PIDS+=("$!")

echo "== Frontend (vite dev) =="
(cd "$RAIZ/frontend" && npm run dev) &
PIDS+=("$!")

if esperar_url "$URL_FRONTEND"; then
    echo "== Abrindo $URL_FRONTEND =="
    # Perfil padrão do Brave, sem --new-window: se já tiver uma janela aberta,
    # abre como aba nela; senão abre janela nova — comportamento padrão do
    # Brave ao receber uma URL sem flag de janela. Sem --user-data-dir próprio
    # o processo daqui morre na hora se já existir instância rodando, por isso
    # NÃO entra em PIDS nem em "wait" abaixo (senão a sessão encerraria sozinha
    # em seguida, ou fechar essa aba/janela poderia derrubar o Brave inteiro se
    # ele não estivesse aberto antes). Consequência aceita: fechar a aba do
    # navegador não encerra mais o terminal/processos automaticamente.
    brave-browser-stable "$URL_FRONTEND" >/dev/null 2>&1 &
    disown
else
    echo "Frontend não respondeu em 30s — não abri o navegador" >&2
fi

wait
