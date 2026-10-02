# -*- coding: utf-8 -*-
"""Testes do backend da loja. Rodam sem internet e sem token do Mercado Pago.

Como rodar:   python -m unittest test_loja -v
"""
import os
import sys
import json
import tempfile
import unittest
from decimal import Decimal

# Ambiente de teste isolado: pastas temporárias e modo manual (sem token).
TMP = tempfile.mkdtemp()
CHARS = os.path.join(TMP, "chars")
os.makedirs(os.path.join(CHARS, "joao"))
os.environ.update({
    "ZHA_CHARS_DIR": CHARS,
    "ZHA_SERVER_DIR": TMP,
    "ZHA_SITE_DIR": TMP,
    "ZHA_PEDIDOS_FILE": os.path.join(TMP, "pedidos.json"),
    "MP_ACCESS_TOKEN": "",
    "MP_WEBHOOK_SECRET": "",
    "PIX_KEY": "chave-de-teste",
    "ZHA_ADMIN_PASS": "",
})
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loja_backend as lb  # noqa: E402


class TestValidacoes(unittest.TestCase):
    def test_quantidade_valida(self):
        self.assertEqual(lb.ler_quantidade("10"), 10)
        self.assertEqual(lb.ler_quantidade(" 250 "), 250)
        self.assertEqual(lb.ler_quantidade("1000"), 1000)

    def test_quantidade_invalida(self):
        for v in ["9", "1001", "0", "-5", "10.5", "1e3", "abc", "", None, "１０"]:
            self.assertIsNone(lb.ler_quantidade(v), v)

    def test_preco_calculado_no_servidor(self):
        self.assertEqual(lb.calcular_preco(37), Decimal("37.00"))

    def test_nome_do_personagem(self):
        self.assertIsNotNone(lb.pasta_do_char("joao"))
        for ruim in ["..", "..\\..", "../chars", "joao/..", "joao ", "nao_existe", "", "a" * 40]:
            self.assertIsNone(lb.pasta_do_char(ruim), ruim)


class TestLoja(unittest.TestCase):
    def setUp(self):
        lb._tentativas.clear()
        if os.path.exists(lb.PEDIDOS_FILE):
            os.remove(lb.PEDIDOS_FILE)
        self.c = lb.app.test_client()

    def comprar(self, **dados):
        return self.c.post("/api/comprar", json=dados)

    def test_compra_manual_ok(self):
        r = self.comprar(jogador="joao", quantidade="37").get_json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["vip"], 37)
        self.assertEqual(r["preco"], 37.0)
        self.assertEqual(r["chave_pix"], "chave-de-teste")
        with open(lb.PEDIDOS_FILE, encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)), 1)

    def test_preco_enviado_pelo_navegador_e_ignorado(self):
        r = self.comprar(jogador="joao", quantidade="50", preco=1).get_json()
        self.assertEqual(r["preco"], 50.0)

    def test_quantidade_invalida_e_recusada(self):
        for q in ["5", "99999", "abc", ""]:
            self.assertFalse(self.comprar(jogador="joao", quantidade=q).get_json()["ok"], q)

    def test_personagem_inexistente_ou_malicioso(self):
        for nome in ["fantasma", "..", "..\\..\\x"]:
            self.assertFalse(self.comprar(jogador=nome, quantidade="10").get_json()["ok"], nome)

    def test_limite_de_pedidos_por_ip(self):
        for _ in range(lb.LIMITE_PEDIDOS):
            self.assertEqual(self.comprar(jogador="joao", quantidade="10").status_code, 200)
        self.assertEqual(self.comprar(jogador="joao", quantidade="10").status_code, 429)

    def test_admin_desligado_sem_senha(self):
        r = self.c.post("/api/admin/pedidos", json={"senha": ""})
        self.assertEqual(r.status_code, 403)

    def test_cors_so_para_origem_permitida(self):
        ok = self.c.get("/api/config", headers={"Origin": "https://radiolc.com"})
        ruim = self.c.get("/api/config", headers={"Origin": "https://site-malicioso.com"})
        self.assertEqual(ok.headers.get("Access-Control-Allow-Origin"), "https://radiolc.com")
        self.assertIsNone(ruim.headers.get("Access-Control-Allow-Origin"))

    def test_credito_grava_arquivo_pendente(self):
        self.assertEqual(lb.creditar_vip("joao", 10), 10)
        arqs = os.listdir(lb.VIP_PENDENTE_DIR)
        self.assertTrue(any(a.startswith("joao_") for a in arqs))
        self.assertIsNone(lb.creditar_vip("fantasma", 10))

    def test_arquivo_corrompido_nao_apaga_historico(self):
        with open(lb.PEDIDOS_FILE, "w", encoding="utf-8") as f:
            f.write("{quebrado")
        with self.assertRaises(ValueError):
            lb.carregar_pedidos()


if __name__ == "__main__":
    unittest.main(verbosity=2)
