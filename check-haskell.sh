#!/usr/bin/env bash

# check-haskell.sh
#
# Roda cada .hs em ./full-code (procurando em subpastas também, tipo
# full-code/Huffman e full-code/AbsTypes) pelo GHC, só pra typecheck, e
# junta tudo num log só em ghc-errors.log na raiz do repo.
#
# Um arquivo sem "module ... where" (pensado só pra ':load' interativo,
# sem 'main') faz o GHC reclamar "main não definido" mesmo sem ter
# problema nenhum de verdade. Esse script reconhece esse caso
# específico e não conta como erro (só quando ELE é o único problema;
# se tiver qualquer outro erro real junto, continua contando como
# quebrado).

set -uo pipefail

ROOT="."
CODE_DIR="${1:-$ROOT/full-code}"
OUT="$ROOT/ghc-errors.log"
OUTDIR="$ROOT/.ghc-check-tmp"

command -v ghc >/dev/null 2>&1 || {
    echo "ghc não encontrado no PATH." >&2
    exit 1
}

[ -d "$CODE_DIR" ] || {
    echo "Não achei $CODE_DIR. Roda ./fetch.sh primeiro." >&2
    exit 1
}

mkdir -p "$OUTDIR"
: > "$OUT"

files=()
while IFS= read -r -d '' f; do
    files+=("$f")
done < <(find "$CODE_DIR" -name '*.hs' -print0 | sort -z)

if [ ${#files[@]} -eq 0 ]; then
    echo "Nenhum .hs encontrado em $CODE_DIR" >&2
    exit 1
fi

ok=()
bad=()
declare -A bad_reason

for f in "${files[@]}"; do
    d="$(dirname "$f")"
    rel="${f#"$ROOT"/}"
    echo "==================== $rel ====================" >> "$OUT"

    # Ordem importa: "$d" (a própria pasta do arquivo) tem que vir primeiro,
    # senão nomes de módulo repetidos entre pastas (Store, Types, ParseLib,
    # MonadIO existem tanto em AbsTypes/ quanto em Calculator/Huffman/IO/
    # Parsing/) resolvem pro vizinho errado. "$CODE_DIR/AbsTypes" entra como
    # fallback só pro Chapter17.hs (único arquivo de nivel raiz que importa
    # Set/Relation, que só existem dentro de AbsTypes/).
    #
    # Caso especial: pra um arquivo de nivel raiz (Chapter*.hs, Pictures.hs)
    # "$d" É "$CODE_DIR" (mesma pasta) - se botássemos os dois, "$d" empataria
    # e "ganharia" na frente de AbsTypes, e aí o full-code/ raiz (que tem
    # Set.lhs/Relation.lhs, versões .lhs não corrigidas, só pra tipografia
    # do livro) resolveria primeiro que full-code/AbsTypes/Set.hs de verdade.
    # Por isso omitimos "$d" nesse caso e deixamos AbsTypes vir logo depois
    # de "$CODE_DIR/AbsTypes" na frente do "$CODE_DIR" puro.
    if [ "$d" = "$CODE_DIR" ]; then
        iflags=(-i"$CODE_DIR/AbsTypes" -i"$CODE_DIR" -i"$ROOT")
    else
        iflags=(-i"$d" -i"$CODE_DIR/AbsTypes" -i"$CODE_DIR" -i"$ROOT")
    fi

    output="$(ghc -fno-code -v0 "${iflags[@]}" -outputdir "$OUTDIR" "$f" 2>&1)"
    status=$?
    echo "$output" >> "$OUT"

    total_errors=$(grep -c ': error' <<< "$output")
    benign_errors=$(grep -c 'is not defined in module' <<< "$output")

    if [ "$status" -eq 0 ]; then
        echo "(ok, sem erros)" >> "$OUT"
        ok+=("$rel")
    elif [ "$total_errors" -gt 0 ] && [ "$total_errors" -eq "$benign_errors" ]; then
        echo "(ok - só falta 'main', normal em arquivo pensado pra :load interativo)" >> "$OUT"
        ok+=("$rel")
    else
        bad+=("$rel")
        # motivo: a linha logo apos a primeira ": error" no output
        # (a primeira linha so tem o codigo [GHC-XXXXX], a descricao
        # de verdade vem na linha seguinte)
        reason="$(grep -m1 -A1 ': error' <<< "$output" | tail -n1 | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        bad_reason["$rel"]="${reason:-erro desconhecido, ver log}"
    fi
    echo >> "$OUT"
done

{
    echo "===================================================="
    echo "RESUMO"
    echo "OK (${#ok[@]}):"
    for f in "${ok[@]}"; do
        echo "    $f"
    done
    echo "ERRO (${#bad[@]}):"
    for f in "${bad[@]}"; do
        echo "    $f -> ${bad_reason[$f]}"
    done
} >> "$OUT"

rm -rf "$OUTDIR"

echo "Log salvo em: $OUT"
echo
echo "OK (${#ok[@]}):"
for f in "${ok[@]}"; do
    echo "    $f"
done
echo "ERRO (${#bad[@]}):"
for f in "${bad[@]}"; do
    echo "    $f -> ${bad_reason[$f]}"
done
