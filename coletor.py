#!/usr/bin/env python3
"""Coletor de preços para a Black Friday.

Lê produtos.txt, consulta o Zoom (comparador de preços: menor preço do dia
entre as lojas + histórico diário), guarda o histórico em docs/dados/ e
manda alertas pelo Telegram.

Só usa a biblioteca padrão do Python.
"""
from __future__ import annotations

import gzip
import html
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ARQ_PRODUTOS = RAIZ / "produtos.txt"
DADOS = RAIZ / "docs" / "dados"
ARQ_RESUMO = DADOS / "resumo.json"
ARQ_ESTADO = DADOS / "estado.json"
DIR_HIST = DADOS / "historico"

ZOOM = "https://www.zoom.com.br"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
BRT = timezone(timedelta(hours=-3))

MAX_COLETAS = 600          # leituras detalhadas guardadas por produto
QUEDA_ALERTA = 0.03        # avisa se cair 3% ou mais desde a última leitura
HORA_RESUMO = 8            # resumo diário na primeira coleta depois das 8h


# ---------------------------------------------------------------- rede

def baixar(url: str, tentativas: int = 3) -> str:
    erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "pt-BR,pt;q=0.9",
                "Accept-Encoding": "gzip",
            })
            with urllib.request.urlopen(req, timeout=40) as r:
                corpo = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    corpo = gzip.decompress(corpo)
                return corpo.decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            erro = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"falha ao baixar {url}: {erro}")


def estado_da_pagina(url: str) -> dict:
    pagina = baixar(url)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', pagina, re.S)
    if not m:
        raise RuntimeError(f"página sem dados (bloqueio ou mudança no site): {url}")
    return json.loads(m.group(1))["props"]["initialReduxState"]


# ---------------------------------------------------------------- produtos.txt

def ler_produtos() -> list[dict]:
    """Cada linha: nome do produto OU link do Zoom, e opcionalmente ' | preço-alvo'."""
    itens = []
    for linha in ARQ_PRODUTOS.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        partes = [p.strip() for p in linha.split("|")]
        alvo = None
        if len(partes) > 1 and partes[1]:
            txt = re.sub(r"[^\d,.]", "", partes[1])
            if "," in txt:                      # 3.500,00 -> 3500.00
                txt = txt.replace(".", "").replace(",", ".")
            elif re.fullmatch(r"\d{1,3}(\.\d{3})+", txt):   # 3.500 -> 3500
                txt = txt.replace(".", "")
            try:
                alvo = float(txt)
            except ValueError:
                print(f"  ! preço-alvo ilegível em: {linha}")
        itens.append({"entrada": partes[0], "alvo": alvo})
    return itens


def resolver_url(entrada: str, estado: dict) -> str | None:
    """Link do Zoom é usado direto; nome vira busca (resultado fica em cache)."""
    if entrada.startswith("http"):
        u = urllib.parse.urlsplit(entrada)
        return f"{ZOOM}{u.path}"
    cache = estado.setdefault("buscas", {})
    if entrada in cache:
        return cache[entrada]
    s = estado_da_pagina(f"{ZOOM}/search?q={urllib.parse.quote_plus(entrada)}")
    for hit in s.get("hits", {}).get("hits", []):
        if hit.get("type") == "product" and hit.get("url"):
            cache[entrada] = ZOOM + hit["url"]
            print(f"  busca '{entrada}' -> {hit.get('name')}")
            return cache[entrada]
    return None


# ---------------------------------------------------------------- coleta

def coletar(url: str) -> dict:
    s = estado_da_pagina(url)
    ofertas = s.get("offers", {})
    pid = str(ofertas.get("currentProductID") or "")
    prod = s.get("products", {}).get("product", {})
    nome = prod.get("product", {}).get("name") or ""
    if not pid or not nome:
        raise RuntimeError("produto não encontrado na página")

    lojas = {}
    lista = (ofertas.get("displayOffers") or []) + (ofertas.get("offerList") or [])
    melhor = ofertas.get("bestOffer") or {}
    if melhor:
        lista.append(melhor)
    for o in lista:
        if o.get("merchantId") and o.get("sellerName"):
            lojas[str(o["merchantId"])] = o["sellerName"]

    precos = [o for o in lista if o.get("price")]
    if not precos:
        raise RuntimeError("sem ofertas no momento")
    menor = min(precos, key=lambda o: o["price"])

    dias = {}
    hist = s.get("priceHistory", {}).get("priceHistory", {}).get(pid, {})
    for d in hist.get("days", []):
        if d.get("price"):
            dias[d["date"]] = {"preco": round(float(d["price"]), 2),
                               "loja_id": str(d.get("merchantId") or "")}

    imagens = prod.get("mediaImages") or []
    return {
        "id": pid,
        "nome": nome,
        "url": url,
        "imagem": imagens[0].get("url") if imagens else None,
        "preco": round(float(menor["price"]), 2),
        "loja": menor.get("sellerName") or "",
        "n_lojas": ofertas.get("countOfStores") or 0,
        "lojas": lojas,
        "dias_zoom": dias,
    }


def atualizar_historico(c: dict, agora: datetime) -> dict:
    arq = DIR_HIST / f"{c['id']}.json"
    h = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {
        "id": c["id"], "dias": {}, "coletas": [], "lojas": {}}
    h.update(nome=c["nome"], url=c["url"], imagem=c["imagem"])
    h["lojas"].update(c["lojas"])

    # histórico diário do Zoom (menor preço de cada dia)
    for data, d in c["dias_zoom"].items():
        h["dias"][data] = {"preco": d["preco"],
                           "loja": h["lojas"].get(d["loja_id"], "")}
    # o dia de hoje fica com o menor preço que nós mesmos vimos
    hoje = agora.strftime("%Y-%m-%d")
    atual = h["dias"].get(hoje)
    if not atual or c["preco"] <= atual["preco"]:
        h["dias"][hoje] = {"preco": c["preco"], "loja": c["loja"]}

    h["coletas"].append({"quando": agora.isoformat(timespec="minutes"),
                         "preco": c["preco"], "loja": c["loja"],
                         "n_lojas": c["n_lojas"]})
    h["coletas"] = h["coletas"][-MAX_COLETAS:]
    h["dias"] = dict(sorted(h["dias"].items()))
    arq.write_text(json.dumps(h, ensure_ascii=False, indent=1), encoding="utf-8")
    return h


# ---------------------------------------------------------------- análise

def analisar(h: dict, preco: float, hoje: str) -> dict:
    """Compara o preço de agora com o histórico e dá um veredito."""
    ant = [(d, v["preco"]) for d, v in h["dias"].items() if d < hoje]
    r = {"dias_historico": len(ant), "mediana": None, "minimo": None,
         "maximo": None, "minimo_data": None, "dif_mediana": None,
         "pico_recente": None}
    if len(ant) < 7:
        r.update(veredito="curto", titulo="Histórico curto",
                 explicacao="Ainda há poucos dias de histórico para julgar este preço.")
        return r

    ult30 = [p for _, p in ant[-30:]]
    mediana = statistics.median(ult30)
    minimo_data, minimo = min(ant, key=lambda x: x[1])
    r.update(mediana=round(mediana, 2), minimo=minimo, minimo_data=minimo_data,
             maximo=max(p for _, p in ant),
             dif_mediana=round((preco - mediana) / mediana * 100, 1))

    # Maquiagem: o preço subiu nos últimos dias e "baixou" para onde já estava.
    recentes = [p for _, p in ant[-10:]]
    base = [p for _, p in ant[:-10]]
    if len(base) >= 7:
        med_base = statistics.median(base)
        pico = max(recentes)
        r["pico_recente"] = pico
        if pico >= med_base * 1.08 and preco <= pico * 0.95 and preco >= med_base * 0.97:
            r.update(veredito="maquiado", titulo="Desconto maquiado",
                     explicacao=(f"Subiu para {brl(pico)} nos últimos dias e 'baixou' para "
                                 f"{brl(preco)}, mas antes disso o normal era {brl(med_base)}. "
                                 "Não é desconto de verdade."))
            return r

    pct = abs(r["dif_mediana"])
    if preco <= minimo * 1.001 and preco <= mediana * 0.97:
        r.update(veredito="otimo", titulo="Menor preço do histórico",
                 explicacao=(f"É o menor preço em {len(ant)} dias e está {pct:.0f}% abaixo "
                             f"do preço normal ({brl(mediana)})."))
    elif preco <= mediana * 0.93:
        r.update(veredito="bom", titulo="Desconto real",
                 explicacao=(f"{pct:.0f}% abaixo do preço normal dos últimos 30 dias "
                             f"({brl(mediana)}). O mínimo já visto foi {brl(minimo)}."))
    elif preco >= mediana * 1.07:
        r.update(veredito="caro", titulo="Acima do normal",
                 explicacao=(f"{pct:.0f}% acima do preço normal ({brl(mediana)}). "
                             "Se aparecer 'desconto' em cima disso, desconfie."))
    else:
        r.update(veredito="normal", titulo="Preço normal",
                 explicacao=(f"Perto do preço normal dos últimos 30 dias ({brl(mediana)}). "
                             f"O mínimo já visto foi {brl(minimo)}."))
    return r


def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------- alertas

ICONE = {"otimo": "🟢", "bom": "🟢", "normal": "⚪", "caro": "🔴",
         "maquiado": "⚠️", "curto": "❔"}


def telegram(texto: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("  (Telegram não configurado; alerta só no log)")
        print(re.sub(r"<[^>]+>", "", texto))
        return False
    dados = urllib.parse.urlencode({
        "chat_id": chat, "text": texto, "parse_mode": "HTML",
        "disable_web_page_preview": "true"}).encode()
    try:
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage", dados, timeout=30)
        return True
    except urllib.error.HTTPError as e:
        print(f"  ! Telegram recusou a mensagem: HTTP {e.code}")
    except (urllib.error.URLError, OSError):
        print("  ! Telegram fora do ar ou sem rede")
    return False


def linha_produto(p: dict) -> str:
    a = p["analise"]
    dif = f" ({a['dif_mediana']:+.0f}% vs normal)" if a["dif_mediana"] is not None else ""
    return (f"{ICONE[a['veredito']]} <a href=\"{p['url']}\">{html.escape(p['nome'])}</a>\n"
            f"   <b>{brl(p['preco'])}</b> em {html.escape(p['loja'])}{dif}\n"
            f"   {a['titulo']}")


def eventos_do_produto(p: dict, mem: dict) -> list[str]:
    """Decide o que merece alerta imediato, sem repetir o mesmo aviso."""
    ev = []
    a, preco = p["analise"], p["preco"]
    anterior = mem.get("preco")
    if anterior and preco <= anterior * (1 - QUEDA_ALERTA):
        ev.append(f"📉 Caiu {(anterior - preco) / anterior * 100:.0f}% "
                  f"(de {brl(anterior)} para {brl(preco)})")
    if a["veredito"] != mem.get("veredito") and a["veredito"] in ("otimo", "bom", "maquiado"):
        ev.append(f"{ICONE[a['veredito']]} {a['titulo']}: {a['explicacao']}")
    if p["alvo"] and preco <= p["alvo"]:
        if not mem.get("alvo_avisado") or preco < mem["alvo_avisado"]:
            ev.append(f"🎯 Chegou no seu preço-alvo de {brl(p['alvo'])}")
            mem["alvo_avisado"] = preco
    elif p["alvo"]:
        mem.pop("alvo_avisado", None)
    mem["preco"] = preco
    mem["veredito"] = a["veredito"]
    return ev


# ---------------------------------------------------------------- principal

def main() -> int:
    agora = datetime.now(BRT)
    hoje = agora.strftime("%Y-%m-%d")
    DIR_HIST.mkdir(parents=True, exist_ok=True)
    estado = json.loads(ARQ_ESTADO.read_text(encoding="utf-8")) if ARQ_ESTADO.exists() else {}
    memoria = estado.setdefault("produtos", {})

    produtos, erros, alertas = [], [], []
    for item in ler_produtos():
        print(f"- {item['entrada']}")
        try:
            url = resolver_url(item["entrada"], estado)
            if not url:
                raise RuntimeError("o Zoom não tem página de produto com histórico para esse nome; "
                                   "seja mais específico ou cole o link do produto no zoom.com.br")
            c = coletar(url)
            h = atualizar_historico(c, agora)
            p = {"id": c["id"], "nome": c["nome"], "url": c["url"], "imagem": c["imagem"],
                 "entrada": item["entrada"], "alvo": item["alvo"],
                 "preco": c["preco"], "loja": c["loja"], "n_lojas": c["n_lojas"],
                 "analise": analisar(h, c["preco"], hoje),
                 "serie": [[d, v["preco"]] for d, v in h["dias"].items()][-120:]}
            produtos.append(p)
            print(f"  {brl(p['preco'])} em {p['loja']} -> {p['analise']['titulo']}")
            ev = eventos_do_produto(p, memoria.setdefault(c["id"], {}))
            if ev:
                alertas.append(f"<b><a href=\"{p['url']}\">{html.escape(p['nome'])}</a></b>\n"
                               f"Agora: <b>{brl(p['preco'])}</b> em {html.escape(p['loja'])}\n"
                               + "\n".join(html.escape(e) for e in ev))
        except Exception as e:  # um produto com problema não derruba os outros
            erros.append({"entrada": item["entrada"], "erro": str(e)})
            print(f"  ! {e}")
        time.sleep(2)

    ARQ_RESUMO.write_text(json.dumps({
        "atualizado": agora.isoformat(timespec="minutes"),
        "fonte": "Zoom (zoom.com.br)", "produtos": produtos, "erros": erros,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    painel = os.environ.get("PAINEL_URL", "")
    rodape = f"\n\n<a href=\"{painel}\">Abrir painel</a>" if painel else ""

    if alertas:
        telegram("🔔 <b>Alerta de preço</b>\n\n" + "\n\n".join(alertas) + rodape)

    if produtos and estado.get("resumo_enviado") != hoje and agora.hour >= HORA_RESUMO:
        texto = (f"🛒 <b>Resumo do dia {agora.strftime('%d/%m')}</b>\n\n"
                 + "\n\n".join(linha_produto(p) for p in produtos))
        if erros:
            texto += "\n\n⚠️ Sem leitura: " + ", ".join(html.escape(e["entrada"]) for e in erros)
        if telegram(texto + rodape):
            estado["resumo_enviado"] = hoje

    # falha repetida de tudo = fonte fora do ar ou bloqueando: avisa uma vez por dia
    if not produtos and erros and estado.get("falha_avisada") != hoje:
        if telegram("⚠️ <b>Coleta de preços falhou</b>\nNenhum produto pôde ser lido agora. "
                    "Primeiro erro: " + html.escape(erros[0]["erro"])):
            estado["falha_avisada"] = hoje

    ARQ_ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(produtos)} produto(s) lidos, {len(erros)} erro(s), {len(alertas)} alerta(s).")
    return 0 if produtos or not erros else 1


if __name__ == "__main__":
    sys.exit(main())
