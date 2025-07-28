# modules/pessoas/ui.py

import json
import streamlit as st
import pandas as pd
from io import BytesIO
from modules.pessoas.service import PessoaService
from utils.errors import render_error


def _modelo_dataframe():
    """
    Modelo abrangente com PF e PJ para testes.
    """
    return pd.DataFrame([
        # PF válida
        {
            "tipo": "FISICA",
            "nome": "Aparecida Emanuelly da Paz",
            "documento": "36014495797",   # 11 dígitos
            "email": "aparecida-dapaz85@paginacom.com.br",
            "telefone": "8628154159",
            "celular": "86987911399",
            "cliente": "sim",
            "fornecedor": "nao",
            "cep": "64065-150",
            "logradouro": "Rua Jato Delta",
            "numero": "755",
            "bairro": "Pedra Mole",
            "cidade": "Teresina",
            "estado": "PI",
            "pais": "Brasil",
            "data_nascimento": "08/05/1996",
            "observacao": "PF de teste",
            "codigo": "PF-0001"
        },
        # PJ válida
        {
            "tipo": "JURIDICA",
            "nome": "Empresa Exemplo LTDA",
            "documento": "12345678000195",  # 14 dígitos
            "email": "contato@empresa.com",
            "telefone": "4130023003",
            "celular": "",
            "cliente": "sim",
            "fornecedor": "sim",
            "cep": "80010000",
            "logradouro": "Rua XV de Novembro",
            "numero": "250",
            "bairro": "Centro",
            "cidade": "Curitiba",
            "estado": "PR",
            "pais": "Brasil",
            "nome_fantasia": "Empresa Exemplo",
            "inscricao_estadual": "ISENTO",
            "inscricao_municipal": "12345",
            "observacao": "PJ de teste",
            "codigo": "PJ-0001"
        },
    ])


def _gerar_modelo_excel():
    df = _modelo_dataframe()
    buf = BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    return buf


def render_ui():
    with st.expander("📇 CADASTRO DE CLIENTE / FORNECEDOR"):
        st.caption("Importe em lote os dados dos seus clientes, fornecedores ou transportadoras.")
        st.markdown("""
**Descrição:**  
Cadastre pessoas físicas ou jurídicas com perfis de **CLIENTE** e/ou **FORNECEDOR**.  
Os dados são validados e normalizados automaticamente antes do envio.

**Campos obrigatórios:**
- `tipo` → `FISICA`, `JURIDICA` ou `ESTRANGEIRA`
- `nome` → nome completo / razão social
- `documento` → `CPF` (11 dígitos) se FISICA, `CNPJ` (14 dígitos) se JURIDICA

**Campos opcionais úteis:**
- `email`, `telefone`, `celular`
- `cliente`, `fornecedor` (aceita `sim/nao`, `true/false`, `1/0`)
- `cep`, `logradouro`, `numero`, `bairro`, `cidade`, `estado` (UF), `pais`
- `data_nascimento` (`dd/mm/aaaa` ou `yyyy-mm-dd`)
- `observacao`, `codigo`, `nome_fantasia`, `inscricao_estadual`, `inscricao_municipal`
        """)

        st.download_button(
            "📥 Baixar modelo (Excel)",
            data=_gerar_modelo_excel(),
            file_name="modelo_pessoas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )

        up = st.file_uploader("📤 Enviar planilha Excel de Pessoas", type=["xlsx"])
        debug = st.toggle("🔍 Depurar payload enviado à API (mostrar JSON em caso de erro)", value=False)

        if up:
            st.info("📊 Processando planilha…")
            try:
                svc = PessoaService()
                resultado = svc.processar_upload(up, debug=debug)

                if resultado["status"] == "erro":
                    st.error("❌ Erros na estrutura da planilha:")
                    for e in resultado["erros"]:
                        st.write(f"- {e}")
                else:
                    df_resumo = pd.DataFrame(resultado["resumo"])
                    st.success("✅ Importação concluída.")
                    st.dataframe(df_resumo, use_container_width=True)

                    if any(r["status"] == "Erro" for r in resultado["resumo"]):
                        with st.expander("⚠️ Visualizar erros detalhados"):
                            # Mostra a mensagem completa (inclui JSON do payload/erro quando debug=True)
                            st.dataframe(df_resumo[df_resumo["status"] == "Erro"], use_container_width=True)

            except Exception as e:
                render_error(e, context="Importar Pessoas")
