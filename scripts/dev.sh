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
