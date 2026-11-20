---
name: monitor-favoritos
description: Lê os preços dos produtos que o usuário deixou nos favoritos do Mercado Livre, da Amazon e da Shopee, abrindo cada página no Chrome dele (já logado), e grava a leitura no repositório pesquisa-black, que monta o histórico, atualiza o painel e manda o Telegram. Use quando a tarefa agendada pedir para rodar o monitor de favoritos, ou quando o usuário digitar /monitor-favoritos ou pedir para "ler os favoritos", "conferir os preços dos favoritos" ou "rodar a pesquisa nos favoritos".
---

# Monitor de favoritos

Objetivo: ler nome, preço e link de cada produto nos favoritos das lojas abaixo e gravar tudo
num único arquivo, `favoritos.json`, no branch `main` do repositório `andersonmoro/pesquisa-black`.
O GitHub cuida do resto (histórico, painel e mensagem no Telegram). Você não manda Telegram.

Só leitura. Nunca compre, nunca adicione ao carrinho, nunca tire nem coloque item nos favoritos,
nunca mude nada nas contas. Se uma página pedir login, senha, código ou captcha, não preencha:
registre como falha daquela loja e siga para a próxima.

## 1. Abrir o navegador

Use o navegador em que o usuário já está logado nas lojas: Claude in Chrome (ferramentas
`mcp__claude-in-chrome__*`). Leia antes a skill `chrome-browser`, se ela existir. Trabalhe em
uma aba nova e feche essa aba no fim.

## 2. Ler cada loja

| Loja | Página dos favoritos |
| --- | --- |
| Mercado Livre | https://www.mercadolivre.com.br/favoritos |
| Amazon | https://www.amazon.com.br/hz/wishlist/ls (Lista de desejos; se houver mais de uma lista, leia todas) |
| Shopee | https://shopee.com.br → ícone da conta → "Meus Curtidos" (ou "Favoritos") |

Em cada uma:
1. Abra a página e espere carregar. Role até o fim para carregar todos os itens.
2. Prefira ler o texto da página a tirar print. Para cada produto, anote:
   - `nome`: o título do produto, como aparece.
   - `preco`: o preço à vista atual, só o número (ex.: `289.90`). Se houver preço riscado e
     preço novo, use o novo. Não use preço de parcela nem preço com cupom que ainda não foi aplicado.
   - `url`: o link da página do produto (abra o item, se o link não estiver visível).
     Tire parâmetros de rastreio quando o link continuar funcionando sem eles.
   - `imagem` (opcional): o link da foto.
   - `obs` (opcional, curta): só fatos que a loja mostra, como "A Amazon diz: preço caiu 12%
     desde que foi adicionado" ou "Frete grátis". Não invente histórico.
3. Não inclua itens indisponíveis ou sem preço.
4. Se a loja não abrir, pedir login ou não mostrar a lista, registre em `falhas`
   (`{"loja": "Shopee", "erro": "pediu login"}`) e siga.

## 3. Gravar no repositório

Monte este JSON (horário atual com fuso de Brasília):

```json
{
  "quando": "2026-11-20T18:05:00-03:00",
  "itens": [
    {"loja": "Mercado Livre", "nome": "...", "preco": 289.9, "url": "https://...", "imagem": "https://...", "obs": "..."},
    {"loja": "Amazon", "nome": "...", "preco": 1299.0, "url": "https://..."}
  ],
  "falhas": [{"loja": "Shopee", "erro": "pediu login"}]
}
```

Grave com o conector do GitHub:
1. `get_file_contents` em `andersonmoro/pesquisa-black`, caminho `favoritos.json`,
   ref `refs/heads/main`, para pegar o SHA (se o arquivo não existir, siga sem SHA).
2. `create_or_update_file` no branch `main`, caminho `favoritos.json`, mensagem
   `Leitura dos favoritos`, com o JSON acima e o SHA do passo 1.

Grave mesmo que todas as lojas falhem (com `itens` vazio e as `falhas`), para o usuário
receber o aviso. Não mexa em nenhum outro arquivo e não abra pull request.

## 4. Responder

Uma linha: quantos itens leu por loja e quais lojas falharam.
Exemplo: "Favoritos lidos: Mercado Livre 4, Amazon 2; Shopee pediu login."
