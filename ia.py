"""
Traduz jargão jurídico para linguagem popular usando Claude.
"""
import os
import httpx

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def traduzir_para_popular(titulo: str, descricao_juridica: str) -> str:
    """
    Recebe o título e texto jurídico de uma movimentação.
    Retorna explicação em português simples para o cliente.
    """
    if not ANTHROPIC_KEY:
        return descricao_juridica[:300] if descricao_juridica else titulo

    prompt = (
        "Você é um assistente que explica processos judiciais para pessoas sem conhecimento jurídico. "
        "Traduza a movimentação abaixo em 2-3 frases curtas, linguagem simples, sem juridiquês. "
        "Se for urgente, deixe isso claro. Responda apenas com a explicação, sem introdução.\n\n"
        f"Movimentação: {titulo}\n"
        f"Texto: {descricao_juridica[:800]}"
    )

    try:
        res = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        data = res.json()
        return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"[IA] Erro ao traduzir: {e}")
        return titulo
