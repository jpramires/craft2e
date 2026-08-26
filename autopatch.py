#!/usr/bin/env python3

"""
autopatch.py

Lê `ghc-errors.log` (gerado pelo `check-haskell.sh`) e aplica os
patches conhecidos pra cada categoria de erro que foi identificada.

Idempotente: rodar de novo em cima de arquivos já corrigidos não
sobrescreve nem duplica nada, pra evitar maiores dores de cabeça.

Uso:
    python3 autopatch.py               (usa ./ghc-errors.log)
    python3 autopatch.py outro.log

Categorias tratadas:
  1. Nome antigo do Hugs faltando (OldPrelude)              -> insere "import OldPrelude"
  2. Nome do usuário ambíguo com algo importado (Word,
     isEOF...)                                              -> insere/estende
                                                                 "import <Módulo> hiding (...)"
                                                                 (descobre sozinho qual módulo:
                                                                 Prelude, System.IO, etc.)
  3. Nome de módulo antigo (IO, List, ...)                  -> troca pro nome atual
                                                                 (System.IO, Data.List, ...)
  4. Monad sem Functor/Applicative (pré-AMP)                -> adiciona as duas instances
                                                                 via liftM/ap
  5. Correções pontuais (Bee.hs/ParseLib.hs, hugsIsEOF)     -> ver EXACT_PATCHES

O que NÃO é tratado aqui (não dá pra automatizar com segurança, ou não
vale a pena): warnings (-Wtabs, -Wx-partial, -Wunrecognised-pragmas,
-Woverlapping-patterns) e o falso positivo de "main não definido" em
arquivo sem main - esse último o `check-haskell.sh` já sabe ignorar
sozinho.
"""

import re
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.text import Text

console = Console()
console_err = Console(stderr=True)


# Helpers de output colorido (rich). Usamos rich.Text em vez de markup tags
# (console.print("[green]...[/]")) de propósito: nossas mensagens já usam
# "[+]"/"[*]" como prefixo literal, e o parser de markup do rich tentaria
# interpretar esses colchetes como tag de estilo e quebraria.
def say_ok(prefix, rest):
    """Verde: patch aplicado com sucesso."""
    t = Text(prefix, style="bold green")
    t.append(rest)
    console.print(t)


def say_skip(prefix, rest):
    """Amarelo: idempotente, já tava corrigido - nada a fazer."""
    t = Text(prefix, style="bold yellow")
    t.append(rest, style="yellow")
    console.print(t)


def say_warn(prefix, rest):
    """Amarelo (stderr): precisa de atenção manual (ex: sem 'module ... where')."""
    t = Text(prefix, style="bold yellow")
    t.append(rest, style="yellow")
    console_err.print(t)


def say_err(prefix, rest):
    """Vermelho (stderr): falhou de vez (ex: arquivo não existe)."""
    t = Text(prefix, style="bold red")
    t.append(rest, style="red")
    console_err.print(t)


def say_info(msg):
    """Ciano: informativo, sem indicar sucesso/falha."""
    console.print(Text(msg, style="cyan"))


# Este script assume que mora na raiz do repo (mesma pasta do
# OldPrelude.hs, do .ghci e do full-code/). Se você o moveu pra uma
# subpasta (ex: scripts/), ajuste esta linha pra apontar pra raiz.
ROOT = Path(__file__).resolve().parent

# Nomes que o OldPrelude.hs reexporta. Se aparecer "Variable not in
# scope" pra um desses, o arquivo precisa de "import OldPrelude".
OLDPRELUDE_NAMES = {
    "eqChar",
    "eqString",
    "eqInt",
    "eqList",
    "eqTuple2",
    "eqTuple3",
    "ordChar",
    "ordString",
    "ordInt",
    "ordList",
    "ordTuple2",
    "fromInt",
    "showInt",
    "readInt",
    "ord",
    "chr",
    "isDigit",
    "isAlpha",
    "isSpace",
    "isUpper",
    "isLower",
    "toUpper",
    "toLower",
    "+.",
    "-.",
    "*.",
    "/.",
    "==.",
    "/=.",
    "<.",
    "<=.",
    ">.",
    ">=.",
}

# Módulos "planos" pré-Haskell 2010 que viraram hierárquicos. Sempre
# que "Could not find module 'X'" bater com uma chave aqui, trocamos
# "import X" pelo valor correspondente (preservando o resto da linha,
# tipo comentário depois do import).
OLD_MODULE_RENAMES = {
    "IO": "System.IO",
    "List": "Data.List",
    "Char": "Data.Char",
    "Maybe": "Data.Maybe",
    "Array": "Data.Array",
    "Ratio": "Data.Ratio",
    "Complex": "Data.Complex",
    "Ix": "Data.Ix",
}


def find_header_end(lines):
    """Acha o índice da linha logo após o fim do cabeçalho
    'module Nome (...) where', mesmo quando a lista de exports ocupa
    várias linhas.

    Alguns arquivos do livro (ex: IO/TreeId.hs, IO/TreeState.hs) não têm
    'module ... where' nenhum - são pensados só pra ':load' interativo,
    então o arquivo inteiro é implicitamente 'Main'. Nesse caso, cai pro
    fallback: insere logo após o último import "solto" no topo do arquivo
    (pulando comentários/linhas em branco antes dele), ou antes da primeira
    linha de código de verdade se não houver import nenhum. Import em
    Haskell não pode vir depois de uma declaração, então não dá pra só
    jogar no início do arquivo quando já existe algum import lá."""
    module_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^module\b", line):
            module_idx = i
            break
    if module_idx is not None:
        for i in range(module_idx, len(lines)):
            if re.search(r"\bwhere\b", lines[i]):
                return i + 1
        return None

    insert_at = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(("--", "import ")):
            insert_at = i + 1
            continue
        break
    return insert_at


def _find_matching_paren(s, open_idx):
    """Índice do ')' que fecha o '(' em s[open_idx], contando parênteses
    aninhados. Precisamos disso porque uma hiding-list pode conter nomes
    de operador entre parênteses (ex: '(++)', '(>>=)'), e um regex tipo
    '\\(([^)]*)\\)' para no primeiro ')' que encontrar - exatamente o
    ')' de dentro de '(++)' - e corrompe a linha."""
    depth = 0
    for i in range(open_idx, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_hiding_names(s):
    """Separa o conteúdo de uma hiding-list em nomes, nas vírgulas de
    nível 0 (ignora vírgula/parênteses dentro de um nome de operador
    tipo '(++)')."""
    names, depth, current = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
            current += ch
        elif ch == ")":
            depth -= 1
            current += ch
        elif ch == "," and depth == 0:
            if current.strip():
                names.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        names.append(current.strip())
    return names


def ensure_line_after_header(lines, wanted_line):
    """Garante que 'wanted_line' exista logo após o cabeçalho do
    módulo. Não duplica se já existir em qualquer lugar do arquivo."""
    if any(line.rstrip("\n") == wanted_line for line in lines):
        return lines, False
    idx = find_header_end(lines)
    if idx is None:
        return lines, "no_module"
    lines = lines[:idx] + [wanted_line + "\n"] + lines[idx:]
    return lines, True


def ensure_hiding(lines, module, names):
    """Garante 'import <module> hiding (a, b, ...)' cobrindo 'names'.

    Três casos, nessa ordem:
      1. Já existe 'import <module> hiding (...)' -> estende a lista.
      2. Já existe 'import <module>' simples (sem hiding, sem lista
         explícita) -> REESCREVE essa linha adicionando hiding. Não
         basta inserir uma linha nova ao lado: um import simples do
         mesmo módulo continua trazendo o nome ambíguo pro escopo
         mesmo com outro import hiding-only presente.
      3. Não tem import nenhum desse módulo ainda -> insere logo após
         o cabeçalho.
    """
    hiding_prefix_re = re.compile(r"^import " + re.escape(module) + r" hiding \(")
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        pm = hiding_prefix_re.match(stripped)
        if not pm:
            continue
        open_idx = pm.end() - 1
        close_idx = _find_matching_paren(stripped, open_idx)
        if close_idx == -1:
            continue  # parenteses desbalanceados, não mexe
        existing = set(_split_hiding_names(stripped[open_idx + 1 : close_idx]))
        merged = existing | names
        if merged == existing:
            return lines, False
        lines[i] = (
            f"import {module} hiding ({', '.join(sorted(merged))}){stripped[close_idx + 1 :]}\n"
        )
        return lines, True

    bare_re = re.compile(r"^import " + re.escape(module) + r"\b(.*)$")
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        m = bare_re.match(stripped)
        if not m:
            continue
        rest = m.group(1)
        code_rest, _, comment = rest.partition("--")
        if "(" in code_rest:
            # tem lista explícita de import ou já é outra coisa; não
            # mexe, deixa cair pro caso 3 (linha nova hiding-only)
            continue
        new_line = f"import {module} hiding ({', '.join(sorted(names))})"
        if comment:
            new_line += f"  --{comment}"
        lines[i] = new_line + "\n"
        return lines, True

    idx = find_header_end(lines)
    if idx is None:
        return lines, "no_module"
    new_line = f"import {module} hiding ({', '.join(sorted(names))})\n"
    lines = lines[:idx] + [new_line] + lines[idx:]
    return lines, True


def fix_old_module(text, old_name, new_name):
    new_text, n = re.subn(
        r"^import " + re.escape(old_name) + r"\b",
        "import " + new_name,
        text,
        flags=re.MULTILINE,
    )
    return new_text, n > 0


def ensure_applicative(lines, type_name):
    """Acrescenta 'import Control.Monad (liftM, ap)' e as instances
    Functor/Applicative pro tipo, via liftM/ap (deriva do Monad já
    existente, sem precisar saber a representação interna do tipo)."""
    changed = False
    import_line = "import Control.Monad (liftM, ap)\n"
    if import_line not in lines:
        idx = find_header_end(lines)
        if idx is None:
            return lines, "no_module"
        lines = lines[:idx] + [import_line] + lines[idx:]
        changed = True

    marker = f"instance Functor {type_name} where"
    if marker not in "".join(lines):
        block = (
            f"\ninstance Functor {type_name} where\n"
            f"  fmap = liftM\n"
            f"\ninstance Applicative {type_name} where\n"
            f"  pure  = return\n"
            f"  (<*>) = ap\n"
        )
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(block)
        changed = True

    return lines, changed


def fix_tabs():
    """Troca tab por espaço (até o próximo tab-stop de 8) em todo .hs
    em full-code/. Silencia o -Wtabs de vez; percorre com pathlib em
    vez de depender de glob recursivo do shell (o famoso globstar)."""
    changed = []
    for path in (ROOT / "full-code").rglob("*.hs"):
        text = path.read_text(encoding="utf-8")
        if "\t" not in text:
            continue
        path.write_text(text.expandtabs(8), encoding="utf-8")
        changed.append(path)
    if changed:
        say_info(f"[+] tabs -> espaços em {len(changed)} arquivo(s)")


# --- patches pontuais (cf. README.md pra detalhes) ---


def fix_bee(text):
    pattern = re.compile(
        r"import Ant hiding \(\s*anteater\s*\)\s*\n\s*renaming\s*\(\s*aardvark to honeyEater\s*\)\n?"
    )
    if not pattern.search(text):
        return text, False
    text = pattern.sub(
        "import Ant hiding (anteater)\nimport qualified Ant\n\nhoneyEater = Ant.aardvark\n",
        text,
        count=1,
    )
    return text, True


def fix_nplusk(text):
    old = "nTimes (n+1) p = (p >*> nTimes n p) `build` (uncurry (:))"
    new = "nTimes n     p = (p >*> nTimes (n-1) p) `build` (uncurry (:))"
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True


def fix_hugs_iseof(text):
    """`hugsIsEOF` era um primop específico de GHC/Hugs de 1999 que não
    existe mais; o `isEOF` de verdade (System.IO) hoje funciona direito
    (o problema que o livro contornava não existe mais), então a
    reimplementação do livro (que 'hiding'ava o isEOF de verdade só
    pra poder redefinir com hugsIsEOF) ficou obsoleta. Remove a
    redefinição e devolve o isEOF real (tira do hiding)."""
    lines = text.splitlines(keepends=True)
    changed = False

    filtered = [ln for ln in lines if not re.match(r"^isEOF\s*=\s*hugsIsEOF\b", ln)]
    if len(filtered) != len(lines):
        lines = filtered
        changed = True

    prefix_re = re.compile(r"^import System\.IO hiding \(")
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        m = prefix_re.match(stripped)
        if not m:
            continue
        open_idx = m.end() - 1
        close_idx = _find_matching_paren(stripped, open_idx)
        if close_idx == -1:
            continue
        names = [
            n
            for n in _split_hiding_names(stripped[open_idx + 1 : close_idx])
            if n != "isEOF"
        ]
        rest = stripped[close_idx + 1 :]
        lines[i] = (
            f"import System.IO hiding ({', '.join(names)}){rest}\n"
            if names
            else f"import System.IO{rest}\n"
        )
        changed = True
        break

    return "".join(lines), changed


EXACT_PATCHES = [
    ("parse error on input ‘renaming’", fix_bee),
    ("Parse error in pattern: n + 1", fix_nplusk),
    ("Variable not in scope: hugsIsEOF", fix_hugs_iseof),
]


# --- leitura e classificação do log -----------------------------------


def split_blocks(log_text):
    # O check-haskell.sh gruda um RESUMO no final do mesmo arquivo (contando
    # "Could not find module", "No instance for Applicative" etc. de TODOS
    # os arquivos quebrados, em forma de texto livre). Sem cortar isso fora
    # antes de procurar os headers, esse texto vira parte do ÚLTIMO bloco
    # (o de qualquer erro/warning que por acaso apareça por último no log) e
    # contamina a classificação desse arquivo com todo tipo de "correção"
    # que não tem nada a ver com ele.
    resumo_re = re.compile(r"^=+\nRESUMO\n", re.MULTILINE)
    m = resumo_re.search(log_text)
    if m:
        log_text = log_text[: m.start()]

    header_re = re.compile(
        r"^(?P<path>\S+):(?P<line>\d+):(?P<col>\d+): (error|warning):.*$", re.MULTILINE
    )
    headers = list(header_re.finditer(log_text))
    blocks = []
    for i, h in enumerate(headers):
        start = h.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(log_text)
        blocks.append((h.group("path"), log_text[start:end]))
    return blocks


def classify(blocks):
    plan = {}  # path -> dict de acoes

    def entry(path):
        return plan.setdefault(
            path,
            {
                "oldprelude": False,
                "hiding": {},  # modulo -> set de nomes
                "old_modules": set(),  # nomes antigos de modulo encontrados (IO, List, ...)
                "applicative": set(),
                "exact": [],
            },
        )

    not_in_scope_re = re.compile(r"Variable not in scope: (\S+)")
    ambiguous_re = re.compile(
        r"Ambiguous occurrence [‘'](?P<name>\w+)[’'].*?"
        r"imported from [‘'](?P<module>[\w.]+)[’'].*?"
        r"defined at (?P<path>\S+):\d+:\d+\.",
        re.DOTALL,
    )
    old_module_re = re.compile(r"Could not find module [‘'](\w+)[’']")
    applicative_re = re.compile(r"No instance for [‘']Applicative ([^’']+)[’']")

    for path, block in blocks:
        m = not_in_scope_re.search(block)
        if m:
            name = m.group(1).strip("()")
            if name in OLDPRELUDE_NAMES:
                entry(path)["oldprelude"] = True

        m = ambiguous_re.search(block)
        if m:
            name, module, def_path = m.group("name"), m.group("module"), m.group("path")
            entry(def_path)["hiding"].setdefault(module, set()).add(name)

        m = old_module_re.search(block)
        if m and m.group(1) in OLD_MODULE_RENAMES:
            entry(path)["old_modules"].add(m.group(1))

        m = applicative_re.search(block)
        if m:
            entry(path)["applicative"].add(m.group(1))

        for needle, fn in EXACT_PATCHES:
            if needle in block:
                entry(path)["exact"].append(fn)

        # nosso proprio patch anterior inserido no lugar errado
        if "parse error on input ‘import’" in block:
            entry(path)["oldprelude"] = True
            entry(path)["_strip_broken_oldprelude"] = True

    return plan


def apply_plan(plan):
    touched_any = False
    for rel_path, actions in sorted(plan.items()):
        path = ROOT / rel_path if not Path(rel_path).is_absolute() else Path(rel_path)
        if not path.is_file():
            say_err("[x] ", f"{rel_path} não existe, pulando")
            continue

        text = path.read_text(encoding="utf-8")
        touched = []

        if actions.get("_strip_broken_oldprelude"):
            new_text = re.sub(r"^import OldPrelude\n", "", text, flags=re.MULTILINE)
            if new_text != text:
                text = new_text
                touched.append("removeu import OldPrelude mal posicionado")

        lines = text.splitlines(keepends=True)

        if actions["oldprelude"]:
            lines, changed = ensure_line_after_header(lines, "import OldPrelude")
            if changed == "no_module":
                say_warn(
                    "[!] ",
                    f"{rel_path}: sem 'module ... where' reconhecível, ajusta na mão",
                )
            elif changed:
                touched.append("import OldPrelude")

        for module, names in actions["hiding"].items():
            lines, changed = ensure_hiding(lines, module, names)
            if changed == "no_module":
                say_warn(
                    "[!] ",
                    f"{rel_path}: sem 'module ... where' reconhecível, ajusta na mão",
                )
            elif changed:
                touched.append(f"import {module} hiding ({', '.join(sorted(names))})")

        for type_name in actions["applicative"]:
            lines, changed = ensure_applicative(lines, type_name)
            if changed == "no_module":
                say_warn(
                    "[!] ",
                    f"{rel_path}: sem 'module ... where' reconhecível, ajusta na mão",
                )
            elif changed:
                touched.append(f"Functor/Applicative {type_name}")

        text = "".join(lines)

        for old_name in actions["old_modules"]:
            new_name = OLD_MODULE_RENAMES[old_name]
            text, changed = fix_old_module(text, old_name, new_name)
            if changed:
                touched.append(f"import {old_name} -> import {new_name}")

        for fn in actions["exact"]:
            text, changed = fn(text)
            if changed:
                touched.append(f"patch pontual ({fn.__name__})")

        if touched:
            path.write_text(text, encoding="utf-8")
            say_ok("[+] ", f"{rel_path}: {', '.join(touched)}")
            touched_any = True
        else:
            say_skip("[*] ", f"{rel_path}: nada a fazer (já corrigido antes?)")

    return touched_any


def main():
    fix_tabs()

    default_log = ROOT / "ghc-errors.log"
    log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_log
    check_script = ROOT / "check-haskell.sh"
    # corrigir um erro pode revelar o próximo (ex: "Could not find module IO"
    # vira "import System.IO" - só depois de rodar o typecheck de novo dá pra
    # ver que agora sobrou "Ambiguous occurrence isEOF"). Por isso, se tiver
    # como (log é o default e check-haskell.sh existe), reclassificamos e
    # aplicamos de novo automaticamente até convergir, em vez de obrigar
    # rodar ./check-haskell.sh + python3 autopatch.py na mão várias vezes.
    can_loop = log_path == default_log and check_script.is_file()
    max_iter = 10

    if not log_path.is_file() and can_loop:
        # primeira rodada, sem ghc-errors.log nenhum ainda (ex: full-code/
        # recém-baixado) - gera antes de tentar ler, pra não obrigar rodar
        # ./check-haskell.sh na mão só pra iniciar o ciclo.
        say_info("[~] sem ghc-errors.log ainda, rodando check-haskell.sh primeiro...")
        subprocess.run(
            [str(check_script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    for i in range(1, max_iter + 1):
        if not log_path.is_file():
            say_err("[x] ", f"Não achei {log_path}. Roda ./check-haskell.sh primeiro.")
            sys.exit(1)

        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        blocks = split_blocks(log_text)
        plan = classify(blocks)

        if not plan:
            if i == 1:
                say_ok(
                    "[+] ",
                    "Nenhum erro reconhecido no log pra corrigir automaticamente.",
                )
            else:
                say_ok(
                    "[+] ",
                    f"Convergiu depois de {i - 1} rodada(s) - nada mais pra corrigir.",
                )
            return

        touched_any = apply_plan(plan)

        if not touched_any or not can_loop:
            return

        say_info(
            f"[~] rodando check-haskell.sh de novo pra ver o que sobrou (rodada {i})..."
        )
        result = subprocess.run(
            [str(check_script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            say_err(
                "[x] ", "check-haskell.sh falhou ao rodar de novo, parando por aqui."
            )
            return

    say_warn(
        "[!] ",
        f"Parei depois de {max_iter} rodadas ainda com correção pendente - roda "
        "'python3 autopatch.py' de novo pra continuar.",
    )


if __name__ == "__main__":
    main()
