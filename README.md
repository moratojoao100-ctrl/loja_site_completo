# Site da parceria DJVieon e Último Distrito

Site da parceria oficial entre o DJVieon e o **Último Distrito**, audiogame de RP da Net Forge Estúdios. Tem a página da parceria, o guia de ajuda do jogo e a loja de créditos VIP com pagamento por PIX.

## Estrutura

```
wwwroot/
├── estilo.css                  # estilo único de todas as páginas
├── jogo/
│   └── ultimo_distrito.zip     # download do jogo (Windows)
└── parceria/
    ├── index.html              # a parceria e o botão de download
    ├── ajuda.html              # primeiros passos, teclas, profissões, construção
    └── loja.html               # loja de créditos VIP

servidor/
├── loja_backend.py             # backend Flask da loja
├── requirements.txt
├── test_loja.py                # testes automáticos do backend
└── pedidos.json                # criado sozinho; NÃO deixar dentro do wwwroot
```

As páginas chamam `../estilo.css` e `../jogo/ultimo_distrito.zip`, então a pasta `parceria` precisa ficar dentro do `wwwroot`, ao lado de `estilo.css` e `jogo`.

## Páginas

| Página | O que tem |
|---|---|
| `index.html` | Boas-vindas, o que é o jogo, aviso de versão BETA, como começar e links da comunidade (TeamTalk e WhatsApp) |
| `ajuda.html` | Primeiros passos, teclas principais, carro, profissões, construção civil e regras |
| `loja.html` | Compra de créditos VIP com quantidade livre e PIX |

Todas seguem as mesmas práticas de acessibilidade, pensadas para quem joga de ouvido: link "Pular para o conteúdo", `aria-current` no menu, `aria-live` nos avisos da loja, foco de teclado visível e alvos de toque de pelo menos 44 px.

## Estilo

`estilo.css` é um tema escuro de alto contraste com destaque em ciano. Usa a fonte Atkinson Hyperlegible, com Segoe UI e Verdana de reserva. Para trocar as cores, edite as variáveis no início do arquivo (`--ciano`, `--fundo`, `--ambar`, etc.).

## Loja

O jogador digita o nome do personagem e a quantidade de créditos, e o backend gera o PIX pelo Mercado Pago. Quando o pagamento é aprovado, o webhook grava o VIP em `vip_pendente/`, e o servidor do jogo lê esse arquivo e soma o crédito ao jogador.

- Preço: R$ 1,00 por crédito (configurável).
- Quantidade: de 10 a 1000 créditos (configurável).
- O preço é sempre calculado no servidor, nunca pelo navegador.
- Sem token do Mercado Pago, a loja funciona em **modo manual**: mostra a chave PIX e o admin confirma o pagamento.

### Ligar e desligar a loja

Em `loja.html`, no final do arquivo:

```js
var LOJA_ATIVA = false;   // troque para true para abrir a loja
```

### Rodar o backend

```bash
pip install -r requirements.txt
python loja_backend.py
```

O servidor sobe na porta **8080** (usa `waitress` quando instalado).

### Variáveis de ambiente

Nenhum segredo fica no código. Defina tudo no servidor:

| Variável | Para que serve |
|---|---|
| `MP_ACCESS_TOKEN` | Token de produção do Mercado Pago. Vazio = modo manual |
| `MP_WEBHOOK_SECRET` | Assinatura secreta do webhook (painel do Mercado Pago) |
| `ZHA_ADMIN_PASS` | Senha do admin. Vazia = rotas de admin desligadas |
| `PIX_KEY` | Chave PIX usada no modo manual |
| `ZHA_BACKEND_URL` | URL pública do backend, usada na notificação do webhook |
| `ZHA_CHARS_DIR` | Pasta `chars` do servidor do jogo |
| `ZHA_SERVER_DIR` | Pasta do servidor (onde fica `vip_pendente`) |
| `ZHA_SITE_DIR` | Pasta do site (`wwwroot`) |
| `ALLOWED_ORIGINS` | Sites autorizados a chamar a API, separados por vírgula |
| `PRECO_POR_CREDITO` | Preço de cada crédito (padrão `1.00`) |
| `MIN_CREDITOS` / `MAX_CREDITOS` | Limites da compra (padrão `10` e `1000`) |

### Rotas da API

| Rota | Método | Descrição |
|---|---|---|
| `/api/config` | GET | Mínimo, máximo e preço por crédito |
| `/api/comprar` | POST | Cria o pedido e devolve o PIX. Corpo: `jogador`, `quantidade`, `parceiro` |
| `/api/webhook` | POST | Aviso de pagamento do Mercado Pago |
| `/api/admin/pedidos` | POST | Lista os pedidos (precisa da senha) |
| `/api/admin/confirmar` | POST | Confirma um pagamento manual (precisa da senha) |

### Testes

```bash
python -m unittest test_loja -v
```

Rodam sem internet e sem token. Cobrem validação da quantidade, preço calculado no servidor, nomes maliciosos, limite de pedidos, CORS, admin e proteção do `pedidos.json`.

### Segurança: o que não pode faltar

- Nunca coloque token, senha ou chave PIX dentro dos arquivos. Use só variáveis de ambiente.
- Não deixe `pedidos.json`, `.py` ou `.pyc` dentro da pasta pública do site.
- Defina `MP_WEBHOOK_SECRET` para o webhook conferir a assinatura do Mercado Pago.
- Se um token vazar, gere outro no painel do Mercado Pago e revogue o antigo na hora.
- Faça backup do `pedidos.json`.

## Comunidade

- TeamTalk: `netforge.ddns.net`
- Grupo do WhatsApp: link na página da parceria
- Site do DJVieon: https://radiolc.com

## Créditos

Parceria DJVieon e Net Forge Estúdios. © 2025-2026 Net Forge Estúdios. Todos os direitos reservados.
