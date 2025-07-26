# modules/produto/service.py

import pandas as pd
import io
import re
from utils.ca_api import api_get, api_post
from utils.token_store import has_valid_token

class ProdutoService:

    CAMPOS_OBRIGATORIOS = ['nome', 'codigo']
    CAMPOS_VALIDOS = ['nome', 'codigo', 'unidade', 'preco', 'descricao', 'marca', 'codigo_barras']

    @classmethod
    def validar_planilha(cls, arquivo_excel):
        try:
            df = pd.read_excel(arquivo_excel)
        except Exception as e:
            raise ValueError("Erro ao ler o Excel. Verifique se o arquivo está válido.")

        df.columns = [str(col).strip().lower().replace(" ", "_") for col in df.columns]

        for campo in cls.CAMPOS_OBRIGATORIOS:
            if campo not in df.columns:
                raise ValueError(f"Campo obrigatório ausente: {campo}")

        if len(df) > 500:
            raise ValueError("Limite de 500 produtos excedido.")

        return df[cls.CAMPOS_VALIDOS].fillna("")

    @classmethod
    def verificar_existencia(cls, produto_dict):
        nome = produto_dict.get("nome", "")
        codigo = produto_dict.get("codigo", "")
        nome = re.sub(r"\s+", " ", nome.strip().lower())
        codigo = codigo.strip()

        try:
            resposta = api_get("/v1/products", params={"name": nome, "code": codigo})
            produtos = resposta.get("data", []) if isinstance(resposta, dict) else resposta
            for p in produtos:
                if p["name"].strip().lower() == nome or p.get("code", "").strip() == codigo:
                    return True
        except:
            pass

        return False

    @classmethod
    def cadastrar_produto(cls, produto_dict):
        payload = {
            "name": produto_dict["nome"],
            "code": produto_dict["codigo"],
            "unit": produto_dict.get("unidade", "UN"),
            "price": float(produto_dict.get("preco", 0)) or 0,
            "description": produto_dict.get("descricao", ""),
            "brand": produto_dict.get("marca", ""),
            "barcode": produto_dict.get("codigo_barras", ""),
            "type": "PRODUCT",  # obrigatório na API da Conta Azul
        }

        response = api_post("/v1/products", json=payload)
        return response

    @classmethod
    def processar_upload(cls, arquivo_excel):
        if not has_valid_token():
            raise RuntimeError("Token de acesso inválido ou expirado.")

        df = cls.validar_planilha(arquivo_excel)
        erros = []
        cadastrados = 0
        ignorados = 0

        for _, row in df.iterrows():
            produto = row.to_dict()

            if cls.verificar_existencia(produto):
                ignorados += 1
                continue

            try:
                cls.cadastrar_produto(produto)
                cadastrados += 1
            except Exception as e:
                produto["erro"] = str(e)
                erros.append(produto)

        return {
            "cadastrados": cadastrados,
            "ignorados": ignorados,
            "erros": erros,
            "erros_df": pd.DataFrame(erros) if erros else None
        }
