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
            ### 📌 Instruções para Preenchimento da Planilha

            Siga atentamente as orientações abaixo para garantir o sucesso na importação:

            1. **Uma linha por item vendido**  
               - Cada linha representa **um produto ou serviço** de um pedido.  
               - Utilize o mesmo `pedido_id` para agrupar múltiplos itens e/ou parcelas de um mesmo pedido.

            2. **Informações do Cliente**  
               - `customer_tipo`: FISICA ou JURIDICA  
               - `customer_nome`: Nome completo ou razão social  
               - `customer_documento`: CPF (11 dígitos) ou CNPJ (14 dígitos)  
               → Se o cliente ainda não existir, será criado automaticamente.

            3. **Informações dos Itens**  
               - `item_tipo`: PRODUTO ou SERVICO  
               - `item_codigo`: SKU (produto) ou código de serviço  
               - `item_quantidade`: número maior que 0  
               - `item_unit_price`: valor unitário com **ponto decimal** (ex: 149.90)

            4. **Pagamentos e Parcelas**  
               - `payment_method`: PIX, BOLETO, CARTAO_CREDITO, DINHEIRO, etc.  
                 → Também aceitamos nomes comuns como `pix_itau`, `boleto_caixa`, etc.  
               - `payment_amount`: valor da parcela (> 0)  
               - `payment_due_date`: data de vencimento no formato **YYYY-MM-DD**  
               → Para parcelar, repita o mesmo `pedido_id` com diferentes parcelas.

            5. **Campos Opcionais**  
               - `status`: EM_ABERTO (default) ou outro status suportado pela API  
               - `shipping_cost`: valor do frete (default = 0)  
               - `total_declarado`: total esperado da venda → será comparado com soma dos itens + frete  
               - `observacao`: texto livre para observações internas

            6. **Validações automáticas**
               - Checamos a soma dos valores (itens + frete == total_declarado)  
               - Validação da quantidade, valores, métodos de pagamento e documentos  
               - Produtos e serviços são buscados automaticamente por código

            ---
            ✅ Ao finalizar o preenchimento, salve como **Excel (.xlsx)** e envie abaixo.
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
