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
            ### 📌 Instruções para Preenchimento da Planilha (PT-BR)

            **Conceito:** Preencha **uma linha por ITEM**. Para parcelar, **repita o mesmo _Número_**
            alterando apenas as colunas de pagamento (**Método**, **Valor da Parcela**, **Vencimento da Parcela**).
            O sistema irá agrupar as linhas por **Número** para montar os **ITENS** e as **PARCELAS** do pedido.

            **Campos obrigatórios (marcados com *)**
            - **Número***: inteiro (ex.: pode informar "PED-1001" — os dígitos serão extraídos).
            - **Data da Venda*** (YYYY-MM-DD) • **Situação***: EM_ANDAMENTO ou APROVADO .
            - **Tipo do Cliente***: FISICA ou JURIDICA
            - **Nome do Cliente*** • **Documento do Cliente***: CPF (11) / CNPJ (14) — somente dígitos
            - **Tipo do Item*** (PRODUTO/SERVICO) • **Código do Item*** (SKU/código)
            - **Quantidade*** (> 0) • **Valor Unitário*** (ponto decimal)
            - **Método de Pagamento*** (enum canônico) • **Valor da Parcela*** • **Vencimento da Parcela*** (YYYY-MM-DD)

            **Campos opcionais**
            - **Observações** • **Custo de Frete** • **Conta Financeira (ID)**
            - **Total declarado** (se informado, validaremos a igualdade com soma dos itens + frete)

            **Validações automáticas**
            - Soma das parcelas = soma(itens) + frete
            - Resolução automática de cliente/produto/serviço
            - Datas e numéricos com tratamento consistente

            ✅ Salve como **Excel (.xlsx)** e envie abaixo.
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
