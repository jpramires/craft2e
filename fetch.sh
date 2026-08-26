#!/usr/bin/env bash

# fetch.sh
#
# Baixa o pacote oficial e **completo** de código do livro (2ª edição),
# direto do site do autor no Kent, e desempacota em "./full-code" na raiz
# do repositório. NÃO usa o zip da pasta "helium/" (ver README.md seção
# "Code/ vs helium/" pra entender a diferença).
#
# Roda de novo a qualquer momento pra resetar ./code pro estado
# original, sem nenhum dos nossos patches. Por isso ./code fica de fora
# do git (.gitignore) e nao mora nada nosso dentro dela.

set -uo pipefail

ROOT="."
URL="https://www.cs.kent.ac.uk/people/staff/sjt/craft2e/Code/Code.tar.gz"
DEST="$ROOT/full-code"
TMP="/tmp/craft2e-code.tar.gz"

command -v curl >/dev/null 2>&1 || { echo "curl não instalado." >&2; exit 1; }

echo
echo "Baixando $URL ..."
curl -fsSL "$URL" -o "$TMP" || { echo "Download falhou." >&2; exit 1; }

rm -rf "$DEST"
mkdir -p "$DEST"

echo "Descompactando em $DEST ..."
tar -xzf "$TMP" -C "$DEST" --strip-components=1

n=$(find "$DEST" -name '*.hs' | wc -l)
echo "Pronto: $n arquivos .hs em $DEST"
echo
