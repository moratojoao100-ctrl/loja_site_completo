# -*- coding: utf-8 -*-
"""
LOJA VIRTUAL - ÚLTIMO DISTRITO / NET FORGE ESTÚDIOS
Backend Flask para vender créditos VIP, com quantidade livre.

SEGREDOS: nada fica no código. Defina as variáveis de ambiente no servidor:
  MP_ACCESS_TOKEN     token de produção do Mercado Pago (vazio = modo manual)
  MP_WEBHOOK_SECRET   "assinatura secreta" do webhook (painel do Mercado Pago)
  ZHA_ADMIN_PASS      senha do admin (vazio = rotas de admin desligadas)
  PIX_KEY             chave PIX do modo manual
  ZHA_CHARS_DIR, ZHA_SERVER_DIR, ZHA_SITE_DIR, ZHA_BACKEND_URL
  ALLOWED_ORIGINS     sites que podem chamar a API, separados por vírgula
"""

import os
import re
import json
import time
import uuid
import hmac
import hashlib
import logging
import threading
from decimal import Decimal, ROUND_HALF_UP

import requests
from flask import Flask, request, jsonify, send_from_directory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("loja")

# ====================== CONFIGURAÇÃO ======================

CHARS_DIR = os.environ.get("ZHA_CHARS_DIR", r"C:\Users\Administrator\Desktop\server\chars")
SERVER_DIR = os.environ.get("ZHA_SERVER_DIR", os.path.dirname(CHARS_DIR.rstrip("\\/")) or ".")
VIP_PENDENTE_DIR = os.path.join(SERVER_DIR, "vip_pendente")
SITE_DIR = os.environ.get("ZHA_SITE_DIR", "../wwwroot")
PEDIDOS_FILE = os.environ.get("ZHA_PEDIDOS_FILE", "pedidos.json")

MP_ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN", "")
MP_WEBHOOK_SECRET = os.environ.get("MP_WEBHOOK_SECRET", "")
BACKEND_PUBLIC_URL = os.environ.get("ZHA_BACKEND_URL", "https://netforge.ddns.net").rstrip("/")
ADMIN_PASSWORD = os.environ.get("ZHA_ADMIN_PASS", "")
PIX_KEY = os.environ.get("PIX_KEY", "")
ALLOWED_ORIGINS = {o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", "https://netforge.ddns.net,https://radiolc.com").split(",") if o.strip()}

# Quantidade livre: 1 crédito = R$ 1,00
PRECO_POR_CREDITO = Decimal(os.environ.get("PRECO_POR_CREDITO", "1.00"))
MIN_CREDITOS = int(os.environ.get("MIN_CREDITOS", "10"))
MAX_CREDITOS = int(os.environ.get("MAX_CREDITOS", "1000"))

# Limite simples: no máximo N pedidos por IP a cada janela (segundos)
LIMITE_PEDIDOS = 5
JANELA_SEG = 600

_lock = threading.Lock()
_tentativas = {}
NOME_OK = re.compile(r"^[\w\- ]{1,32}$", re.UNICODE)

app = Flask(__name__)


# ====================== CORS (só origens permitidas, nunca no admin) ======================

@app.after_request
def _cors(resp):
    origem = request.headers.get("Origin", "")
    if origem in ALLOWED_ORIGINS and not request.path.startswith("/api/admin"):
        resp.headers["Access-Control-Allow-Origin"] = origem
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Vary"] = "Origin"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


# ====================== VALIDAÇÕES ======================

def pasta_do_char(nome):
    """Devolve a pasta do personagem se o nome for seguro e a pasta existir; senão None."""
    if not NOME_OK.match(nome) or nome.strip(" .") != nome:
        return None
    base = os.path.realpath(CHARS_DIR)
    pasta = os.path.realpath(os.path.join(base, nome))
    if os.path.dirname(pasta) != base or not os.path.isdir(pasta):
        return None
    return pasta


def ler_quantidade(valor):
    s = str(valor).strip()
    if not re.fullmatch(r"\d{1,6}", s, re.ASCII):
        return None
    q = int(s)
    return q if MIN_CREDITOS <= q <= MAX_CREDITOS else None


def calcular_preco(qtd):
    return (Decimal(qtd) * PRECO_POR_CREDITO).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def limitado(ip):
    agora = time.time()
    with _lock:
        recentes = [t for t in _tentativas.get(ip, []) if agora - t < JANELA_SEG]
        if len(recentes) >= LIMITE_PEDIDOS:
            _tentativas[ip] = recentes
            return True
        recentes.append(agora)
        _tentativas[ip] = recentes
        return False


def senha_admin_ok(dados):
    if not ADMIN_PASSWORD:
        return False
    return hmac.compare_digest(str(dados.get("senha") or ""), ADMIN_PASSWORD)


# ====================== PEDIDOS (gravação atômica) ======================

def carregar_pedidos():
    """Se o arquivo não existe, lista vazia. Se está corrompido, FALHA (não apaga o histórico)."""
    if not os.path.exists(PEDIDOS_FILE):
        return []
    with open(PEDIDOS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_pedidos(pedidos):
    tmp = PEDIDOS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(pedidos, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PEDIDOS_FILE)


def registrar_pedido(nome, qtd, preco, modo, mp_id=None, parceiro=""):
    with _lock:
        pedidos = carregar_pedidos()
        pedido = {
            "id": str(int(time.time() * 1000)),
            "jogador": nome,
            "vip": qtd,
            "preco": float(preco),
            "status": "aguardando",   # aguardando | creditado
            "modo": modo,             # manual | automatico
            "mp_id": mp_id,
            "parceiro": parceiro,
            "data": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        pedidos.append(pedido)
        salvar_pedidos(pedidos)
        return pedido


def creditar_vip(nome, quantidade):
    """Grava o arquivo em vip_pendente/ que o servidor do jogo lê. None se falhar."""
    if pasta_do_char(nome) is None:
        return None
    try:
        os.makedirs(VIP_PENDENTE_DIR, exist_ok=True)
        nome_arq = "".join(c for c in nome if c.isalnum() or c in "_-") or "jogador"
        arq = os.path.join(VIP_PENDENTE_DIR, "%s_%d_%s.txt" % (nome_arq, int(time.time() * 1000), uuid.uuid4().hex[:6]))
        with open(arq, "w", encoding="utf-8") as f:
            f.write(nome + "|" + str(int(quantidade)))
    except Exception:
        log.exception("Falha ao gravar VIP pendente de %s", nome)
        return None
    return int(quantidade)


def marcar_creditado(pedido_id):
    with _lock:
        pedidos = carregar_pedidos()
        for p in pedidos:
            if p["id"] == pedido_id and p["status"] != "creditado":
                if creditar_vip(p["jogador"], p["vip"]) is None:
                    return None, "Personagem não encontrado ou erro ao gravar o VIP."
                p["status"] = "creditado"
                p["creditado_em"] = time.strftime("%Y-%m-%d %H:%M:%S")
                salvar_pedidos(pedidos)
                log.info("Pedido %s creditado manualmente (%s, %s VIP)", pedido_id, p["jogador"], p["vip"])
                return p, "ok"
        return None, "Pedido não encontrado ou já creditado."


# ====================== SITE ======================

@app.route("/")
def index():
    return send_from_directory(SITE_DIR, "index.html")


@app.route("/<path:caminho>")
def arquivos(caminho):
    return send_from_directory(SITE_DIR, caminho)


# ====================== API DA LOJA ======================

@app.route("/api/config")
def config():
    return jsonify({"ok": True, "min": MIN_CREDITOS, "max": MAX_CREDITOS,
                    "preco_por_credito": float(PRECO_POR_CREDITO)})


@app.route("/api/comprar", methods=["POST"])
def comprar():
    dados = request.get_json(force=True, silent=True) or {}
    nome = str(dados.get("jogador") or "").strip()
    parceiro = "".join(c for c in str(dados.get("parceiro") or "").lower() if c.isalnum())[:30]

    if limitado(request.remote_addr):
        return jsonify({"ok": False, "erro": "Muitas tentativas. Espere alguns minutos e tente de novo."}), 429
    if not nome:
        return jsonify({"ok": False, "erro": "Digite o nome do seu personagem no jogo."})
    qtd = ler_quantidade(dados.get("quantidade"))
    if qtd is None:
        return jsonify({"ok": False, "erro": "Digite uma quantidade inteira entre %d e %d créditos." % (MIN_CREDITOS, MAX_CREDITOS)})
    if pasta_do_char(nome) is None:
        return jsonify({"ok": False, "erro": "Personagem não encontrado. Entre no jogo ao menos uma vez antes de comprar."})

    preco = calcular_preco(qtd)  # o preço SEMPRE é calculado aqui, nunca vem do navegador

    if MP_ACCESS_TOKEN:
        try:
            headers = {
                "Authorization": "Bearer " + MP_ACCESS_TOKEN,
                "Content-Type": "application/json",
                "X-Idempotency-Key": str(uuid.uuid4()),
            }
            pagamento = {
                "transaction_amount": float(preco),
                "description": "%d créditos VIP - jogador %s%s" % (qtd, nome, (" - parceria " + parceiro) if parceiro else ""),
                "payment_method_id": "pix",
                "payer": {"email": "comprador@gmail.com", "first_name": nome},
                "notification_url": BACKEND_PUBLIC_URL + "/api/webhook",
            }
            r = requests.post("https://api.mercadopago.com/v1/payments", json=pagamento, headers=headers, timeout=30)
            try:
                corpo = r.json()
            except Exception:
                corpo = {}
            if r.status_code not in (200, 201) or "point_of_interaction" not in corpo:
                log.error("Mercado Pago recusou o pagamento: %s %s", r.status_code, r.text[:500])
                return jsonify({"ok": False, "erro": "Não foi possível gerar o PIX agora. Tente de novo em instantes."})

            pedido = registrar_pedido(nome, qtd, preco, "automatico", str(corpo.get("id")), parceiro)
            tx = corpo["point_of_interaction"]["transaction_data"]
            return jsonify({
                "ok": True, "modo": "automatico", "pedido_id": pedido["id"],
                "qr_code": tx.get("qr_code"), "qr_code_base64": tx.get("qr_code_base64"),
                "vip": qtd, "preco": float(preco),
            })
        except Exception:
            log.exception("Erro ao criar pagamento")
            return jsonify({"ok": False, "erro": "Erro ao criar o pagamento. Tente de novo em instantes."})

    if not PIX_KEY:
        return jsonify({"ok": False, "erro": "A loja não está configurada."})
    pedido = registrar_pedido(nome, qtd, preco, "manual", None, parceiro)
    return jsonify({"ok": True, "modo": "manual", "pedido_id": pedido["id"],
                    "chave_pix": PIX_KEY, "vip": qtd, "preco": float(preco)})


# ====================== WEBHOOK ======================

def assinatura_ok(data_id):
    """Confere a assinatura x-signature do Mercado Pago (se MP_WEBHOOK_SECRET estiver definido)."""
    if not MP_WEBHOOK_SECRET:
        log.warning("MP_WEBHOOK_SECRET não definido: webhook sem verificação de assinatura")
        return True
    partes = {}
    for p in request.headers.get("x-signature", "").split(","):
        if "=" in p:
            k, v = p.strip().split("=", 1)
            partes[k] = v
    ts, v1 = partes.get("ts"), partes.get("v1")
    if not ts or not v1:
        return False
    manifest = "id:%s;request-id:%s;ts:%s;" % (str(data_id).lower(), request.headers.get("x-request-id", ""), ts)
    calc = hmac.new(MP_WEBHOOK_SECRET.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, v1)


@app.route("/api/webhook", methods=["POST"])
def webhook():
    if not MP_ACCESS_TOKEN:
        return jsonify({"ok": True})
    dados = request.get_json(force=True, silent=True) or {}
    pagamento_id = request.args.get("data.id") or (dados.get("data") or {}).get("id") or request.args.get("id")
    if not pagamento_id or (dados.get("type") and dados.get("type") != "payment"):
        return jsonify({"ok": True})
    pagamento_id = str(pagamento_id)

    if not assinatura_ok(pagamento_id):
        log.warning("Webhook com assinatura inválida (id %s)", pagamento_id)
        return jsonify({"ok": False}), 403
    try:
        r = requests.get("https://api.mercadopago.com/v1/payments/" + pagamento_id,
                         headers={"Authorization": "Bearer " + MP_ACCESS_TOKEN}, timeout=30)
        r.raise_for_status()
        corpo = r.json()
        if corpo.get("status") == "approved":
            with _lock:
                pedidos = carregar_pedidos()
                for p in pedidos:
                    if p.get("mp_id") == pagamento_id and p["status"] != "creditado":
                        pago = Decimal(str(corpo.get("transaction_amount")))
                        if abs(pago - Decimal(str(p["preco"]))) > Decimal("0.005"):
                            log.error("Valor pago (%s) difere do pedido %s (%s)", pago, p["id"], p["preco"])
                            continue
                        if creditar_vip(p["jogador"], p["vip"]) is not None:
                            p["status"] = "creditado"
                            p["creditado_em"] = time.strftime("%Y-%m-%d %H:%M:%S")
                            salvar_pedidos(pedidos)
                            log.info("Pedido %s creditado (%s, %s VIP)", p["id"], p["jogador"], p["vip"])
        return jsonify({"ok": True})
    except Exception:
        log.exception("Erro no webhook (pagamento %s)", pagamento_id)
        return jsonify({"ok": False}), 500  # o Mercado Pago tenta de novo


# ====================== ADMIN (modo manual) ======================

@app.route("/api/admin/pedidos", methods=["POST"])
def admin_pedidos():
    dados = request.get_json(force=True, silent=True) or {}
    if not senha_admin_ok(dados):
        time.sleep(1)
        return jsonify({"ok": False, "erro": "Acesso negado."}), 403
    return jsonify({"ok": True, "pedidos": carregar_pedidos()})


@app.route("/api/admin/confirmar", methods=["POST"])
def admin_confirmar():
    dados = request.get_json(force=True, silent=True) or {}
    if not senha_admin_ok(dados):
        time.sleep(1)
        return jsonify({"ok": False, "erro": "Acesso negado."}), 403
    pedido, msg = marcar_creditado(str(dados.get("pedido_id") or ""))
    if pedido is None:
        return jsonify({"ok": False, "erro": msg})
    return jsonify({"ok": True, "pedido": pedido})


if __name__ == "__main__":
    print("=== Loja Último Distrito ===")
    print("Modo:", "AUTOMÁTICO (Mercado Pago)" if MP_ACCESS_TOKEN else "MANUAL")
    print("Admin:", "ligado" if ADMIN_PASSWORD else "desligado (defina ZHA_ADMIN_PASS)")
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=8080)
    except ImportError:
        app.run(host="0.0.0.0", port=8080)
