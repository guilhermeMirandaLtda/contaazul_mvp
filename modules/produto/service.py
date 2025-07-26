# modules/produto/service.py

import pandas as pd
import re
from utils.ca_api import api_get, api_post
from utils.token_store import has_valid_token

class ProdutoService:
    CAMPOS_OBRIGATORIOS = [
        "nome", "codigo_sku", "formato", "valor_venda",
        "custo_medio", "estoque_disponivel", "estoque_minimo", "estoque_maximo",
        "altura", "largura", "profundidade"
    ]

    CAMPOS_VALIDOS = CAMPOS_OBRIGATORIOS + [
        "codigo_ean", "observacao", "condicao", "integracao_habilitada",
        "descricao", "titulo_seo", "url_seo"
    ]

    def __init__(self, token=None):
        # token mantido como opcional para não quebrar chamadas antigas; não é usado.
        self.token = token

    @staticmethod
    def _to_float(val):
        """
        Converte valores numéricos de planilha:
        - '99,9' -> 99.9
        - ''/None -> 0.0
        - '  10 ' -> 10.0
        """
        if val is None:
            return 0.0
        s = str(val).strip()
        if s == "" or s.lower() == "nan":
            return 0.0
        s = s.replace(".", "").replace(",", ".") if re.match(r"^\d{1,3}(\.\d{3})*(,\d+)?$", s) else s.replace(",", ".")
        try:
            return float(s)
        except Exception:
            return 0.0

    @staticmethod
    def _to_bool(val):
        return str(val).strip().upper() in {"VERDADEIRO", "TRUE", "SIM", "1", "YES"}

    def validar_planilha(self, df: pd.DataFrame):
        df.columns = df.columns.str.strip().str.lower()
        erros = []
        for campo in self.CAMPOS_OBRIGATORIOS:
            if campo not in df.columns:
                erros.append(f"Campo obrigatório ausente: {campo}")
        if len(df) > 500:
            erros.append("Limite máximo de 500 linhas por importação.")
        return erros

    def verificar_existencia(self, nome: str, sku: str) -> bool:
        """
        Verifica existência por SKU e, em fallback, por nome.
        Considera normalização de espaços/case.
        """
        nome_norm = re.sub(r"\s+", " ", (nome or "").strip()).lower()
        sku_norm = (sku or "").strip()

        # 1) Tenta por SKU (mais confiável)
        try:
            resp = api_get("/v1/produto/busca", params={"codigo_sku": sku_norm}) if sku_norm else {}
            itens = resp.get("data", resp) if isinstance(resp, dict) else resp
            if isinstance(itens, list) and len(itens) > 0:
                return True
        except Exception:
            pass

        # 2) Fallback por nome
        try:
            if nome_norm:
                resp = api_get("/v1/produto/busca", params={"nome": nome_norm})
                itens = resp.get("data", resp) if isinstance(resp, dict) else resp
                if isinstance(itens, list):
                    for p in itens:
                        n = str(p.get("nome", "")).strip().lower()
                        if n == nome_norm:
                            return True
        except Exception:
            pass

        return False

    def _payload_produto(self, produto: dict) -> dict:
        return {
            "nome": produto["nome"],
            "codigo_sku": produto["codigo_sku"],
            "codigo_ean": produto.get("codigo_ean", ""),
            "observacao": produto.get("observacao", ""),
            "formato": produto["formato"],  # "SIMPLES" ou "VARIACAO"
            "estoque": {
                "valor_venda": self._to_float(produto["valor_venda"]),
                "custo_medio": self._to_float(produto["custo_medio"]),
                "estoque_disponivel": self._to_float(produto["estoque_disponivel"]),
                "estoque_minimo": self._to_float(produto["estoque_minimo"]),
                "estoque_maximo": self._to_float(produto["estoque_maximo"]),
            },
            "dimensao": {
                "altura": self._to_float(produto["altura"]),
                "largura": self._to_float(produto["largura"]),
                "profundidade": self._to_float(produto["profundidade"]),
            },
            "ecommerce": {
                "condicao": produto.get("condicao", "NOVO"),
                "integracao_habilitada": self._to_bool(produto.get("integracao_habilitada", False)),
                "descricao": produto.get("descricao", ""),
                "titulo_seo": produto.get("titulo_seo", ""),
                "url_seo": produto.get("url_seo", ""),
            }
        }

    def cadastrar_produto(self, produto: dict):
        payload = self._payload_produto(produto)
        # Chamada real à API v2 (ajuste o endpoint caso seu contrato use outro path):
        resp = api_post("/v1/produto", json=payload)
        return True, resp  # mantenho contrato (sucesso, mensagem/objeto)

    def processar_upload(self, arquivo_excel):

        df = pd.read_excel(arquivo_excel)
        erros_planilha = self.validar_planilha(df)
        if erros_planilha:
            return {"status": "erro", "mensagem": "Erros na planilha", "resumo": [], "erros": erros_planilha}

        resultados = []

        for _, row in df.iterrows():
            produto = {k: row.get(k) for k in df.columns}
            nome = produto.get("nome")
            sku = produto.get("codigo_sku")

            # 1) Existência
            try:
                if self.verificar_existencia(nome, sku):
                    resultados.append({
                        "produto": nome,
                        "sku": sku,
                        "status": "Ignorado",
                        "mensagem": "Já existe (encontrado por SKU/Nome)."
                    })
                    continue
            except Exception as e:
                resultados.append({
                    "produto": nome,
                    "sku": sku,
                    "status": "Erro",
                    "mensagem": f"Falha ao verificar existência: {e}"
                })
                continue

            # 2) Cadastro
            try:
                ok, msg = self.cadastrar_produto(produto)
                resultados.append({
                    "produto": nome,
                    "sku": sku,
                    "status": "Cadastrado" if ok else "Erro",
                    "mensagem": msg if isinstance(msg, str) else "OK"
                })
            except Exception as e:
                resultados.append({
                    "produto": nome,
                    "sku": sku,
                    "status": "Erro",
                    "mensagem": str(e)
                })

        return {"status": "ok", "resumo": resultados, "erros": []}
