# modules/vendas/ui.py

from __future__ import annotations
import streamlit as st
import pandas as pd
from io import BytesIO

from modules.vendas.service import VendaService
from utils.errors import render_error

def render_ui():
    with st.expander("💰 Vendas — Importar em Massa"):
        st.markdown(
            """
            **Instruções rápidas**
            1. Baixe o modelo, preencha **uma linha por item** e agrupe por `pedido_id`.
            2. Preencha cliente (tipo/nome/documento), datas em **YYYY-MM-DD** e valores numéricos (ponto decimal).
            3. Informe **pagamentos** (método, valor, vencimento). Se houver parcelas, repita o `pedido_id`.
            4. Opcional: `total_declarado` para conferência; validaremos soma dos itens + frete.
            """
        )

        # Download do modelo (xlsx)
        buffer = VendaService.gerar_modelo_planilha()
        st.download_button(
            "📥 Baixar modelo (Excel)",
            data=buffer,
            file_name="modelo_vendas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

        uploaded = st.file_uploader("📤 Enviar planilha (.xlsx ou .csv)", type=["xlsx", "csv"])

        if uploaded is not None:
            st.info("Validando e montando pedidos...")
            try:
                with st.spinner("Processando vendas..."):
                    resultado = VendaService.processar_upload(uploaded)

                resumo = resultado["resumo"]
                st.success(
                    f"✅ Pedidos: {resumo['total_pedidos']} • Criadas: {resumo['sucesso']} • Erros: {resumo['erros']}"
                )

                # Erros de montagem/validação (antes do POST)
                if not resultado["erros_montagem_df"].empty:
                    with st.expander("⚠️ Erros de validação (antes do envio)"):
                        st.dataframe(resultado["erros_montagem_df"], use_container_width=True)

                st.subheader("📄 Resultado por pedido")
                st.dataframe(resultado["resultado_df"], use_container_width=True)

            except Exception as e:
                render_error(e, context="Importar Vendas")
