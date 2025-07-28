# modules/vendas/service.py

from __future__ import annotations
import io
from typing import Any, Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime
import pandas as pd
import unicodedata
import re

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

# --- Adicione helpers próximos das constantes ---
def _norm_colname(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")

# PT-BR (normalizado) → nome interno (inglês) já usado pelo serviço
PTBR_TO_INTERNAL = {
    "numero": "pedido_id",
    "data_da_venda": "sale_date",
    "situacao": "status",
    "tipo_do_cliente": "customer_tipo",
    "nome_do_cliente": "customer_nome",
    "documento_do_cliente": "customer_documento",
    "observacoes": "observacao",
    "custo_de_frete": "shipping_cost",
    "tipo_do_item": "item_tipo",
    "codigo_do_item": "item_codigo",
    "quantidade": "item_quantidade",
    "valor_unitario": "item_unit_price",
    "metodo_de_pagamento": "payment_method",
    "valor_da_parcela": "payment_amount",
    "vencimento_da_parcela": "payment_due_date",
    "conta_financeira_id": "id_conta_financeira",
}

# Também aceitamos os nomes antigos (inglês)
IDENTITY_INTERNAL = {
    "pedido_id": "pedido_id",
    "sale_date": "sale_date",
    "status": "status",
    "customer_tipo": "customer_tipo",
    "customer_nome": "customer_nome",
    "customer_documento": "customer_documento",
    "observacao": "observacao",
    "shipping_cost": "shipping_cost",
    "item_tipo": "item_tipo",
    "item_codigo": "item_codigo",
    "item_quantidade": "item_quantidade",
    "item_unit_price": "item_unit_price",
    "payment_method": "payment_method",
    "payment_amount": "payment_amount",
    "payment_due_date": "payment_due_date",
    "id_conta_financeira": "id_conta_financeira",
    "total_declarado": "total_declarado",
}

def _rename_columns_ptbr(df: pd.DataFrame) -> pd.DataFrame:
    renamed = {}
    for c in df.columns:
        key = _norm_colname(c)
        internal = (
            PTBR_TO_INTERNAL.get(key) or
            IDENTITY_INTERNAL.get(key) or
            key  # fallback: mantém normalizado (não deve quebrar obrigatórios)
        )
        renamed[c] = internal
    return df.rename(columns=renamed)

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
    pedido_id: str                          # pedido_id
    sale_date: str                          # YYYY-MM-DD
    status: str                             # EM_ABERTO | PAGO
    cliente_tipo: str                       # FISICA | JURIDICA
    cliente_nome: str                       # Nome completo
    cliente_documento: str                  # CPF | CNPJ
    shipping_cost: float                    # custo_de_frete
    total_declarado: float | None           # total_declarado
    observacao: str | None                  # observacoes
    conta_financeira_id: str | None = None  # preenchido na resolução

@dataclass
class VendaMontada:
    header: CabecalhoVenda
    itens: List[VendaItem]
    payments: List[ParcelaPagamento]

class VendaService:
    # ---------- Geração do modelo ----------
    @staticmethod
    def gerar_modelo_planilha() -> io.BytesIO:
        from datetime import date, timedelta
        today = date.today()

        # Duas amostras: 1 à vista (PIX) e 3 parcelas (BOLETO)
        df = pd.DataFrame([
            {
                "Número*": "1001",
                "Data da Venda*": today.strftime("%Y-%m-%d"),
                "Situação*": "EM_ANDAMENTO",
                "Tipo do Cliente*": "FISICA",
                "Nome do Cliente*": "Ana Paula Ribeiro",
                "Documento do Cliente*": "12345678909",
                "Observações": "",
                "Custo de Frete": 0.00,
                "Tipo do Item*": "SERVICO",
                "Código do Item*": "SVC-001",
                "Quantidade*": 1,
                "Valor Unitário*": 150.00,
                "Método de Pagamento*": "PIX",
                "Valor da Parcela*": 150.00,
                "Vencimento da Parcela*": today.strftime("%Y-%m-%d"),
                "Conta Financeira (ID)": "",
            },
            {
                "Número*": "1002",
                "Data da Venda*": today.strftime("%Y-%m-%d"),
                "Situação*": "APROVADO",
                "Tipo do Cliente*": "JURIDICA",
                "Nome do Cliente*": "Empresa XPTO Ltda",
                "Documento do Cliente*": "12345678000199",
                "Observações": "Pedido parcelado em 3x boleto.",
                "Custo de Frete": 0.00,
                "Tipo do Item*": "PRODUTO",
                "Código do Item*": "PRD-001",
                "Quantidade*": 2,
                "Valor Unitário*": 100.00,
                "Método de Pagamento*": "BOLETO_BANCARIO",
                "Valor da Parcela*": 200.00,
                "Vencimento da Parcela*": (today + timedelta(days=30)).strftime("%Y-%m-%d"),
                "Conta Financeira (ID)": "",
            },
            {
                "Número*": "1002",
                "Data da Venda*": today.strftime("%Y-%m-%d"),
                "Situação*": "APROVADO",
                "Tipo do Cliente*": "JURIDICA",
                "Nome do Cliente*": "Empresa XPTO Ltda",
                "Documento do Cliente*": "12345678000199",
                "Observações": "",
                "Custo de Frete": 0.00,
                "Tipo do Item*": "PRODUTO",
                "Código do Item*": "PRD-001",
                "Quantidade*": 2,
                "Valor Unitário*": 100.00,
                "Método de Pagamento*": "BOLETO_BANCARIO",
                "Valor da Parcela*": 200.00,
                "Vencimento da Parcela*": (today + timedelta(days=60)).strftime("%Y-%m-%d"),
                "Conta Financeira (ID)": "",
            },
            {
                "Número*": "1002",
                "Data da Venda*": today.strftime("%Y-%m-%d"),
                "Situação*": "APROVADO",
                "Tipo do Cliente*": "JURIDICA",
                "Nome do Cliente*": "Empresa XPTO Ltda",
                "Documento do Cliente*": "12345678000199",
                "Observações": "",
                "Custo de Frete": 0.00,
                "Tipo do Item*": "PRODUTO",
                "Código do Item*": "PRD-001",
                "Quantidade*": 2,
                "Valor Unitário*": 100.00,
                "Método de Pagamento*": "BOLETO_BANCARIO",
                "Valor da Parcela*": 200.00,
                "Vencimento da Parcela*": (today + timedelta(days=90)).strftime("%Y-%m-%d"),
                "Conta Financeira (ID)": "",
            },
        ])

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="VENDAS")

            guia = pd.DataFrame({
                "Instruções": [
                    "1) Uma linha por ITEM. Agrupe por 'Número'.",
                    "2) Documento do Cliente: CPF (11) / CNPJ (14) — apenas dígitos.",
                    "3) Datas no formato YYYY-MM-DD; valores com ponto decimal.",
                    "4) Tipo do Item: PRODUTO ou SERVICO; informe o Código do Item (SKU/código).",
                    "5) Para parcelas, repita o mesmo 'Número' mudando Método/Valor/Vencimento.",
                    "6) Soma das parcelas deve ser igual à soma dos itens + frete.",
                ]
            })
            guia.to_excel(writer, index=False, sheet_name="LEIA-ME")

            mapa = pd.DataFrame([
                ("Número", "pedido_id"),
                ("Data da Venda", "sale_date"),
                ("Situação", "status"),
                ("Tipo do Cliente", "customer_tipo"),
                ("Nome do Cliente", "customer_nome"),
                ("Documento do Cliente", "customer_documento"),
                ("Observações", "observacao"),
                ("Custo de Frete", "shipping_cost"),
                ("Tipo do Item", "item_tipo"),
                ("Código do Item", "item_codigo"),
                ("Quantidade", "item_quantidade"),
                ("Valor Unitário", "item_unit_price"),
                ("Método de Pagamento", "payment_method"),
                ("Valor da Parcela", "payment_amount"),
                ("Vencimento da Parcela", "payment_due_date"),
                ("Conta Financeira (ID)", "id_conta_financeira"),
            ], columns=["Título (PT-BR)", "Nome Interno"])
            mapa.to_excel(writer, index=False, sheet_name="MAPEAMENTO")

        buffer.seek(0)
        return buffer



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

        # 1) Renomeia colunas PT-BR/EN para nomes internos
        df = _rename_columns_ptbr(df)

        # 2) Lower-case NÃO é mais necessário porque já mapeamos
        # df.columns = [c.strip().lower() for c in df.columns]  # REMOVA

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
    def _resolve_or_create_customer(cls, tipo: str, nome: str, documento: str) -> str:
        """
        Retorna SEMPRE o UUID do cliente para uso em id_cliente.
        Se não encontrar, tenta criar o cliente mínimo.
        Se ainda assim não obtiver ID, lança ValueError (interrompe a venda).
        """
        pessoa = cls._buscar_pessoa_por_documento(documento)
        if not pessoa:
            pessoa = cls._criar_pessoa_minima(tipo, nome, documento)

        pessoa_id = (
            pessoa.get("id")
            or pessoa.get("uuid")
            or pessoa.get("identificador")
            or pessoa.get("identificador_legado")
        )
        if not pessoa_id:
            raise ValueError(
                "Não foi possível obter o ID do cliente. "
                "Verifique o CPF/CNPJ e tente novamente."
            )
        return str(pessoa_id)


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
                    conta_financeira_id=(str(r0.get("id_conta_financeira", "")).strip() or None),
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
        # -------- 1) Resolver itens -> itens[].{id, quantidade, valor} --------
        itens_payload = []
        for it in venda.itens:
            if it.tipo == "PRODUTO":
                resolved = cls._resolve_produto_id(it.codigo)
                if not resolved:
                    raise ValueError(f"Produto não encontrado para código '{it.codigo}'.")
            else:
                resolved = cls._resolve_servico_id(it.codigo)
                if not resolved:
                    raise ValueError(f"Serviço não encontrado para código '{it.codigo}'.")
            itens_payload.append({
                "id": str(resolved),
                "quantidade": float(it.quantidade),
                "valor": float(it.unit_price),
            })

        if not itens_payload:
            raise ValueError("Nenhum item informado para a venda.")

        # -------- 2) Condição de pagamento --------
        if not venda.payments:
            raise ValueError("É obrigatório informar ao menos uma parcela de pagamento.")

        # Normaliza e valida meios de pagamento — todos devem ser o MESMO tipo por venda
        metodos_norm = {
            cls._normalize_payment_method(p.metodo)
            for p in venda.payments
        }
        if None in metodos_norm:
            raise ValueError("Forma de pagamento inválida na planilha.")
        if len(metodos_norm) != 1:
            raise ValueError(
                "A venda contém múltiplas formas de pagamento. "
                "Agrupe por pedido_id para manter um único tipo por venda."
            )
        tipo_pagamento = metodos_norm.pop()

        # Parcelas
        parcelas = []
        for p in venda.payments:
            # validação básica (o serviço já valida somas)
            if float(p.valor) <= 0:
                raise ValueError("Valor de parcela deve ser > 0.")
            parcelas.append({
                "data_vencimento": str(p.vencimento),
                "valor": float(p.valor),
            })

        # Inferir opcao_condicao_pagamento: "À vista" | "Nx" | "30, 60, 90"
        opcao = cls._infer_opcao_condicao_pagamento(
            data_venda=venda.header.sale_date,
            parcelas=parcelas,
        )

        # id_conta_financeira (opcional) via secrets
        id_conta_financeira = (
            st.secrets.get("contaazul", {}).get("id_conta_financeira")
            if hasattr(st, "secrets") else None
        )

        condicao_pagamento = {
            "tipo_pagamento": tipo_pagamento,
            "opcao_condicao_pagamento": opcao,
            "parcelas": parcelas,
        }
        if id_conta_financeira:
            condicao_pagamento["id_conta_financeira"] = str(id_conta_financeira)

        # -------- 3) Cliente (ID) --------
        cliente_id = cls._resolve_or_create_customer(
            tipo=venda.header.cliente_tipo,
            nome=venda.header.cliente_nome,
            documento=venda.header.cliente_documento,
        )

        # -------- 4) Numero (OBRIGATÓRIO) --------
        # regra: extrair dígitos do pedido_id; se não houver, falha amigável
        so_digitos = "".join(ch for ch in str(venda.header.pedido_id) if ch.isdigit())
        if not so_digitos:
            raise ValueError(
                f"numero (inteiro) é obrigatório. Informe 'numero' na planilha ou "
                f"use pedido_id com dígitos (ex: PED-1001). Pedido: {venda.header.pedido_id}"
            )
        numero = int(so_digitos)

        # -------- 5) Situacao/Data/Frete/Obs --------
        situacao = str(venda.header.status or "").upper().strip()
        # contrato aceita EM_ANDAMENTO | APROVADO (demais para PUT)
        if situacao in ("", "EM_ABERTO"):
            situacao = "EM_ANDAMENTO"

        payload: Dict[str, Any] = {
            "id_cliente": str(cliente_id),
            "numero": numero,
            "data_venda": str(venda.header.sale_date),
            "situacao": situacao,
            "itens": itens_payload,
            "condicao_pagamento": condicao_pagamento,
        }

        # Frete aninhado
        frete = float(venda.header.shipping_cost or 0)
        if frete > 0:
            payload["composicao_de_valor"] = {"frete": frete}

        # Observação
        if venda.header.observacao:
            payload["observacoes"] = str(venda.header.observacao)

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

    
    # ---------- Auxiliares ----------
    @staticmethod
    def _infer_opcao_condicao_pagamento(data_venda: str, parcelas: List[Dict[str, Any]]) -> str:
        from datetime import datetime as _dt
        if not parcelas:
            return "À vista"

        if len(parcelas) == 1:
            return "À vista"

        # Verifica se todas as parcelas têm o mesmo valor (duas casas)
        valores = [round(float(p["valor"]), 2) for p in parcelas]
        valores_iguais = all(abs(v - valores[0]) < 0.01 for v in valores)

        if valores_iguais:
            return f"{len(parcelas)}x"

        # Caso geral: offsets em dias
        try:
            base = _dt.strptime(str(data_venda), "%Y-%m-%d").date()
            offsets = []
            for p in parcelas:
                dtv = _dt.strptime(str(p["data_vencimento"]), "%Y-%m-%d").date()
                offsets.append((dtv - base).days)
            offsets = [str(max(0, d)) for d in offsets]
            return ", ".join(offsets)
        except Exception:
            # fallback seguro
            return f"{len(parcelas)}x"

