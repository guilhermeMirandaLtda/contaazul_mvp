# modules/produto/ui.py

import streamlit as st
from modules.produto.service import ProdutoService

def render_ui():
    with st.expander("📦 Produto — Importar via Excel"):
        st.markdown("Faça upload de uma planilha `.xlsx` para importar produtos em massa.")
        st.markdown("- A planilha deve conter colunas obrigatórias: **nome**, **código**")
        st.markdown("- Baixe o modelo: [modelo_produto.xlsx](https://exemplo.com/modelo_produto.xlsx)")
        
        uploaded_file = st.file_uploader("📤 Enviar planilha Excel", type=["xlsx"])

        if uploaded_file:
            st.info("📊 Processando arquivo...")

            try:
                resultado = ProdutoService.processar_upload(uploaded_file)

                st.success(f"✅ Importação finalizada: {resultado['cadastrados']} novos cadastrados, {resultado['ignorados']} ignorados.")
                
                if resultado["erros"]:
                    with st.expander("⚠️ Visualizar Erros"):
                        st.dataframe(resultado["erros_df"])
            except Exception as e:
                st.error(f"❌ Erro ao processar planilha: {e}")
