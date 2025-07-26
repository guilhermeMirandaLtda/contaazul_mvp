# modules/produto/service.py

import pandas as pd
import io
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

    def __init__(self, token):
        self.token = token

    def str_para_bool(self, valor):
        return str(valor).strip().upper() in ["VERDADEIRO", "TRUE", "SIM"]

    def validar_planilha(self, df):
        df.columns = df.columns.str.strip().str.lower()
        erros = []
        for campo in self.CAMPOS_OBRIGATORIOS:
            if campo not in df.columns:
                erros.append(f"Campo obrigatório ausente: {campo}")
        return erros

    def verificar_existencia(self, nome, sku):
        # Simulação de API - ajustar para usar api_get real
        return False  # Assume produto não existe

    def cadastrar_produto(self, produto):
        payload = {
            "nome": produto["nome"],
            "codigo_sku": produto["codigo_sku"],
            "codigo_ean": produto.get("codigo_ean", ""),
            "observacao": produto.get("observacao", ""),
            "formato": produto["formato"],
            "estoque": {
                "valor_venda": float(produto["valor_venda"]),
                "custo_medio": float(produto["custo_medio"]),
                "estoque_disponivel": float(produto["estoque_disponivel"]),
                "estoque_minimo": float(produto["estoque_minimo"]),
                "estoque_maximo": float(produto["estoque_maximo"]),
            },
            "dimensao": {
                "altura": float(produto["altura"]),
                "largura": float(produto["largura"]),
                "profundidade": float(produto["profundidade"]),
            },
            "ecommerce": {
                "condicao": produto.get("condicao", "NOVO"),
                "integracao_habilitada": self.str_para_bool(produto.get("integracao_habilitada", "FALSO")),
                "descricao": produto.get("descricao", ""),
                "titulo_seo": produto.get("titulo_seo", ""),
                "url_seo": produto.get("url_seo", ""),
            }
        }
        # Simulação de envio - substituir por api_post
        return True, "Cadastrado com sucesso"

    def processar_upload(self, arquivo_excel):
        df = pd.read_excel(arquivo_excel)
        erros_planilha = self.validar_planilha(df)
        if erros_planilha:
            return {"status": "erro", "mensagem": "Erros na planilha", "resumo": [], "erros": erros_planilha}

        resultados = []

        for i, row in df.iterrows():
            nome = row.get("nome")
            sku = row.get("codigo_sku")

            # Checar se já existe
            if self.verificar_existencia(nome, sku):
                resultados.append({
                    "produto": nome,
                    "sku": sku,
                    "status": "Ignorado",
                    "mensagem": "Já existe"
                })
                continue

            try:
                # Formatar números
                for campo in [
                    "valor_venda", "custo_medio", "estoque_disponivel",
                    "estoque_minimo", "estoque_maximo",
                    "altura", "largura", "profundidade"
                ]:
                    row[campo] = float(str(row.get(campo)).replace(",", "."))

                sucesso, msg = self.cadastrar_produto(row)
                status = "Cadastrado" if sucesso else "Erro"
                resultados.append({
                    "produto": nome,
                    "sku": sku,
                    "status": status,
                    "mensagem": msg
                })
            except Exception as e:
                resultados.append({
                    "produto": nome,
                    "sku": sku,
                    "status": "Erro",
                    "mensagem": str(e)
                })

        return {"status": "ok", "resumo": resultados, "erros": []}

