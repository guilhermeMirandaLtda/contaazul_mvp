# modules/pessoas/service.py

import re
import json
import pandas as pd
import requests
from datetime import datetime
from utils.ca_api import api_get, api_post


class PessoaService:
    """
    Importação em massa de Pessoas (v2) com saneamento e validação de payload.
    - Endpoints oficiais: /v1/pessoa (GET+POST)
    - Busca por termo_busca (fallback termo)
    - Payload com tipo_pessoa, perfis[], cpf/cnpj e enderecos[].
    - Correção de campos comuns (CPF/CNPJ/CEP/telefones/data).
    """

    # Endpoints
    PESSOAS_LIST_PATH = "/v1/pessoa"    # GET ?termo_busca=... (fallback: ?termo=...)
    PESSOAS_CREATE_PATH = "/v1/pessoa"  # POST

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

    TIPOS_PESSOA_VALIDOS = {"FISICA", "JURIDICA", "ESTRANGEIRA"}
    TIPOS_PERFIL_VALIDOS = {"CLIENTE", "FORNECEDOR", "TRANSPORTADORA"}

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
        """
        Converte 'dd/mm/aaaa' ou valores reconhecíveis para 'YYYY-MM-DD'.
        """
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
        
        # ---------- Validadores adicionais ----------
    @staticmethod
    def _is_valid_cpf(cpf: str) -> bool:
        return len(cpf) == 11 and cpf.isdigit()  # (checagem simples; se quiser, implementamos dígito verificador)

    @staticmethod
    def _is_valid_cnpj(cnpj: str) -> bool:
        return len(cnpj) == 14 and cnpj.isdigit()  # idem

    @staticmethod
    def _is_valid_cep(cep: str) -> bool:
        return len(cep) == 8 and cep.isdigit()

    @staticmethod
    def _is_valid_cell(num: str) -> bool:
        # Celular BR usual: 11 dígitos (DDD + 9)
        return len(num) == 11 and num.isdigit()

    @staticmethod
    def _is_valid_phone(num: str) -> bool:
        # Telefone fixo aceita 10 dígitos (DDD + 8) ou 11 (algumas regiões)
        return len(num) in (10, 11) and num.isdigit()


    # ---------- Validação de estrutura da planilha ----------
    def validar_planilha(self, df: pd.DataFrame) -> list[str]:
        df.columns = df.columns.str.strip().str.lower()
        erros = []
        for c in self.CAMPOS_OBRIGATORIOS:
            if c not in df.columns:
                erros.append(f"Campo obrigatório ausente: {c}")
        if len(df) > 500:
            erros.append("Limite máximo de 500 linhas por importação.")
        return erros

    # ---------- Builders ----------
    def _perfis_from_row(self, row: dict) -> list[dict]:
        perfis = []
        if self._to_bool(row.get("cliente", True)):
            perfis.append({"tipo_perfil": "CLIENTE"})
        if self._to_bool(row.get("fornecedor", False)):
            perfis.append({"tipo_perfil": "FORNECEDOR"})
        # Se ninguém marcou nada, padrão CLIENTE para não cair em 400
        if not perfis:
            perfis.append({"tipo_perfil": "CLIENTE"})
        return perfis

    def _enderecos_from_row(self, row: dict) -> list[dict]:
        any_addr = any(row.get(k) for k in ["cep", "logradouro", "numero", "bairro", "cidade", "estado", "pais"])
        if not any_addr:
            return []

        cep = self._only_digits(row.get("cep"))
        estado = (row.get("estado") or "").strip().upper()
        if estado and len(estado) > 2:
            estado = estado[:2]

        end = {
            "cep": cep if self._is_valid_cep(cep) else None,
            "logradouro": (row.get("logradouro") or "").strip() or None,
            "numero": (str(row.get("numero") or "").strip() or None),
            "complemento": (row.get("complemento") or "").strip() or None,
            "bairro": (row.get("bairro") or "").strip() or None,
            "cidade": (row.get("cidade") or "").strip() or None,
            "estado": estado or None,
        }

        # país só entra se informado e não-vazio
        pais = (row.get("pais") or "").strip()
        if pais:
            end["pais"] = pais

        # remove chaves None
        end = {k: v for k, v in end.items() if v is not None}
        return [end] if end else []


    # ---------- Consulta de existência ----------
    def verificar_existencia(self, pessoa: dict) -> bool:
        """
        Usa GET /v1/pessoa?termo_busca=... (documento ou nome). Fallback com ?termo=...
        """
        doc_norm = self._only_digits(pessoa.get("documento"))
        nome_norm = self._norm_text(pessoa.get("nome"))
        termo = doc_norm or nome_norm
        if not termo:
            return False

        # 1) tentativa com termo_busca
        try:
            resp = api_get(self.PESSOAS_LIST_PATH, params={"termo_busca": termo})
            itens = resp.get("data", resp) if isinstance(resp, dict) else resp
            if isinstance(itens, list):
                for p in itens:
                    cand_doc = self._only_digits(p.get("documento") or p.get("cpf") or p.get("cnpj") or "")
                    cand_nome = self._norm_text(p.get("nome") or p.get("razaoSocial") or "")
                    if doc_norm and cand_doc and cand_doc == doc_norm:
                        return True
                    if nome_norm and cand_nome and cand_nome == nome_norm:
                        return True
        except Exception:
            pass

        # 2) fallback com termo
        try:
            resp = api_get(self.PESSOAS_LIST_PATH, params={"termo": termo})
            itens = resp.get("data", resp) if isinstance(resp, dict) else resp
            if isinstance(itens, list):
                for p in itens:
                    cand_doc = self._only_digits(p.get("documento") or p.get("cpf") or p.get("cnpj") or "")
                    cand_nome = self._norm_text(p.get("nome") or p.get("razaoSocial") or "")
                    if doc_norm and cand_doc and cand_doc == doc_norm:
                        return True
                    if nome_norm and cand_nome and cand_nome == nome_norm:
                        return True
        except Exception:
            pass

        return False

    # ---------- Montagem e VALIDAÇÃO de payload ----------
    def _payload_pessoa(self, row: dict) -> tuple[dict, list[str], list[str]]:
        """
        Retorna (payload_corrigido, erros, correcoes).
        - erros: mensagens que impedem o POST (ex.: nome vazio, cpf/cnpj inválido)
        - correcoes: notas sobre saneamentos que fizemos (ex.: removemos enderecos vazio)
        """
        correcoes: list[str] = []
        erros: list[str] = []

        tipo = (row.get("tipo") or "FISICA").strip().upper()
        if tipo not in self.TIPOS_PESSOA_VALIDOS:
            erros.append(f"tipo_pessoa inválido: '{tipo}'. Use FISICA, JURIDICA ou ESTRANGEIRA.")
        nome = (row.get("nome") or "").strip()
        if not nome:
            erros.append("nome obrigatório e não pode ser vazio.")

        documento = self._only_digits(row.get("documento"))
        email = (row.get("email") or "").strip()

        # perfis
        perfis = self._perfis_from_row(row)
        # sanity de perfis válidos (defensivo)
        perfis = [p for p in perfis if p.get("tipo_perfil") in self.TIPOS_PERFIL_VALIDOS]
        if not perfis:
            erros.append("perfis deve conter pelo menos um tipo_perfil válido (CLIENTE/FORNECEDOR/TRANSPORTADORA).")

        # contato
        tel = self._only_digits(row.get("telefone"))
        cel = self._only_digits(row.get("celular"))

        if tel and not self._is_valid_phone(tel):
            erros.append("telefone_comercial inválido (use 10 ou 11 dígitos, apenas números).")
        if cel and not self._is_valid_cell(cel):
            erros.append("celular inválido (use 11 dígitos, apenas números).")

        # endereços
        enderecos = self._enderecos_from_row(row)
        if enderecos:
            # valida CEP do primeiro endereço (se presente)
            cep_val = enderecos[0].get("cep")
            if cep_val and not self._is_valid_cep(cep_val):
                erros.append("cep inválido (use 8 dígitos, apenas números).")

        payload = {
            "perfis": perfis,
            "tipo_pessoa": tipo,
            "nome": nome,
            "email": email or None,
            "telefone_comercial": tel or None,
            "celular": cel or None,
            "observacao": (row.get("observacao") or "").strip() or None,
            "codigo": (str(row.get("codigo")) if row.get("codigo") not in (None, "") else None),
            "enderecos": enderecos if enderecos else None,
        }

        if tipo == "FISICA":
            if len(documento) != 11:
                erros.append("cpf obrigatório para FISICA (11 dígitos, apenas números).")
            else:
                payload["cpf"] = documento
            dn = self._date_to_iso(row.get("data_nascimento"))
            if dn:
                payload["data_nascimento"] = dn
        elif tipo == "JURIDICA":
            if len(documento) != 14:
                erros.append("cnpj obrigatório para JURIDICA (14 dígitos, apenas números).")
            else:
                payload["cnpj"] = documento
            if row.get("nome_fantasia"):
                payload["nome_fantasia"] = str(row.get("nome_fantasia")).strip()
            if row.get("inscricao_estadual"):
                payload["inscricao_estadual"] = str(row.get("inscricao_estadual")).strip()
            if row.get("inscricao_municipal"):
                payload["inscricao_municipal"] = str(row.get("inscricao_municipal")).strip()
        else:
            # Estrangeira: sem cpf/cnpj
            pass

        # Remove chaves None/vazias
        cleaned = {}
        for k, v in payload.items():
            if v in (None, ""):
                continue
            if isinstance(v, list) and len(v) == 0:
                continue
            cleaned[k] = v

        # correções informativas (ex.: trims, formatações)
        if email and cleaned.get("email") != email:
            correcoes.append("email foi normalizado.")
        if tel and cleaned.get("telefone_comercial") != tel:
            correcoes.append("telefone foi normalizado (apenas dígitos).")
        if cel and cleaned.get("celular") != cel:
            correcoes.append("celular foi normalizado (apenas dígitos).")

        return cleaned, erros, correcoes

    # ---------- POST com logs detalhados ----------
    def cadastrar_pessoa(self, pessoa_row: dict, debug: bool = False):
        payload, erros, correcoes = self._payload_pessoa(pessoa_row)
        if erros:
            # Se o payload não passa na pré-validação, não devemos chamar a API
            raise RuntimeError(json.dumps({
                "erro": "Erros de validação no payload",
                "detalhes": erros,
                "correcoes_aplicadas": correcoes,
                "payload_corrigido": payload if debug else "oculto (habilite debug)"
            }, ensure_ascii=False))

        try:
            resp = api_post(self.PESSOAS_CREATE_PATH, json=payload)
            return True, {"payload": payload if debug else "ok", "resposta": resp}
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            body = None
            try:
                body = e.response.json()
            except Exception:
                try:
                    body = e.response.text
                except Exception:
                    body = str(e)

            info = {
                "endpoint": self.PESSOAS_CREATE_PATH,
                "status_code": status,
                "error_body": body,
                "payload_enviado": payload if debug else "oculto (habilite debug)",
                "correcoes_aplicadas": correcoes
            }
            raise RuntimeError(json.dumps(info, ensure_ascii=False)) from e
        except Exception as e:
            raise

    # ---------- Pipeline principal ----------
    def processar_upload(self, arquivo_excel, debug: bool = False):
        df = pd.read_excel(arquivo_excel)
        erros_planilha = self.validar_planilha(df)
        if erros_planilha:
            return {"status": "erro", "mensagem": "Erros na planilha", "resumo": [], "erros": erros_planilha}

        cols = [c for c in df.columns if c in self.CAMPOS_VALIDOS]
        df = df[cols].fillna("")

        resultados = []
        for _, row in df.iterrows():
            pessoa = {k: row.get(k) for k in df.columns}
            nome = (pessoa.get("nome") or "").strip()
            doc  = self._only_digits(pessoa.get("documento"))

            # 0) Corrigir/validar payload ANTES de consultar existência (para não buscar por lixo)
            payload_corrigido, erros, _correcoes = self._payload_pessoa(pessoa)
            if erros:
                resultados.append({
                    "pessoa": nome, "documento": doc,
                    "status": "Erro",
                    "mensagem": f"Erros de validação: {', '.join(erros)}",
                    "payload_corrigido": payload_corrigido if debug else None
                })
                continue

            # 1) Verificar duplicidade (após saneamento)
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
                ok, msg = self.cadastrar_pessoa(pessoa, debug=debug)
                resultados.append({
                    "pessoa": nome, "documento": doc,
                    "status": "Cadastrado" if ok else "Erro",
                    "mensagem": "OK" if ok else str(msg),
                    "payload_corrigido": msg.get("payload") if (debug and isinstance(msg, dict)) else None
                })
            except Exception as e:
                resultados.append({
                    "pessoa": nome, "documento": doc,
                    "status": "Erro",
                    "mensagem": str(e)
                })

        return {"status": "ok", "resumo": resultados, "erros": []}
