-- OldPrelude.hs
--
-- O Hugs de 1999 (o interpretador que o livro usa) expunha um punhado de
-- funcoes monomórficas direto do Prelude que hoje não existem mais (foram
-- substituidas pelas versões overloaded via type class, ou movidas
-- pra `Data.Char`).
--
-- O livro usa essas funções antes do capítulo 12 (Overloading and Type Classes)
-- de propósito, pra não precisar explicar classes ainda.
--
-- Pra arrumar, basta importar no topo de qualquer `Chapter*.hs` que reclamar
-- de "Variable not in scope":
--
--   import OldPrelude
--
-- Se aparecer outro nome faltando que não tá aqui, é só adicionar a definição
-- seguindo o mesmo padrão.

module OldPrelude
  ( eqChar, eqString, eqInt, eqList, eqTuple2, eqTuple3
  , ordChar, ordString, ordInt, ordList, ordTuple2
  , fromInt, showInt, readInt
  , (+.), (-.), (*.), (/.), (==.), (/=.), (<.), (<=.), (>.), (>=.)
  , ord, chr, isDigit, isAlpha, isSpace, isUpper, isLower, toUpper, toLower
  ) where

import Data.Char
  ( ord, chr, isDigit, isAlpha, isSpace, isUpper, isLower, toUpper, toLower )

-- Comparações monomórficas que o Hugs dava de graca. Hoje são só (==)
-- especializado; escrevemos por extenso pra eqList/eqTuple2/eqTuple3
-- porque essas nunca tiveram equivalente direto em (==) sozinho

eqChar :: Char -> Char -> Bool
eqChar = (==)

eqString :: String -> String -> Bool
eqString = (==)

eqInt :: Int -> Int -> Bool
eqInt = (==)

eqList :: (a -> a -> Bool) -> [a] -> [a] -> Bool
eqList _  []     []     = True
eqList eq (x:xs) (y:ys) = eq x y && eqList eq xs ys
eqList _  _      _      = False

eqTuple2 :: (a -> a -> Bool) -> (b -> b -> Bool) -> (a, b) -> (a, b) -> Bool
eqTuple2 eqA eqB (a1, b1) (a2, b2) = eqA a1 a2 && eqB b1 b2

eqTuple3 :: (a -> a -> Bool) -> (b -> b -> Bool) -> (c -> c -> Bool)
         -> (a, b, c) -> (a, b, c) -> Bool
eqTuple3 eqA eqB eqC (a1, b1, c1) (a2, b2, c2) =
  eqA a1 a2 && eqB b1 b2 && eqC c1 c2

-- Mesma familia, só que pra ordenação (Ordering = LT | EQ | GT)
-- em vez de igualdade. Hoje é só `compare` especializado

ordChar :: Char -> Char -> Ordering
ordChar = compare

ordString :: String -> String -> Ordering
ordString = compare

ordInt :: Int -> Int -> Ordering
ordInt = compare

ordList :: (a -> a -> Ordering) -> [a] -> [a] -> Ordering
ordList _   []     []     = EQ
ordList _   []     (_:_)  = LT
ordList _   (_:_)  []     = GT
ordList ord (x:xs) (y:ys) = case ord x y of
                               EQ    -> ordList ord xs ys
                               other -> other

ordTuple2 :: (a -> a -> Ordering) -> (b -> b -> Ordering)
          -> (a, b) -> (a, b) -> Ordering
ordTuple2 ordA ordB (a1, b1) (a2, b2) =
  case ordA a1 a2 of
    EQ    -> ordB b1 b2
    other -> other

-- fromInt/showInt/readInt existiam no Prelude pré-Haskell98
-- Viraram fromIntegral/show/read

fromInt :: Num a => Int -> a
fromInt = fromIntegral

showInt :: Int -> String
showInt = show

readInt :: String -> Int
readInt = read

-- Operadores "pontuados" (+. -. *. /. etc.) que o livro usa antes do
-- capítulo de overloading, pra deixar explícito que a conta é sobre
-- Float e não um número genérico. Fixidade igual a dos operadores
-- normais (+ - * / < <= > >= ==) pra não quebrar precedência.

infixl 6 +., -.
infixl 7 *., /.
infix 4 ==., /=., <., <=., >., >=.

(+.), (-.), (*.), (/.) :: Float -> Float -> Float
(+.) = (+)
(-.) = (-)
(*.) = (*)
(/.) = (/)

(==.), (/=.), (<.), (<=.), (>.), (>=.) :: Float -> Float -> Bool
(==.) = (==)
(/=.) = (/=)
(<.)  = (<)
(<=.) = (<=)
(>.)  = (>)
(>=.) = (>=)
