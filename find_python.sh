# Sourced by the shell scripts: pick the project's Python interpreter.
# The repo can sit on an NTFS volume that strips exec bits, so an in-repo
# .venv may be unusable — prefer the venv outside it (see README → Setup).
#   $NSE_RS_PY  →  ~/.venvs/nse-rs  →  ./.venv  →  system python3
PY="${NSE_RS_PY:-}"
for _c in "$HOME/.venvs/nse-rs/bin/python" ".venv/bin/python"; do
    if [ -z "$PY" ] && [ -x "$_c" ] && "$_c" -c "" 2>/dev/null; then PY="$_c"; fi
done
[ -n "$PY" ] || PY="$(command -v python3)"
unset _c
