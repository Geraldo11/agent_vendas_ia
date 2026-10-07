from pathlib import Path

import pytest

from agentes.ambiente import RAIZ, analisar_env, carregar_env, diagnosticar, ler_env, valores_do_env


def nomes_e_valores(texto):
    return {l.nome: l.valor for l in analisar_env(texto)}


# ------------------------------------------------------------------ interpretação do arquivo
def test_formato_basico_comentarios_e_linhas_em_branco():
    assert nomes_e_valores("# comentário\n\nA=1\nB = dois \n") == {"A": "1", "B": "dois"}


def test_export_e_aspas_externas():
    assert nomes_e_valores('export A=1\nB="x y"\nC=\'z\'') == {"A": "1", "B": "x y", "C": "z"}


def test_valor_pode_conter_igual():
    assert nomes_e_valores("URL=https://x.com/?a=b")["URL"] == "https://x.com/?a=b"


def test_linha_sem_igual_e_marcada():
    (linha,) = analisar_env("GROQ_API_KEY")
    assert linha.valor is None and "sem '='" in linha.problema


def test_espaco_no_inicio_e_marcado_mas_o_valor_e_lido():
    (linha,) = analisar_env(" LLM_MODEL=llama")
    assert linha.valor == "llama" and "espaço no início" in linha.problema


def test_o_caso_real_colado_pelo_usuario():
    texto = "LLM_PROVIDER=groq\n LLM_MODEL=llama-3.3-70b-versatile\n GROQ_API_KEY\n"
    problemas = diagnosticar(texto)
    assert any("linha 2" in p and "espaço no início" in p for p in problemas)
    assert any("linha 3" in p and "sem '='" in p for p in problemas)
    assert valores_do_env(analisar_env(texto)) == {"LLM_PROVIDER": "groq", "LLM_MODEL": "llama-3.3-70b-versatile"}


def test_duplicata_com_ultima_vazia_e_apontada():
    problemas = diagnosticar("LLM_PROVIDER=groq\nOUTRA=1\nLLM_PROVIDER=\n")
    assert any("LLM_PROVIDER aparece 2 vezes" in p and "ÚLTIMA ESTÁ VAZIA" in p for p in problemas)


def test_valor_vazio_isolado_e_apontado():
    assert any("valor vazio" in p for p in diagnosticar("A=\n"))


def test_nome_invalido():
    assert any("nome de variável inválido" in p for p in diagnosticar("1ABC=x\n"))


# ------------------------------------------------------------------ carregamento
def escrever(tmp_path, conteudo, codificacao="utf-8"):
    arquivo = tmp_path / ".env"
    arquivo.write_bytes(conteudo.encode(codificacao) if isinstance(conteudo, str) else conteudo)
    return arquivo


def test_carrega_variaveis_ausentes(tmp_path):
    ambiente = {}
    assert carregar_env(escrever(tmp_path, "A=1\nB=2\n"), ambiente) is True
    assert ambiente == {"A": "1", "B": "2"}


def test_nao_sobrescreve_o_que_ja_esta_definido(tmp_path):
    ambiente = {"A": "do-ambiente"}
    carregar_env(escrever(tmp_path, "A=do-arquivo\n"), ambiente)
    assert ambiente["A"] == "do-ambiente"


def test_preenche_variavel_existente_mas_vazia(tmp_path):
    ambiente = {"A": ""}
    carregar_env(escrever(tmp_path, "A=do-arquivo\n"), ambiente)
    assert ambiente["A"] == "do-arquivo"


def test_linha_vazia_no_arquivo_nunca_anula_um_valor_preenchido(tmp_path):
    ambiente = {}
    carregar_env(escrever(tmp_path, "LLM_PROVIDER=groq\nLLM_PROVIDER=\n"), ambiente)
    assert ambiente["LLM_PROVIDER"] == "groq"


def test_o_ultimo_valor_nao_vazio_vence(tmp_path):
    ambiente = {}
    carregar_env(escrever(tmp_path, "A=1\nA=2\n"), ambiente)
    assert ambiente["A"] == "2"


def test_arquivo_inexistente_devolve_false(tmp_path):
    assert carregar_env(tmp_path / "nao-existe.env", {}) is False


# ------------------------------------------------------------------ codificações do Windows
def test_utf8_com_bom_e_lido_e_avisado(tmp_path):
    arquivo = escrever(tmp_path, b"\xef\xbb\xbfA=1\n")
    texto, avisos = ler_env(arquivo)
    assert nomes_e_valores(texto) == {"A": "1"} and any("BOM" in a for a in avisos)
    ambiente = {}
    carregar_env(arquivo, ambiente)
    assert ambiente == {"A": "1"}


def test_utf16_do_powershell_e_lido_e_avisado(tmp_path):
    # .encode("utf-16") já grava UM marcador BOM no início, exatamente como o PowerShell faz com `>`
    arquivo = escrever(tmp_path, "A=1\r\nB=2\r\n".encode("utf-16"))
    texto, avisos = ler_env(arquivo)
    assert nomes_e_valores(texto) == {"A": "1", "B": "2"} and any("UTF-16" in a for a in avisos)


def test_bom_sobrando_nao_corrompe_o_nome_da_primeira_variavel(tmp_path):
    arquivo = escrever(tmp_path, "\ufeffA=1\r\nB=2\r\n".encode("utf-16"))        # dois BOM de propósito
    texto, _ = ler_env(arquivo)
    assert nomes_e_valores(texto) == {"A": "1", "B": "2"}


# ------------------------------------------------------------------ segurança
def test_diagnostico_nunca_revela_valores():
    segredo = "gsk_SEGREDO_123456"
    texto = (
        f" TOKEN_COM_ESPACO={segredo}\n"      # problema de formato E valor secreto na mesma linha
        f"1NOME_INVALIDO={segredo}\n"          # outro problema com valor secreto
        f"DUPLICADA={segredo}\nDUPLICADA=\n"  # duplicata com a última vazia
        " SEM_IGUAL\n"
    )
    problemas = diagnosticar(texto)
    assert len(problemas) >= 4                  # o teste só vale se os problemas realmente existem
    assert segredo not in " | ".join(problemas)


# ------------------------------------------------------------------ o modelo .env.example não pode ter armadilhas
def test_env_example_nao_tem_linhas_ativas_vazias_nem_com_problema():
    exemplo = RAIZ / ".env.example"
    assert exemplo.exists(), ".env.example não encontrado na raiz: restaure-o (ele é o modelo do .env; rode scripts/verificar_repositorio.py)"
    texto = exemplo.read_text(encoding="utf-8")
    ativas = analisar_env(texto)
    assert [l.nome for l in ativas if not l.valor] == [], "linhas NOME= vazias anulam valores no Docker"
    assert [l.nome for l in ativas if l.problema] == []
