# modules/pessoas/service.py

import re
import pandas as pd
from datetime import datetime
from utils.ca_api import api_get, api_post

class PessoaService:
    """
    Serviço de importação em massa de Pessoas.
    - Usa ca_api (que garante token válido e refresh).
    - Endpoints isolados em constantes para fácil ajuste por tenant/ambiente.
    """

    # Ajuste aqui se o seu ambiente expuser outro path
    PESSOAS_LIST_PATH = "/v1/pessoas"
    PESSOAS_CREATE_PATH = "/v1/pessoas"

    # Campos esperados na planilha
    CAMPOS_OBRIGATORIOS = ["tipo", "nome", "documento"]
    CAMPOS_OPCIONAIS = [
        "email", "telefone", "celular",
        "cep", "logradouro", "numero", "complemento",
        "bairro", "cidade", "estado",
        "cliente", "fornecedor",
        "inscricao_estadual", "inscricao_municipal",
        "nome_fantasia", "data_nascimento"
    ]
    CAMPOS_VALIDOS = CAMPOS_OBRIGATORIOS + CAMPOS_OPCIONAIS

    # --------- Helpers de normalização ---------
    @staticmethod
    def _only_digits(s: str | None) -> str:
        return re.sub(r"\D+", "", str(s or ""))

    @staticmethod
    def _norm_text(s: str | None) -> str:
        return re.sub(r"\s+", " ", str(s or "").strip()).lower()

    @staticmethod
    def _to_bool(v) -> bool:
        return str(v).strip().upper() in {"1", "TRUE", "VERDADEIRO", "SIM", "YES"}

    @staticmethod
    def _date_to_iso(d) -> str | None:
        """
        Converte formatos comuns de planilha para 'YYYY-MM-DD'.
        Aceita: datetime, 'dd/mm/aaaa', 'aaaa-mm-dd', etc.
        """
        if d in (None, "", "nan"):
            return None
        if isinstance(d, datetime):
            return d.strftime("%Y-%m-%d")
        s = str(d).strip()
        # dd/mm/aaaa
        m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        # aaaa-mm-dd (já ok)
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return s
        # fallback: tenta pandas
        try:
            return pd.to_datetime(s).strftime("%Y-%m-%d")
        except Exception:
            return None

    # --------- Validação da planilha ---------
    def validar_planilha(self, df: pd.DataFrame) -> list[str]:
        df.columns = df.columns.str.strip().str.lower()
        erros = []
        for c in self.CAMPOS_OBRIGATORIOS:
            if c not in df.columns:
                erros.append(f"Campo obrigatório ausente: {c}")
        if len(df) > 500:
            erros.append("Limite máximo de 500 linhas por importação.")
        # Garante que só passem colunas válidas (silenciosamente ignora extras)
        return erros

    # --------- Consulta de existência ---------
    def verificar_existencia(self, pessoa: dict) -> bool:
        """
        Regra:
        - Primeiro tenta por documento (apenas dígitos).
        - Fallback por nome normalizado (case/espacos).
        """
        doc_norm = self._only_digits(pessoa.get("documento"))
        nome_norm = self._norm_text(pessoa.get("nome"))

        try:
            termo = doc_norm or nome_norm
            if not termo:
                return False
            resp = api_get(self.PESSOAS_LIST_PATH, params={"termo": termo})
            itens = resp.get("data", resp) if isinstance(resp, dict) else resp

            if not isinstance(itens, list):
                return False

            for p in itens:
                # documento pode vir como 'documento'/'cpfCnpj' ou aninhado em 'documentos' (varia por contrato)
                cand_doc = self._only_digits(p.get("documento") or p.get("cpfCnpj") or "")
                cand_nome = self._norm_text(p.get("nome") or p.get("razaoSocial") or "")

                if doc_norm and cand_doc and cand_doc == doc_norm:
                    return True
                if nome_norm and cand_nome and cand_nome == nome_norm:
                    return True
        except Exception:
            # Em caso de erro de rede/401/422 etc., trate como não-existente e deixe o POST decidir
            return False

        return False

    # --------- Montagem do payload ---------
    def _payload_pessoa(self, row: dict) -> dict:
        """
        Mapeia os campos da planilha para o payload esperado pelo endpoint de Pessoas.
        Mantemos nomes genéricos e opcionais para cobrir variações:
        """
        tipo = str(row.get("tipo", "FISICA")).upper().strip()  # FISICA | JURIDICA
        documento = self._only_digits(row.get("documento"))
        payload = {
            "tipo": tipo,
            "nome": row.get("nome", ""),
            "documento": documento,
            "email": (row.get("email") or "").strip(),
            "telefone": self._only_digits(row.get("telefone")),
            "celular": self._only_digits(row.get("celular")),
            "cliente": self._to_bool(row.get("cliente", True)),
            "fornecedor": self._to_bool(row.get("fornecedor", False)),
            "endereco": {
                "cep": self._only_digits(row.get("cep")),
                "logradouro": (row.get("logradouro") or "").strip(),
                "numero": (str(row.get("numero") or "").strip()),
                "complemento": (row.get("complemento") or "").strip(),
                "bairro": (row.get("bairro") or "").strip(),
                "cidade": (row.get("cidade") or "").strip(),
                "estado": (row.get("estado") or "").strip(),
            }
        }

        # Campos específicos/optativos
        if row.get("inscricao_estadual"):
            payload["inscricao_estadual"] = str(row.get("inscricao_estadual")).strip()
        if row.get("inscricao_municipal"):
            payload["inscricao_municipal"] = str(row.get("inscricao_municipal")).strip()
        if row.get("nome_fantasia"):
            payload["nome_fantasia"] = str(row.get("nome_fantasia")).strip()
        dn = self._date_to_iso(row.get("data_nascimento"))
        if dn and tipo == "FISICA":
            payload["data_nascimento"] = dn

        return payload

    # --------- POST de criação ---------
    def cadastrar_pessoa(self, pessoa_row: dict):
        payload = self._payload_pessoa(pessoa_row)
        resp = api_post(self.PESSOAS_CREATE_PATH, json=payload)
        return True, resp

    # --------- Pipeline principal ---------
    def processar_upload(self, arquivo_excel):
        df = pd.read_excel(arquivo_excel)
        erros = self.validar_planilha(df)
        if erros:
            return {"status": "erro", "mensagem": "Erros na planilha", "resumo": [], "erros": erros}

        # restrição às colunas válidas (evita KeyError)
        cols = [c for c in df.columns if c in self.CAMPOS_VALIDOS]
        df = df[cols].fillna("")

        resultados = []
        for _, row in df.iterrows():
            pessoa = {k: row.get(k) for k in df.columns}
            nome = (pessoa.get("nome") or "").strip()
            doc  = self._only_digits(pessoa.get("documento"))

            # 1) Verificar duplicidade
            try:
                if self.verificar_existencia(pessoa):
                    resultados.append({
                        "pessoa": nome,
                        "documento": doc,
                        "status": "Ignorado",
                        "mensagem": "Já existe (documento/nome)."
                    })
                    continue
            except Exception as e:
                resultados.append({
                    "pessoa": nome,
                    "documento": doc,
                    "status": "Erro",
                    "mensagem": f"Falha na verificação: {e}"
                })
                continue

            # 2) Cadastrar
            try:
                ok, msg = self.cadastrar_pessoa(pessoa)
                resultados.append({
                    "pessoa": nome,
                    "documento": doc,
                    "status": "Cadastrado" if ok else "Erro",
                    "mensagem": msg if isinstance(msg, str) else "OK"
                })
            except Exception as e:
                resultados.append({
                    "pessoa": nome,
                    "documento": doc,
                    "status": "Erro",
                    "mensagem": str(e)
                })

        return {"status": "ok", "resumo": resultados, "erros": []}
