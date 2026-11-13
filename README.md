# Pesquisa Black

Acompanha preços e histórico de preços para não cair em desconto falso na Black Friday.

- **Painel (abre no celular):** https://andersonmoro.github.io/pesquisa-black/
- **Fonte:** [Zoom](https://www.zoom.com.br), comparador de preços. Usa o menor preço do dia
  entre as lojas e o histórico diário do próprio Zoom (cerca de 40 dias), e passa a acumular
  o histórico aqui a cada coleta.
- **Rotina:** o GitHub Actions roda `coletor.py` a cada 2 horas e salva tudo em `docs/dados/`.
- **Alertas:** Telegram. Um resumo por dia (primeira coleta depois das 8h) e aviso imediato
  quando o preço cai 3% ou mais, vira desconto real, atinge o preço-alvo ou é desconto maquiado.

## Mudar a lista de produtos

Edite [`produtos.txt`](produtos.txt) (dá para fazer pelo celular, no lápis do GitHub).
Um produto por linha: o nome ou o link da página do produto no Zoom. Para ter aviso de
preço-alvo, acrescente ` | valor`:

```
iPhone 15 128GB | 3500
https://www.zoom.com.br/celular/smartphone-apple-iphone-15-128gb-camera-dupla
```

Ao salvar, a coleta roda sozinha. Se um nome não for encontrado, aparece um cartão de erro
no painel; nesse caso use o link do produto.

## Como o preço é julgado

"Preço normal" é a mediana dos últimos 30 dias.

| Veredito | Regra |
| --- | --- |
| Menor preço do histórico | menor preço já visto e pelo menos 3% abaixo do normal |
| Desconto real | 7% ou mais abaixo do normal |
| Preço normal | dentro de ±7% do normal |
| Acima do normal | 7% ou mais acima do normal |
| Desconto maquiado | subiu 8% ou mais nos últimos 10 dias e "baixou" para perto do preço de antes |

## Configurar o Telegram (uma vez)

1. No Telegram, fale com **@BotFather**, envie `/newbot` e siga os passos. Ele devolve um token.
2. Abra uma conversa com o seu bot novo e envie qualquer mensagem.
3. Abra `https://api.telegram.org/bot<TOKEN>/getUpdates` no navegador e copie o número em
   `"chat":{"id": ...}`.
4. No repositório: **Settings → Secrets and variables → Actions → New repository secret**.
   Crie `TELEGRAM_BOT_TOKEN` (o token) e `TELEGRAM_CHAT_ID` (o número).

## Ligar o painel (uma vez)

**Settings → Pages → Source: Deploy from a branch → Branch: `main`, pasta `/docs` → Save.**

## Rodar no computador

```bash
python coletor.py
```
