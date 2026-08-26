# craft2e no GHCi moderno

Kit pra rodar o código de *Haskell: The Craft of Functional Programming*
(2ª ed., Simon Thompson, 1999) num GHC/GHCi atual (9.14.1), sem precisar
do Hugs (que o livro usa originalmente, e está descontinuado desde 2006).

Feito originalmente pra estudo próprio, organizado aqui pra também servir
como documentação e passos/truques executados pra deixar tudo "funcional" 😉

## Pra quê?

A 2ª edição do livro é de 1999. Muita coisa mudou na linguagem (até mesmo
a versão dela, que passou de 98 pra 2010), e nas bibliotecas desde então:

- Nomes de módulo antigos: `List`, `Char`, `Maybe` viraram `Data.List`,
  `Data.Char`, `Data.Maybe` (padrão a partir do Haskell 2010)

- O Prelude reorganizou vários tipos de função: `length`, `mapM`,
  `elem` etc. deixaram de ser específicos de lista e viraram genéricos
  sobre `Foldable`/`Traversable` (reformas AMP/FTP, ~2014-2018). Os tipos
  que o livro mostra pra essas funções não batem mais com o que o GHCi
  reporta hoje.

- O Hugs dava de graça algumas funções monomórficas direto do
  Prelude (`eqChar`, `eqString`, `ordString`, `fromInt`, os operadores
  `+.`/`*.`/`>=.` etc.) que o livro usa de propósito antes do capítulo 12
  (que introduz overloading via type classes). Nada disso existe mais.

- O GHC de hoje é _mais permissivo em certos pontos_ (roda por padrão
  um "language edition" GHC2021/GHC2024, superset de extensões que Hugs
  nem tinha) e _mais estrito em outros_ (o Hugs tolerava uns desvios de
  sintaxe pontuais que o GHC rejeita, ver `Chapter10.hs` mais abaixo).

## Pré-requisitos

GHC/GHCup instalados (`ghc`, `ghci` no PATH). Testado com GHC 9.14.1, mas
qualquer GHC razoavelmente recente deve funcionar legal também.

`python3` com o pacote `rich` (`pip install rich`, ou use o `uv`), pra colorir
o output do `autopatch.py` - verde pra patch aplicado, amarelo pra "já
tava corrigido"/aviso de atenção manual, vermelho pra falha mais grave.

## Passo a passo

### 1. Baixar o código

```bash
./fetch.sh
```

Baixa `Code.tar.gz` direto do site oficial do autor e descompacta em
`./full-code`. Esse script pode ser rodado de novo a qualquer momento pra
resetar `./full-code` do zero (por isso `./full-code` fica fora do git, cf.
`.gitignore`: não faz sentido versionar uma cópia de código de terceiros
quando podemos fazer um request e obtê-lo de novo).

**Por que não commito `full-code/` direto no repo?** O código está sob
copyright Addison-Wesley/Simon Thompson, 1999. Baixar sob demanda da
fonte oficial em vez de vendorizar cópias evita problemas de redistribuição.

### 2. Ver o que quebra

```bash
./check-haskell.sh
```

Roda `ghc -fno-code` (só typecheck, não gera binário e não precisa que o
arquivo tenha `main`) em cada `.hs` de `./full-code` e subpastas; junta tudo
em `ghc-errors.log`. 

### 3. Aplicar os patches

```bash
python3 autopatch.py
```

Lê o `ghc-errors.log` gerado no passo anterior e corrige **sozinho** tudo que
sabemos corrigir, sem precisar passar nome de arquivo nem nada.

Corrigir um erro às vezes revela o próximo (ex: trocar `import IO` por
`import System.IO` faz o nome de verdade aparecer, e aí pode dar
"Ambiguous occurrence" com uma redefinição local do próprio arquivo,
erro que só existe _depois_ da primeira correção) - por isso o script
roda `./check-haskell.sh` de novo sozinho e reclassifica, repetindo até
convergir (não sobrar mais nada reconhecido pra corrigir) ou até um
_limite de 10 rodadas_.

Essa automação evita ter que alternar `check-haskell.sh` / `autopatch.py`
na mão: um único `python3 autopatch.py` já parte de um `full-code/` recém-baixado
(sem `ghc-errors.log` nenhum, sem nem precisar rodar `check-haskell.sh` antes) e
deixa tudo corrigido.

De modo geral, as correções aplicadas são:

- `import IO`: troca por `import System.IO`

- Colisão de nome com o Prelude (`Word`, `elem`...): insere
  ou estende `import Prelude hiding (...)` com os nomes certos

- Nome antigo do Hugs faltando (`eqChar`, `ordString`, `fromInt`,
  operadores `+.`/`*.`/`>=.`, `ord`/`chr`/`isDigit`...): insere
  `import OldPrelude` logo após o fim do cabeçalho do módulo, mesmo
  se esse cabeçalho ocupa várias linhas por causa de uma lista de
  exports longa (motivo de não poder ser apenas um `sed` "simples")

- `instance Monad Foo` sem `Functor`/`Applicative`: acrescenta as
  duas instances derivando do `Monad` já existente (`fmap = liftM`,
  `pure = return`, `(<*>) = ap`)

- Patches pontuais: o `` `renaming` `` do `Huffman/Bee.hs` (sintaxe de
  import removida desde Haskell 1.3, o próprio arquivo comenta a
  solução); o padrão `(n+1)` do `Parsing/ParseLib.hs`/`Calculator/ParseLib.hs`
  (removido no Haskell 2010); e `hugsIsEOF` (primop específico do
  GHC/Hugs de 1999 que não existe mais - `Calculator/MonadIO.hs`,
  `IO/MonadIO.hs` e `Chapter18.hs` redefiniam `isEOF` em cima dele
  porque o `isEOF` de verdade não funcionava direito na época; hoje
  funciona, então removemos a redefinição e devolvemos o `isEOF` real)

### 4. Carregar no GHCi

Sempre a partir da **raiz deste repo** (não de dentro de `full-code/`):

```bash
ghci
ghci> :l full-code/Chapter7.hs
```

Pra um arquivo direto em `full-code/` (`Chapter*.hs`, `Pictures.hs`,
`FirstScript.hs`), `:l` normal já basta.

Pra um arquivo de dentro de uma subpasta de case study
(`Huffman/`, `Calculator/`, `AbsTypes/`, `IO/`, `Parsing/`, `Simulation/`)
que importa um vizinho da própria pasta, use o comando customizado `:cl`
(definido no `.ghci`) em vez de `:l`:

```bash
ghci> :cl full-code/Huffman/Coding.hs
```

`:cl` recalcula o caminho de busca de módulo pra incluir a pasta do
próprio arquivo antes de carregar - o mesmo truque que o
`check-haskell.sh` já faz por fora, por arquivo.

Não dá pra deixar todas as subpastas juntas no caminho fixo de uma vez só,
porque nomes como `Store`, `Types`, `ParseLib` e `MonadIO` existem repetidos
em mais de uma subpasta (ex: `AbsTypes/Store.hs` e `Calculator/Store.hs`),
e um caminho fixo com as duas juntas resolveria pro vizinho errado
dependendo de qual arquivo importou. `:cl` evita isso resolvendo
pasta por pasta, um arquivo de cada vez - assim dá pra carregar
qualquer arquivo do livro, incluindo todos os case studies.

O `.ghci` na raiz configura automaticamente:

- O comando `:cl` (ver acima)

- Prompt mostrando o módulo carregado e `:set +t`, pra mostrar o tipo
  de toda expressão avaliada, um pequeno ajuste de qualidade de vida

- Caminho de busca de módulo default (`-i.:full-code/AbsTypes:full-code`),
  pra achar `OldPrelude.hs` (raiz), qualquer `Chapter*.hs`/`Pictures.hs`
  (`full-code/`), e o caso especial do `Chapter17.hs` (único arquivo de
  nível raiz que importa `Set`/`Relation`, que só existem em
  `full-code/AbsTypes/`). É por isso que `OldPrelude.hs` mora na raiz e
  não dentro de `full-code/`: mantém `full-code/` como uma cópia limpa e
  intocada do que foi baixado, sem misturar arquivo nosso com arquivo do
  livro. O trade-off é ter que rodar `ghci` sempre da raiz e usar
  `full-code/NomeDoArquivo.hs` ao dar `:l`/`:cl`

## `Code/` vs `helium/` no site do Kent

O zip original (`craft2e/helium/code.zip`) é uma versão
adaptada e reduzida pensada pra rodar no [Helium](https://github.com/Helium4Haskell/helium), um compilador
Haskell simplificado, feito com foco em mensagens de erro mais didáticas.

O que este kit usa (`craft2e/Code/Code.tar.gz`) é o pacote oficial e
completo do livro: todos os 20 capítulos, incluindo os _case studies_
(Huffman Coding no cap. 15, Tipos de Dados Abstratos no cap. 16,
Calculadora, Parsing, Simulação).
