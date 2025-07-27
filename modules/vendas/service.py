# modules/vendas/service.py

from __future__ import annotations
import io
from typing import Any, Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime
import pandas as pd
import unicodedata

import streamlit as st

from utils.ca_api import api_get, api_post
from utils.token_store import has_valid_token
from utils.errors import render_error  # opcional para logs amigáveis na UI

# =========================
#  Constantes & Helpers (MÓDULO)
# =========================

# Caminho do endpoint de criação de venda.
# Por padrão, usamos a convenção v2: POST /v1/venda
# Se seu ambiente expuser /v1/sales, basta alterar esta constante via st.secrets (se preferir).
SALES_PATH = st.secrets.get("general", {}).get("SALES_PATH", "/v1/venda")

# Limites defensivos
MAX_ROWS = 2_000          # linhas de planilha (1 linha = 1 item)
MAX_ORDERS = 500          # qtd. distinta de pedidos (pedido_id)

# --- Formas de pagamento: normalização & validação ---
# Enum canônico (resumo). Se o seu tenant expuser mais, basta acrescentar aqui.
ALLOWED_PAYMENT_METHODS = {
    "PIX",
    "BOLETO_BANCARIO",
    "CARTAO_CREDITO",
    "CARTAO_DEBITO",
    "DEPOSITO_BANCARIO",
    "TRANSFERENCIA_BANCARIA",
    "DINHEIRO",
    "CARTEIRA_DIGITAL",
    "CREDITO_LOJA",
    "CHEQUE",
    # ... acrescente conforme seu tenant/enum exato
}

# Apelidos comuns → valor canônico
PAYMENT_ALIASES = {
    # PIX (qualquer banco vira PIX)
    "PIX": "PIX",
    "PIX_ITAU": "PIX", "PIX_BRADESCO": "PIX", "PIX_BB": "PIX", "PIX_CAIXA": "PIX",
    "QRCODE": "PIX", "CHAVE_PIX": "PIX",

    # BOLETO
    "BOLETO": "BOLETO_BANCARIO",
    "BOLETO_BB": "BOLETO_BANCARIO", "BOLETO_CAIXA": "BOLETO_BANCARIO",
    "BOLETO_BRADESCO": "BOLETO_BANCARIO",

    # Cartões
    "CARTAO_CREDITO": "CARTAO_CREDITO",
    "CREDITO": "CARTAO_CREDITO",
    "CARTAO_DEBITO": "CARTAO_DEBITO",
    "DEBITO": "CARTAO_DEBITO",

    # Outras linhas comuns
    "TRANSFERENCIA": "TRANSFERENCIA_BANCARIA",
    "TED": "TRANSFERENCIA_BANCARIA", "DOC": "TRANSFERENCIA_BANCARIA",
    "DEPOSITO": "DEPOSITO_BANCARIO",
    "DINHEIRO": "DINHEIRO",
    "WALLET": "CARTEIRA_DIGITAL",
}

def _normalize_token(s: str) -> str:
    s = str(s or "").strip().upper()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = s.replace("-", "_").replace(" ", "_")
    return s

def _normalize_payment_method(raw: str) -> str:
    key = _normalize_token(raw)
    if key in ALLOWED_PAYMENT_METHODS:
        return key
    if key in PAYMENT_ALIASES:
        return PAYMENT_ALIASES[key]
    # tenta combinações “BANCO” após o método (ex.: PIX_ITAU) → PIX
    if key.startswith("PIX"):
        return "PIX"
    if key.startswith("BOLETO"):
        return "BOLETO_BANCARIO"
    # falhou → erro explicativo
    allowed_preview = ", ".join(sorted(list(ALLOWED_PAYMENT_METHODS))[:8]) + ", ..."
    raise ValueError(f"Forma de pagamento inválida: '{raw}'. Use valores como: {allowed_preview}")

# -------------------------
# Modelo/Contrato de entrada
# -------------------------

"""
Modelo de planilha (1 linha = 1 ITEM da venda; pedidos com múltiplos itens
devem repetir o mesmo 'pedido_id'):

Colunas obrigatórias:
- pedido_id                 → identificador do pedido na planilha (agrupa itens)
- sale_date                 → data da venda (YYYY-MM-DD)
- customer_tipo             → FISICA | JURIDICA
- customer_nome             → nome/razão do cliente
- customer_documento        → CPF (11) se FISICA | CNPJ (14) se JURIDICA
- item_tipo                 → PRODUTO | SERVICO
- item_codigo               → SKU do produto OU código do serviço (a gente resolve o ID)
- item_quantidade           → número > 0
- item_unit_price           → número >= 0
- payment_method            → ex.: BOLETO | PIX | DINHEIRO | CARTAO_CREDITO | TRANSFERENCIA
- payment_amount            → número > 0
- payment_due_date          → YYYY-MM-DD

Colunas opcionais:
- status                    → EM_ABERTO (default) | FECHADA (ou o que seu tenant aceitar)
- shipping_cost             → frete (número >= 0, default 0)
- total_declarado           → se informado, validaremos soma(itens)+frete == total_declarado
- observacao                → observações internas

Observação: se um pedido tiver múltiplas parcelas, repita o mesmo pedido_id com as mesmas
informações de cabeçalho e itens, alterando apenas as linhas de pagamentos; o serviço agregará
por pedido_id para montar o payload final com listas de items e payments.
"""

@dataclass
class VendaItem:
    tipo: str              # PRODUTO | SERVICO
    codigo: str            # SKU/código
    quantidade: float
    unit_price: float
    id_resolvido: str | None = None  # preenchido na resolução

@dataclass
class ParcelaPagamento:
    metodo: str            # payment_method
    valor: float           # payment_amount
    vencimento: str        # YYYY-MM-DD

@dataclass
class CabecalhoVenda:
    pedido_id: str
    sale_date: str
    status: str
    cliente_tipo: str
    cliente_nome: str
    cliente_documento: str
    shipping_cost: float
    total_declarado: float | None
    observacao: str | None

@dataclass
class VendaMontada:
    header: CabecalhoVenda
    itens: List[VendaItem]
    payments: List[ParcelaPagamento]

class VendaService:
    # ---------- Geração do modelo ----------
    @staticmethod
    def gerar_modelo_planilha() -> io.BytesIO:
        df = pd.DataFrame(
            [
                {
                    "pedido_id": "PED-1001",
                    "sale_date": "2025-07-27",
                    "customer_tipo": "FISICA",
                    "customer_nome": "João da Silva",
                    "customer_documento": "12345678909",
                    "item_tipo": "PRODUTO",
                    "item_codigo": "CAMISAPOLO123",
                    "item_quantidade": 2,
                    "item_unit_price": 99.90,
                    "payment_method": "PIX",
                    "payment_amount": 199.80,
                    "payment_due_date": "2025-07-30",
                    "status": "EM_ABERTO",
                    "shipping_cost": 0,
                    "total_declarado": 199.80,
                    "observacao": "Venda exemplo",
                },
                {
                    "pedido_id": "PED-1002",
                    "sale_date": "2025-07-27",
                    "customer_tipo": "JURIDICA",
                    "customer_nome": "TechNova Soluções LTDA",
                    "customer_documento": "12345678000195",
                    "item_tipo": "SERVICO",
                    "item_codigo": "SVC-CONSULTORIA",
                    "item_quantidade": 5,
                    "item_unit_price": 150.00,
                    "payment_method": "BOLETO",
                    "payment_amount": 750.00,
                    "payment_due_date": "2025-08-05",
                    "status": "EM_ABERTO",
                    "shipping_cost": 0,
                    "total_declarado": 750.00,
                    "observacao": "",
                },
            ]
        )
        bio = io.BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="vendas")
            guia = pd.DataFrame(
                {
                    "Instruções": [
                        "1) Uma linha por ITEM. Agrupe por 'pedido_id'.",
                        "2) 'customer_documento': CPF (11 dígitos) para FISICA; CNPJ (14) para JURIDICA.",
                        "3) Datas no formato YYYY-MM-DD. Valores numéricos com ponto decimal.",
                        "4) 'item_tipo' = PRODUTO ou SERVICO; informe 'item_codigo' (SKU/código).",
                        "5) Para parcelas múltiplas, repita o 'pedido_id' alterando payment_*.",
                        "6) Se 'total_declarado' preencher, validaremos a soma.",
                    ]
                }
            )
            guia.to_excel(writer, index=False, sheet_name="LEIA-ME")
        bio.seek(0)
        return bio

    # ---------- Parsing & validação ----------
    @staticmethod
    def _to_num(val) -> float:
        if pd.isna(val) or val == "":
            return 0.0
        s = str(val).strip().replace(",", ".")
        return float(s)

    @staticmethod
    def _only_digits(s: Any) -> str:
        return "".join(ch for ch in str(s) if ch.isdigit())

    @classmethod
    def parse_planilha(cls, file) -> pd.DataFrame:
        try:
            df = pd.read_excel(file)
        except Exception:
            file.seek(0)
            df = pd.read_csv(file)

        df.columns = [c.strip().lower() for c in df.columns]

        obrig = [
            "pedido_id", "sale_date", "customer_tipo", "customer_nome", "customer_documento",
            "item_tipo", "item_codigo", "item_quantidade", "item_unit_price",
            "payment_method", "payment_amount", "payment_due_date"
        ]
        faltando = [c for c in obrig if c not in df.columns]
        if faltando:
            raise ValueError(f"Colunas obrigatórias ausentes: {', '.join(faltando)}")

        if len(df) > MAX_ROWS:
            raise ValueError(f"Limite de {MAX_ROWS} linhas excedido.")

        df["pedido_id"] = df["pedido_id"].astype(str).str.strip()

        for col in ["item_quantidade", "item_unit_price", "payment_amount", "shipping_cost", "total_declarado"]:
            if col in df.columns:
                df[col] = df[col].apply(cls._to_num)

        for col in ["sale_date", "payment_due_date"]:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")

        df["customer_documento"] = df["customer_documento"].apply(cls._only_digits)

        if "status" not in df.columns:
            df["status"] = "EM_ABERTO"
        if "shipping_cost" not in df.columns:
            df["shipping_cost"] = 0.0
        if "observacao" not in df.columns:
            df["observacao"] = ""

        return df

    # ---------- Resolução de IDs (produto/serviço) ----------
    @staticmethod
    def _resolve_produto_id(codigo: str) -> str | None:
        try:
            data = api_get("/v1/produto", params={"codigo_sku": codigo})
            if isinstance(data, dict):
                itens = data.get("itens") or data.get("data") or data.get("items")
                if isinstance(itens, list) and itens:
                    for p in itens:
                        pid = p.get("id") or p.get("identificador") or p.get("identificador_legado")
                        if pid:
                            return str(pid)
        except Exception:
            pass

        try:
            data = api_get("/v1/products", params={"code": codigo})
            if isinstance(data, list) and data:
                pid = data[0].get("id")
                if pid:
                    return str(pid)
            elif isinstance(data, dict):
                itens = data.get("data") or []
                if itens:
                    return str(itens[0].get("id"))
        except Exception:
            pass

        return None

    @staticmethod
    def _resolve_servico_id(codigo: str) -> str | None:
        try:
            data = api_get("/v1/servicos", params={"codigo": codigo})
            if isinstance(data, dict):
                itens = data.get("itens") or data.get("data") or data.get("items")
                if isinstance(itens, list) and itens:
                    sid = itens[0].get("id")
                    if sid:
                        return str(sid)
            elif isinstance(data, list) and data:
                return str(data[0].get("id"))
        except Exception:
            pass
        return None

    # ---------- Busca/criação de pessoa ----------
    @staticmethod
    def _buscar_pessoa_por_documento(documento: str) -> dict | None:
        try:
            data = api_get("/v1/pessoas", params={"documento": documento})
            if isinstance(data, dict):
                itens = data.get("data") or data.get("items") or data.get("itens") or []
            else:
                itens = data or []
            for p in itens:
                doc = (p.get("cpf") or p.get("cnpj") or p.get("documento") or "").replace(".", "").replace("-", "").replace("/", "")
                if doc == documento:
                    return p
        except Exception:
            pass

        for key in ("cpf", "cnpj"):
            try:
                data = api_get("/v1/pessoas", params={key: documento})
                itens = data.get("data") if isinstance(data, dict) else data
                itens = itens or []
                for p in itens:
                    doc = (p.get("cpf") or p.get("cnpj") or p.get("documento") or "").replace(".", "").replace("-", "").replace("/", "")
                    if doc == documento:
                        return p
            except Exception:
                pass
        return None

    @staticmethod
    def _criar_pessoa_minima(tipo: str, nome: str, documento: str) -> dict:
        payload = {
            "perfis": [{"tipo_perfil": "CLIENTE"}],
            "tipo_pessoa": "FISICA" if len(documento) == 11 else "JURIDICA",
            "nome": nome,
        }
        if len(documento) == 11:
            payload["cpf"] = documento
        else:
            payload["cnpj"] = documento

        return api_post("/v1/pessoa", json=payload)

    @classmethod
    def _resolve_or_create_customer(cls, tipo: str, nome: str, documento: str) -> dict:
        pessoa = cls._buscar_pessoa_por_documento(documento)
        if not pessoa:
            pessoa = cls._criar_pessoa_minima(tipo, nome, documento)

        pessoa_id = pessoa.get("id") or pessoa.get("identificador") or pessoa.get("identificador_legado")
        if not pessoa_id:
            return {"type": tipo, "name": nome, "document": documento}
        return {"id": pessoa_id}

    # ---------- Montagem por pedido ----------
    @classmethod
    def _montar_por_pedido(cls, df: pd.DataFrame) -> Tuple[List[VendaMontada], pd.DataFrame]:
        results: List[VendaMontada] = []
        erros: List[Dict[str, Any]] = []

        pedidos = df["pedido_id"].unique().tolist()
        if len(pedidos) > MAX_ORDERS:
            raise ValueError(f"Limite de {MAX_ORDERS} pedidos excedido.")

        for pid in pedidos:
            bloco = df[df["pedido_id"] == pid]
            r0 = bloco.iloc[0].to_dict()
            try:
                header = CabecalhoVenda(
                    pedido_id=pid,
                    sale_date=str(r0["sale_date"]),
                    status=str(r0.get("status", "EM_ABERTO") or "EM_ABERTO"),
                    cliente_tipo=str(r0["customer_tipo"]).upper().strip(),
                    cliente_nome=str(r0["customer_nome"]).strip(),
                    cliente_documento=str(r0["customer_documento"]).strip(),
                    shipping_cost=float(r0.get("shipping_cost", 0.0) or 0.0),
                    total_declarado=float(r0["total_declarado"]) if "total_declarado" in r0 and r0["total_declarado"] not in ("", None) else None,
                    observacao=str(r0.get("observacao", "") or ""),
                )

                if header.cliente_tipo not in ("FISICA", "JURIDICA", "ESTRANGEIRA"):
                    raise ValueError("customer_tipo inválido (use FISICA/JURIDICA/ESTRANGEIRA).")
                if header.cliente_tipo == "FISICA" and len(header.cliente_documento) != 11:
                    raise ValueError("CPF inválido: use 11 dígitos.")
                if header.cliente_tipo == "JURIDICA" and len(header.cliente_documento) != 14:
                    raise ValueError("CNPJ inválido: use 14 dígitos.")
                datetime.strptime(header.sale_date, "%Y-%m-%d")

                itens: List[VendaItem] = []
                total_itens = 0.0
                for _, row in bloco.iterrows():
                    it = VendaItem(
                        tipo=str(row["item_tipo"]).upper().strip(),
                        codigo=str(row["item_codigo"]).strip(),
                        quantidade=float(row["item_quantidade"]),
                        unit_price=float(row["item_unit_price"]),
                    )
                    if it.tipo not in ("PRODUTO", "SERVICO"):
                        raise ValueError(f"item_tipo inválido em {pid}: {it.tipo}")
                    if it.quantidade <= 0:
                        raise ValueError(f"item_quantidade deve ser > 0 no pedido {pid}")
                    if it.unit_price < 0:
                        raise ValueError(f"item_unit_price deve ser >= 0 no pedido {pid}")
                    total_itens += it.quantidade * it.unit_price
                    itens.append(it)

                payments: List[ParcelaPagamento] = []
                soma_pag = 0.0
                for _, row in bloco.iterrows():
                    pm = ParcelaPagamento(
                        metodo=str(row["payment_method"]).upper().strip(),
                        valor=float(row["payment_amount"]),
                        vencimento=str(row["payment_due_date"]),
                    )
                    if pm.valor <= 0:
                        raise ValueError(f"payment_amount deve ser > 0 no pedido {pid}")
                    datetime.strptime(pm.vencimento, "%Y-%m-%d")
                    soma_pag += pm.valor
                    payments.append(pm)

                total_calc = round(total_itens + header.shipping_cost, 2)

                if header.total_declarado is not None:
                    if round(header.total_declarado, 2) != total_calc:
                        raise ValueError(
                            f"total_declarado ({header.total_declarado}) difere da soma (itens+frete={total_calc}) no pedido {pid}"
                        )

                if round(soma_pag, 2) != total_calc:
                    raise ValueError(
                        f"Soma dos pagamentos ({round(soma_pag,2)}) difere do total calculado ({total_calc}) no pedido {pid}"
                    )

                results.append(VendaMontada(header=header, itens=itens, payments=payments))

            except Exception as e:
                erros.append({"pedido_id": pid, "erro": str(e)})

        return results, (pd.DataFrame(erros) if erros else pd.DataFrame(columns=["pedido_id", "erro"]))

    # ---------- Resolução de IDs e payload final ----------
    @classmethod
    def _resolver_itens_e_payload(cls, venda: VendaMontada) -> Dict[str, Any]:
        itens_payload = []
        for it in venda.itens:
            if it.tipo == "PRODUTO":
                pid = cls._resolve_produto_id(it.codigo)
                if not pid:
                    raise ValueError(f"Produto não encontrado para código '{it.codigo}'.")
                itens_payload.append({"product_id": pid, "quantity": it.quantidade, "unit_price": it.unit_price})
            else:
                sid = cls._resolve_servico_id(it.codigo)
                if not sid:
                    raise ValueError(f"Serviço não encontrado para código '{it.codigo}'.")
                itens_payload.append({"service_id": sid, "quantity": it.quantidade, "unit_price": it.unit_price})

        payments_payload = [
            {
                "payment_method": _normalize_payment_method(p.metodo),  # normaliza/valida (helpers do MÓDULO)
                "amount": p.valor,
                "due_date": p.vencimento
            }
            for p in venda.payments
        ]

        customer = cls._resolve_or_create_customer(
            tipo=venda.header.cliente_tipo,
            nome=venda.header.cliente_nome,
            documento=venda.header.cliente_documento,
        )

        payload = {
            "customer": customer,
            "items": itens_payload,
            "payments": payments_payload,
            "sale_date": venda.header.sale_date,
            "status": venda.header.status,
            "shipping_cost": venda.header.shipping_cost,
        }
        if venda.header.observacao:
            payload["note"] = venda.header.observacao

        return payload

    # ---------- Execução em massa ----------
    @classmethod
    def processar_upload(cls, file) -> Dict[str, Any]:
        if not has_valid_token():
            raise RuntimeError("Token de acesso inválido ou expirado. Faça login novamente.")

        df = cls.parse_planilha(file)
        vendas, erros_montagem_df = cls._montar_por_pedido(df)

        resultados: List[Dict[str, Any]] = []
        for venda in vendas:
            try:
                payload = cls._resolver_itens_e_payload(venda)
                resp = api_post(SALES_PATH, json=payload)
                sale_id = resp.get("id") or resp.get("identificador") or resp.get("sale_id")
                resultados.append(
                    {
                        "pedido_id": venda.header.pedido_id,
                        "status": "criada",
                        "sale_id": sale_id,
                        "mensagem": "Venda criada com sucesso",
                    }
                )
            except Exception as e:
                resultados.append(
                    {
                        "pedido_id": venda.header.pedido_id,
                        "status": "erro",
                        "sale_id": None,
                        "mensagem": str(e),
                    }
                )

        df_result = pd.DataFrame(resultados)
        resumo = {
            "total_pedidos": len(vendas),
            "sucesso": int((df_result["status"] == "criada").sum()),
            "erros": int((df_result["status"] == "erro").sum()),
        }

        return {
            "resumo": resumo,
            "resultado_df": df_result,
            "erros_montagem_df": erros_montagem_df,
        }
