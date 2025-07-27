# modules/produto/ui.py

import streamlit as st
import pandas as pd
from io import BytesIO
from modules.produto.service import ProdutoService
from utils.errors import render_error


def gerar_modelo_excel():
    dados_exemplo = {
        "nome": ["Camisa Polo Azul"],
        "codigo_sku": ["CAMISAPOLO123"],
        "codigo_ean": ["7891234567890"],
        "formato": ["SIMPLES"],  # ou VARIACAO
        "observacao": ["Camisa polo 100% algodão"],
        "valor_venda": [99.90],
        "custo_medio": [49.90],
        "estoque_disponivel": [100],
        "estoque_minimo": [10],
        "estoque_maximo": [500],
        "altura": [3],
        "largura": [25],
        "profundidade": [30],
        "condicao": ["NOVO"],  # ou USADO
        "integracao_habilitada": [False],
        "descricao": ["Camisa polo elegante e confortável"],
        "titulo_seo": ["Camisa Polo Azul Masculina"],
        "url_seo": ["camisa-polo-azul"]
    }

    df_modelo = pd.DataFrame(dados_exemplo)
    buffer = BytesIO()
    df_modelo.to_excel(buffer, index=False)
    buffer.seek(0)
    return buffer

def render_ui():
    with st.expander("📦 Produto — Importar via Excel"):
        st.markdown("Faça upload de uma planilha `.xlsx` para importar produtos em massa.")
        st.markdown("A planilha deve conter **colunas obrigatórias** e **alguns campos recomendados**.")

        # Botão de download da planilha modelo
        buffer = gerar_modelo_excel()
        st.download_button(
            label="📥 Baixar modelo de planilha (Excel)",
            data=buffer,
            file_name="modelo_produto.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        uploaded_file = st.file_uploader("Enviar planilha Excel", type=["xlsx"])

        if uploaded_file:
            st.info("📊 Processando arquivo...")

            try:
                # ✅ Não precisamos mais de token na sessão; ca_api garante o Bearer válido.
                service = ProdutoService()
                resultado = service.processar_upload(uploaded_file)

                if resultado["status"] == "erro":
                    st.error("❌ Erros encontrados na planilha:")
                    for erro in resultado["erros"]:
                        st.write(f"- {erro}")
                else:
                    resumo_df = pd.DataFrame(resultado["resumo"])
                    st.success("✅ Importação finalizada com sucesso.")
                    st.dataframe(resumo_df, use_container_width=True)

            except Exception as e:
                render_error(e, context="Importar Produtos")
