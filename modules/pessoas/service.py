# modules/pessoas/service.py

import re
import json
import pandas as pd
import requests
from datetime import datetime
from utils.ca_api import api_get, api_post

class PessoaService:
    """
    Serviço de importação em massa de Pessoas.
    Alinha endpoints e payload ao catálogo v2 (Pessoa).
    """

    # Endpoints oficiais (singular)
    PESSOAS_LIST_PATH = "/v1/pessoa"   # GET ?termo_busca=...
    PESSOAS_CREATE_PATH = "/v1/pessoa" # POST
    # Doc: https://api-v2.contaazul.com/v1/pessoa (list/create)  # ver doc oficial
    # (Página doc: Pessoas / Lista registros de pessoas + Criação) 

    # Colunas esperadas na planilha
    CAMPOS_OBRIGATORIOS = ["tipo", "nome", "documento"]
    CAMPOS_OPCIONAIS = [
        "email", "telefone", "celular",
        "cep", "logradouro", "numero", "complemento",
        "bairro", "cidade", "estado", "pais",
        "cliente", "fornecedor",
        "inscricao_estadual", "inscricao_municipal",
        "nome_fantasia", "data_nascimento", "observacao", "codigo"
    ]
    CAMPOS_VALIDOS = CAMPOS_OBRIGATORIOS + CAMPOS_OPCIONAIS

    # ---------- Normalizadores ----------
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
        if d in (None, "", "nan"):
            return None
        if isinstance(d, datetime):
            return d.strftime("%Y-%m-%d")
        s = str(d).strip()
        m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)  # dd/mm/aaaa
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):        # yyyy-mm-dd
            return s
        try:
            return pd.to_datetime(s).strftime("%Y-%m-%d")
        except Exception:
            return None

    # ---------- Validação ----------
    def validar_planilha(self, df: pd.DataFrame) -> list[str]:
        df.columns = df.columns.str.strip().str.lower()
        erros = []
        for c in self.CAMPOS_OBRIGATORIOS:
            if c not in df.columns:
                erros.append(f"Campo obrigatório ausente: {c}")
        if len(df) > 500:
            erros.append("Limite máximo de 500 linhas por importação.")
        return erros

    # ---------- Perfis ----------
    def _perfis_from_row(self, row: dict) -> list[dict]:
        perfis = []
        if self._to_bool(row.get("cliente", True)):
            perfis.append({"tipo_perfil": "CLIENTE"})
        if self._to_bool(row.get("fornecedor", False)):
            perfis.append({"tipo_perfil": "FORNECEDOR"})
        # Se nenhum marcado, por padrão considere cliente (evita 400 por perfis ausente)
        if not perfis:
            perfis.append({"tipo_perfil": "CLIENTE"})
        return perfis

    # ---------- Endereços ----------
    def _enderecos_from_row(self, row: dict) -> list[dict]:
        any_addr = any(row.get(k) for k in ["cep", "logradouro", "numero", "bairro", "cidade", "estado", "pais"])
        if not any_addr:
            return []
        return [{
            # Campos aceitos pela doc da API de Pessoas em endereços
            "cep": self._only_digits(row.get("cep")),
            "logradouro": (row.get("logradouro") or "").strip(),
            "numero": (str(row.get("numero") or "").strip()),
            "complemento": (row.get("complemento") or "").strip(),
            "bairro": (row.get("bairro") or "").strip(),
            "cidade": (row.get("cidade") or "").strip(),
            "estado": (row.get("estado") or "").strip(),
            "pais": (row.get("pais") or "").strip(),
        }]

    # ---------- Consulta de existência ----------
    def verificar_existencia(self, pessoa: dict) -> bool:
        """
        Usa GET /v1/pessoa?termo_busca=... (documento ou nome).
        Compara por documento (somente dígitos) e por nome normalizado.
        """
        doc_norm = self._only_digits(pessoa.get("documento"))
        nome_norm = self._norm_text(pessoa.get("nome"))

        try:
            termo = doc_norm or nome_norm
            if not termo:
                return False
            resp = api_get(self.PESSOAS_LIST_PATH, params={"termo_busca": termo})
            itens = resp.get("data", resp) if isinstance(resp, dict) else resp
            if not isinstance(itens, list):
                return False
            for p in itens:
                cand_doc = self._only_digits(p.get("documento") or p.get("cpf") or p.get("cnpj") or "")
                cand_nome = self._norm_text(p.get("nome") or p.get("razaoSocial") or "")
                if doc_norm and cand_doc and cand_doc == doc_norm:
                    return True
                if nome_norm and cand_nome and cand_nome == nome_norm:
                    return True
        except Exception:
            return False
        return False

    # ---------- Monta payload conforme doc ----------
    def _payload_pessoa(self, row: dict) -> dict:
        tipo = (row.get("tipo") or "FISICA").strip().upper()  # FISICA/JURIDICA/ESTRANGEIRA
        documento = self._only_digits(row.get("documento"))

        payload = {
            "perfis": self._perfis_from_row(row),       # required
            "tipo_pessoa": tipo,                         # required
            "nome": (row.get("nome") or "").strip(),     # required
            "email": (row.get("email") or "").strip(),
            "telefone_comercial": self._only_digits(row.get("telefone")),
            "celular": self._only_digits(row.get("celular")),
            "observacao": (row.get("observacao") or "").strip(),
            "codigo": (str(row.get("codigo")) if row.get("codigo") not in (None, "") else None),
            "enderecos": self._enderecos_from_row(row),  # array (pode ser vazio)
        }

        # Documento conforme tipo_pessoa
        if tipo == "FISICA":
            payload["cpf"] = documento
            # Data de nascimento só faz sentido para FISICA
            dn = self._date_to_iso(row.get("data_nascimento"))
            if dn:
                payload["data_nascimento"] = dn
        elif tipo == "JURIDICA":
            payload["cnpj"] = documento
            if row.get("nome_fantasia"):
                payload["nome_fantasia"] = str(row.get("nome_fantasia")).strip()
            if row.get("inscricao_estadual"):
                payload["inscricao_estadual"] = str(row.get("inscricao_estadual")).strip()
            if row.get("inscricao_municipal"):
                payload["inscricao_municipal"] = str(row.get("inscricao_municipal")).strip()
        else:
            # ESTRANGEIRA: a doc permite, mas sem cpf/cnpj. Ajuste se a sua operação exigir.
            pass

        # Remove chaves None (opcional, para evitar rejeição por campos vazios)
        return {k: v for k, v in payload.items() if v not in (None, "")}

    # ---------- POST ----------
    def cadastrar_pessoa(self, pessoa_row: dict):
        payload = self._payload_pessoa(pessoa_row)
        try:
            resp = api_post(self.PESSOAS_CREATE_PATH, json=payload)
            return True, resp
        except requests.HTTPError as e:
            # Mostra corpo do erro para depuração (400/422)
            body = ""
            if e.response is not None:
                try:
                    body = e.response.text
                except Exception:
                    body = str(e)
            raise RuntimeError(f"HTTP {e.response.status_code if e.response else ''} - {body}") from e
        except Exception as e:
            raise

    # ---------- Pipeline principal ----------
    def processar_upload(self, arquivo_excel):
        df = pd.read_excel(arquivo_excel)
        erros = self.validar_planilha(df)
        if erros:
            return {"status": "erro", "mensagem": "Erros na planilha", "resumo": [], "erros": erros}

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
                        "pessoa": nome, "documento": doc,
                        "status": "Ignorado",
                        "mensagem": "Já existe (documento/nome)."
                    })
                    continue
            except Exception as e:
                resultados.append({
                    "pessoa": nome, "documento": doc,
                    "status": "Erro",
                    "mensagem": f"Falha na verificação: {e}"
                })
                continue

            # 2) Cadastrar
            try:
                ok, msg = self.cadastrar_pessoa(pessoa)
                resultados.append({
                    "pessoa": nome, "documento": doc,
                    "status": "Cadastrado" if ok else "Erro",
                    "mensagem": msg if isinstance(msg, str) else "OK"
                })
            except Exception as e:
                resultados.append({
                    "pessoa": nome, "documento": doc,
                    "status": "Erro",
                    "mensagem": str(e)
                })

        return {"status": "ok", "resumo": resultados, "erros": []}
