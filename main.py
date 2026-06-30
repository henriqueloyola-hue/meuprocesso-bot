"""
Bot principal — roda todo dia às 20h (BRT) via Railway cron.

Fluxo:
1. Busca todos os processos ativos no Supabase
2. Para cada processo, abre o SEEU com certificado A1
3. Extrai movimentações novas
4. Traduz com IA (Claude Haiku)
5. Salva no banco
6. Envia alerta WhatsApp se urgente
"""
import os
import sys
from datetime import date
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from supabase import create_client

import seeu
import ia
import whatsapp

import base64
import tempfile

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
CERT_PASSWORD = os.environ["CERT_PASSWORD"]

# Suporte a certificado via base64 (Railway) ou path local
_cert_b64 = os.environ.get("CERT_PFX_BASE64", "")
if _cert_b64:
    _tmp = tempfile.NamedTemporaryFile(suffix=".pfx", delete=False)
    _tmp.write(base64.b64decode(_cert_b64))
    _tmp.close()
    CERT_PFX_PATH = _tmp.name
else:
    CERT_PFX_PATH = os.environ["CERT_PFX_PATH"]

db = create_client(SUPABASE_URL, SUPABASE_KEY)


def buscar_processos_ativos() -> list[dict]:
    res = db.table("jurito_processos").select(
        "id, numero, nivel_alerta, jurito_clientes(id, nome, whatsapp)"
    ).eq("status", "ativo").execute()
    return res.data or []


def movimentacoes_conhecidas(processo_id: str) -> set[str]:
    """Retorna títulos já salvos para evitar duplicatas."""
    res = db.table("jurito_movimentacoes").select("titulo, data_movimentacao").eq("processo_id", processo_id).execute()
    return {f"{r['data_movimentacao']}|{r['titulo']}" for r in (res.data or [])}


def salvar_movimentacao(processo_id: str, mov: dict) -> str | None:
    res = db.table("jurito_movimentacoes").insert({
        "processo_id": processo_id,
        "data_movimentacao": mov["data_movimentacao"],
        "titulo": mov["titulo"],
        "descricao_juridica": mov.get("descricao_juridica", ""),
        "descricao_popular": mov.get("descricao_popular", ""),
        "tipo": mov.get("tipo", "info"),
    }).execute()
    rows = res.data or []
    return rows[0]["id"] if rows else None


def atualizar_nivel_alerta(processo_id: str, nivel: str):
    db.table("jurito_processos").update({"nivel_alerta": nivel, "ultima_sincronia": "now()"}).eq("id", processo_id).execute()


def registrar_notificacao(cliente_id: str, mov_id: str | None, tipo: str, mensagem: str):
    db.table("jurito_notificacoes").insert({
        "cliente_id": cliente_id,
        "movimentacao_id": mov_id,
        "tipo": tipo,
        "mensagem": mensagem,
        "status": "pendente",
    }).execute()


def processar_processo(page, processo: dict, conhecidas: set[str]) -> int:
    numero = processo["numero"]
    processo_id = processo["id"]
    cliente = processo.get("jurito_clientes") or {}
    nome_cliente = cliente.get("nome", "")
    whatsapp_cliente = cliente.get("whatsapp", "")
    cliente_id = cliente.get("id", "")

    print(f"  Buscando {numero}...")
    movs = seeu.buscar_processo(page, numero)
    novas = [m for m in movs if f"{m['data_movimentacao']}|{m['titulo']}" not in conhecidas]
    print(f"  {len(novas)} movimentação(ões) nova(s)")

    nivel_mais_grave = "normal"

    for mov in novas:
        # Traduz com IA
        mov["descricao_popular"] = ia.traduzir_para_popular(
            mov["titulo"], mov.get("descricao_juridica", "")
        )

        # Salva no banco
        mov_id = salvar_movimentacao(processo_id, mov)

        # Determina nível de alerta mais grave do ciclo
        if mov["tipo"] == "perigo":
            nivel_mais_grave = "perigo"
        elif mov["tipo"] == "aviso" and nivel_mais_grave == "normal":
            nivel_mais_grave = "atencao"

        # Envia WhatsApp se perigo
        if mov["tipo"] == "perigo" and whatsapp_cliente:
            msg = whatsapp.montar_alerta_perigo(
                nome_cliente, numero, mov["titulo"], mov["descricao_popular"]
            )
            enviado = whatsapp.enviar_mensagem(whatsapp_cliente.replace(r"\D", ""), msg)
            registrar_notificacao(cliente_id, mov_id, "alerta", msg)
            print(f"  🚨 Alerta WhatsApp {'enviado' if enviado else 'registrado (WA não configurado)'}")

    # Envia resumo se tiver novas movimentações não urgentes
    if novas and nivel_mais_grave != "perigo" and whatsapp_cliente:
        msg = whatsapp.montar_resumo(nome_cliente, numero, novas)
        whatsapp.enviar_mensagem(whatsapp_cliente, msg)
        registrar_notificacao(cliente_id, None, "resumo", msg)

    # Atualiza nível de alerta do processo
    if novas:
        atualizar_nivel_alerta(processo_id, nivel_mais_grave)

    return len(novas)


def main():
    print(f"=== Bot Meu Prazo — {date.today()} ===")

    processos = buscar_processos_ativos()
    print(f"{len(processos)} processo(s) ativo(s) encontrado(s)")

    if not processos:
        print("Nada a fazer.")
        return

    total_novas = 0

    with sync_playwright() as p:
        # Contexto com certificado A1 para autenticação mútua TLS
        context = p.chromium.launch_persistent_context(
            user_data_dir="/tmp/seeu-session",
            headless=True,
            client_certificates=[{
                "origin": "https://seeu.jus.br",
                "pfxPath": CERT_PFX_PATH,
                "password": CERT_PASSWORD,
            }],
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )

        page = context.new_page()
        page.set_default_timeout(30000)

        print("Fazendo login no SEEU...")
        ok = seeu.login_com_certificado(page, CERT_PFX_PATH, CERT_PASSWORD)
        if not ok:
            print("[ERRO] Login no SEEU falhou. Verifique o certificado.")
            context.close()
            sys.exit(1)

        print("Login OK. Processando processos...")

        for processo in processos:
            try:
                conhecidas = movimentacoes_conhecidas(processo["id"])
                novas = processar_processo(page, processo, conhecidas)
                total_novas += novas
            except Exception as e:
                print(f"  [ERRO] Processo {processo.get('numero')}: {e}")
                continue

        context.close()

    print(f"\n✅ Concluído — {total_novas} movimentação(ões) nova(s) salva(s)")


if __name__ == "__main__":
    main()
