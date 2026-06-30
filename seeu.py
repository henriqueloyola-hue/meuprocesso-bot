"""
Raspa movimentações do SEEU usando certificado digital A1.
Roda no Railway via cron todo dia às 20h (BRT).
"""
import os
import re
import json
from datetime import date
from playwright.sync_api import sync_playwright, Page

SEEU_URL = "https://seeu.jus.br/seeu/login.faces"


def login_com_certificado(page: Page, pfx_path: str, pfx_senha: str) -> bool:
    """Abre o SEEU e autentica via certificado A1."""
    page.goto(SEEU_URL, wait_until="networkidle", timeout=30000)

    # O SEEU usa autenticação mútua TLS — o Playwright passa o cert via contexto.
    # Se a página pedir seleção de certificado no browser, clicamos no primeiro.
    try:
        # Alguns tribunais mostram tela de seleção de cert
        page.wait_for_selector("button:has-text('Certificado')", timeout=5000)
        page.click("button:has-text('Certificado')")
    except Exception:
        pass

    # Aguarda carregar o painel principal após autenticação
    try:
        page.wait_for_selector("#formPrincipal, #mainContent, .painel-principal", timeout=20000)
        return True
    except Exception:
        return False


def buscar_processo(page: Page, numero: str) -> list[dict]:
    """
    Navega para a tela de consulta de processo e extrai movimentações.
    Retorna lista de movimentações encontradas.
    """
    movimentacoes = []

    try:
        # Menu: Processo > Consultar
        page.click("a:has-text('Processo')", timeout=10000)
        page.click("a:has-text('Consultar')", timeout=10000)
        page.wait_for_load_state("networkidle")

        # Campo de número do processo (formato CNJ: 0000000-00.0000.0.00.0000)
        campo = page.query_selector("input[id*='numero'], input[name*='numero'], input[placeholder*='processo']")
        if not campo:
            print(f"[ERRO] Campo de número não encontrado para {numero}")
            return []

        campo.fill(numero)
        page.keyboard.press("Enter")
        page.wait_for_load_state("networkidle")

        # Extrai movimentações da tabela de andamentos
        linhas = page.query_selector_all("table.andamentos tr, tr.andamento, .movimento-item")
        for linha in linhas:
            cols = linha.query_selector_all("td")
            if len(cols) < 2:
                continue

            data_str = cols[0].inner_text().strip()
            titulo = cols[1].inner_text().strip()
            descricao = cols[2].inner_text().strip() if len(cols) > 2 else ""

            if not titulo:
                continue

            # Converte data BR para ISO
            data_iso = _parse_data(data_str)

            movimentacoes.append({
                "data_movimentacao": data_iso,
                "titulo": titulo[:500],
                "descricao_juridica": descricao[:2000],
                "tipo": _classificar_tipo(titulo),
            })

    except Exception as e:
        print(f"[ERRO] Falha ao buscar processo {numero}: {e}")

    return movimentacoes


def _parse_data(data_str: str) -> str:
    """Converte '18/06/2026' para '2026-06-18'. Retorna hoje se não conseguir."""
    try:
        partes = re.findall(r"\d+", data_str)
        if len(partes) >= 3:
            d, m, a = partes[0], partes[1], partes[2]
            return f"{a}-{m.zfill(2)}-{d.zfill(2)}"
    except Exception:
        pass
    return str(date.today())


def _classificar_tipo(titulo: str) -> str:
    """Classifica a movimentação como perigo / aviso / ok / info."""
    titulo_lower = titulo.lower()
    perigo = ["mandado de prisão", "decreto de prisão", "revogação de", "suspensão", "expedido mandado", "localização"]
    aviso = ["audiência", "intimação", "prazo", "edital", "notificação"]
    ok = ["progressão", "livramento", "extinção", "cumprida", "baixa", "habilitado", "advogado"]

    for p in perigo:
        if p in titulo_lower:
            return "perigo"
    for a in aviso:
        if a in titulo_lower:
            return "aviso"
    for o in ok:
        if o in titulo_lower:
            return "ok"
    return "info"
