"""
Envia alertas via Z-API (ou Evolution API).
Preencher ZAPI_INSTANCE e ZAPI_TOKEN no .env quando contratar.
"""
import os
import httpx

ZAPI_INSTANCE = os.getenv("ZAPI_INSTANCE", "")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN", "")


def enviar_mensagem(numero: str, mensagem: str) -> bool:
    """
    Envia mensagem WhatsApp para o número informado.
    numero: apenas dígitos, ex: '61999990001'
    """
    if not ZAPI_INSTANCE or not ZAPI_TOKEN:
        print(f"[WA] WhatsApp não configurado — mensagem para {numero}: {mensagem[:80]}")
        return False

    url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE}/token/{ZAPI_TOKEN}/send-text"
    payload = {
        "phone": f"55{numero}",
        "message": mensagem,
    }

    try:
        res = httpx.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"[WA] Erro ao enviar para {numero}: {e}")
        return False


def montar_alerta_perigo(nome: str, numero_processo: str, titulo_mov: str, descricao_popular: str) -> str:
    primeiro_nome = nome.split()[0] if nome else "cliente"
    return (
        f"⚠️ *ATENÇÃO, {primeiro_nome}!*\n\n"
        f"Seu processo *{numero_processo}* teve uma movimentação urgente:\n\n"
        f"📋 *{titulo_mov}*\n\n"
        f"{descricao_popular}\n\n"
        f"Fale com um advogado agora: https://meuprocesso.com.br/consulta"
    )


def montar_resumo(nome: str, numero_processo: str, movimentacoes: list[dict]) -> str:
    primeiro_nome = nome.split()[0] if nome else "cliente"
    linhas = "\n".join(
        f"• {m['data_movimentacao']} — {m['titulo'][:60]}"
        for m in movimentacoes[:5]
    )
    return (
        f"📬 *Atualização do seu processo*\n\n"
        f"Olá, {primeiro_nome}! Seu processo *{numero_processo}* teve {len(movimentacoes)} movimentação(ões):\n\n"
        f"{linhas}\n\n"
        f"Acesse seu painel: https://meuprocesso.com.br/painel"
    )
