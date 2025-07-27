# modules/pessoas/ui.py

import streamlit as st
import pandas as pd
from io import BytesIO
from modules.pessoas.service import PessoaService
import json

def _modelo_dataframe():
    """
    Modelo abrangente para testes do dia a dia (CPF/CNPJ, endereço, flags cliente/fornecedor).
    """
    return pd.DataFrame([
        {
            "tipo": "FISICA",
            "nome": "João da Silva",
            "documento": "123.456.789-09",
            "email": "joao.silva@example.com",
            "telefone": "1130012000",
            "celular": "11988887777",
            "cep": "01311000",
            "logradouro": "Av. Paulista",
            "numero": "1000",
            "complemento": "Conjunto 101",
            "bairro": "Bela Vista",
            "cidade": "São Paulo",
            "estado": "SP",
            "cliente": "VERDADEIRO",
            "fornecedor": "FALSO",
            "data_nascimento": "15/04/1988",
        },
        {
            "tipo": "JURIDICA",
            "nome": "Tech Soluções LTDA",
            "documento": "12.345.678/0001-90",
            "nome_fantasia": "Tech Soluções",
            "email": "contato@techsolucoes.com.br",
            "telefone": "4130023003",
            "celular": "",
            "cep": "80010000",
            "logradouro": "Rua XV de Novembro",
            "numero": "250",
            "complemento": "Sala 502",
            "bairro": "Centro",
            "cidade": "Curitiba",
            "estado": "PR",
            "cliente": "VERDADEIRO",
            "fornecedor": "VERDADEIRO",
            "inscricao_estadual": "ISENTO",
            "inscricao_municipal": "12345",
        },
    ])

def _gerar_modelo_excel():
    df = _modelo_dataframe()
    buf = BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    return buf

def render_ui():
    with st.expander("👥 Pessoas — Importar via Excel"):
        st.divider()
        st.title("**CADASTRO DE CLIENTE/FORNECEDOR**", )
        st.markdown("""
            **Descrição:**  
            Você pode cadastrar pessoas físicas ou jurídicas com perfis de **cliente**, **fornecedor** ou **transportadora**, preenchendo os dados básicos e opcionais.

            **Campos obrigatórios na planilha:**
            - `tipo` → define o tipo da pessoa (`FISICA`, `JURIDICA` ou `ESTRANGEIRA`)
            - `nome` → nome completo ou razão social
            - `documento` → CPF ou CNPJ (somente números)

            **Campos opcionais recomendados:**
            - `email`, `telefone`, `celular`
            - `cliente`, `fornecedor` (valores: `sim`, `não`, `1`, `0`, etc.)
            - `cep`, `logradouro`, `numero`, `bairro`, `cidade`, `estado`, `pais`
            - `data_nascimento` (formato: `dd/mm/yyyy` ou `yyyy-mm-dd`)
            - `observacao`, `codigo`, `nome_fantasia`, `inscricao_estadual`, `inscricao_municipal`
                """)
        st.caption("Dica: Se um CPF/CNPJ ou nome já estiver cadastrado, ele será automaticamente ignorado.")

        # Modelo
        st.download_button(
            "📥 Baixar modelo (Excel)",
            data=_gerar_modelo_excel(),
            file_name="modelo_pessoas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="tertiary",
        )

        up = st.file_uploader("📤 Enviar planilha Excel de Pessoas", type=["xlsx"])

        # modules/pessoas/ui.py  (trecho dentro do if up:)
        if up:
            st.info("📊 Processando planilha…")
            debug = st.toggle("🔍 Depurar payload enviado à API (mostrar JSON em caso de erro)", value=False)

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
                            st.dataframe(df_resumo[df_resumo["status"] == "Erro"], use_container_width=True)

            except Exception as e:
                st.error(f"❌ Erro ao processar a planilha:")
                # se o RuntimeError trouxe JSON, mostramos bonito
                try:
                    info = json.loads(str(e))
                    st.json(info)
                except Exception:
                    st.write(e)
    st.divider()
