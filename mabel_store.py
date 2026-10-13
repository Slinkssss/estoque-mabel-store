import uuid
import psycopg2
from psycopg2.extras import DictCursor
from pathlib import Path
from datetime import date, timedelta
from io import BytesIO
from PIL import Image

import pandas as pd
import streamlit as st


# ------------------------------------------
# 1. CONFIGURAÇÕES
# ------------------------------------------
st.set_page_config(
    page_title="Estoque Mabel Store",
    page_icon="logo_store.png",
    layout="wide",
)

PASTA = Path(__file__).resolve().parent
# A conexão é configurada em .streamlit/secrets.toml localmente e em Streamlit Cloud.
# Não coloque a senha diretamente neste arquivo.

class ConexaoPostgres:
    """Adaptador pequeno para manter o estilo execute/fetch do código original."""
    def __init__(self, raw):
        self.raw = raw
        self.dirty = False

    def __enter__(self):
        return self

    def __exit__(self, tipo, valor, traceback):
        try:
            if tipo is None:
                self.raw.commit()
                if self.dirty:
                    # Atualiza os caches depois de qualquer alteração no banco.
                    st.cache_data.clear()
            else:
                self.raw.rollback()
        finally:
            self.raw.close()
        return False

    def execute(self, sql, parametros=None):
        sql = sql.replace("?", "%s")
        sql = sql.replace("BEGIN IMMEDIATE", "BEGIN")
        comando = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        if comando in {"INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP", "TRUNCATE", "REPLACE"}:
            self.dirty = True
        cursor = self.raw.cursor(cursor_factory=DictCursor)
        cursor.execute(sql, parametros or ())
        return cursor


def conectar():
    try:
        url = st.secrets["SUPABASE_DB_URL"]
    except Exception as erro:
        raise RuntimeError(
            "A conexão com o Supabase ainda não foi configurada. "
            "Adicione SUPABASE_DB_URL nas configurações de Secrets."
        ) from erro
    raw = psycopg2.connect(url, sslmode="require", connect_timeout=8, application_name="EstoqueMabelStore")
    return ConexaoPostgres(raw)


# ------------------------------------------
# 2. BANCO DE DADOS
# ------------------------------------------
@st.cache_resource(show_spinner=False)
def criar_tabelas():
    """Confere as tabelas uma vez por execução do app, não a cada interação."""
    with conectar() as conexao:
        tabelas = conexao.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('produtos', 'movimentacoes_estoque', 'vendas', 'pagamentos_dividas')
        """).fetchall()
        existentes = {linha[0] for linha in tabelas}
        esperadas = {'produtos', 'movimentacoes_estoque', 'vendas', 'pagamentos_dividas'}
        faltando = esperadas - existentes
        if faltando:
            raise RuntimeError(
                "Faltam tabelas no Supabase: " + ", ".join(sorted(faltando))
            )
        # Identificador opcional para agrupar itens que pertencem à mesma venda.
        conexao.execute("ALTER TABLE vendas ADD COLUMN IF NOT EXISTS venda_grupo_id TEXT")



def otimizar_foto(arquivo, limite=900, qualidade=82):
    """Redimensiona fotos antes de salvá-las, reduzindo tráfego e memória."""
    if not arquivo:
        return None
    try:
        imagem = Image.open(BytesIO(arquivo)).convert("RGB")
        imagem.thumbnail((limite, limite), Image.Resampling.LANCZOS)
        saida = BytesIO()
        imagem.save(saida, format="JPEG", quality=qualidade, optimize=True)
        return saida.getvalue()
    except Exception as erro:
        raise ValueError("Não foi possível processar a imagem. Tente outro arquivo JPG ou PNG.") from erro


def cadastrar_produto(nome, categoria, custo, preco, quantidade, foto):
    codigo = uuid.uuid4().hex
    with conectar() as conexao:
        produto_id = conexao.execute("""
            INSERT INTO produtos
                (codigo, nome, categoria, custo, preco, quantidade, foto)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """, (codigo, nome, categoria, custo, preco, quantidade, foto)).fetchone()[0]
        if int(quantidade) > 0:
            conexao.execute("""
                INSERT INTO movimentacoes_estoque
                    (produto_id, produto_nome, tipo, quantidade, saldo_anterior, saldo_novo, observacao)
                VALUES (?, ?, 'Estoque inicial', ?, 0, ?, 'Quantidade informada no cadastro')
            """, (produto_id, nome, int(quantidade), int(quantidade)))


def separar_categorias(valor):
    """Lê categorias múltiplas separadas por | e mantém compatibilidade com dados antigos."""
    if not valor:
        return []
    return list(dict.fromkeys(parte.strip() for parte in str(valor).split("|") if parte.strip()))


@st.cache_data(ttl=20, show_spinner=False)
def listar_produtos(busca="", incluir_fotos=True):
    with conectar() as conexao:
        colunas = "*" if incluir_fotos else "id, codigo, nome, categoria, custo, preco, quantidade"
        if busca:
            resultado = conexao.execute(f"""
                SELECT {colunas} FROM produtos
                WHERE nome ILIKE ? OR categoria ILIKE ?
                ORDER BY nome
            """, (f"%{busca}%", f"%{busca}%"))
        else:
            resultado = conexao.execute(f"SELECT {colunas} FROM produtos ORDER BY nome")
        produtos = [dict(linha) for linha in resultado.fetchall()]
        for produto in produtos:
            if isinstance(produto.get("foto"), memoryview):
                produto["foto"] = bytes(produto["foto"])
        return produtos


def listar_fotos_produtos(ids):
    """Busca imagens somente para os produtos que serão exibidos na tela."""
    ids = [int(item) for item in ids]
    if not ids:
        return {}
    marcadores = ",".join(["?"] * len(ids))
    with conectar() as conexao:
        linhas = conexao.execute(
            f"SELECT id, foto FROM produtos WHERE id IN ({marcadores})", tuple(ids)
        ).fetchall()
    return {int(linha["id"]): (bytes(linha["foto"]) if isinstance(linha["foto"], memoryview) else linha["foto"]) for linha in linhas}


@st.cache_data(ttl=60, show_spinner=False)
def listar_categorias():
    with conectar() as conexao:
        resultado = conexao.execute("""
            SELECT categoria
            FROM (
                SELECT DISTINCT categoria
                FROM produtos
                WHERE categoria IS NOT NULL AND TRIM(categoria) != ''
            ) AS categorias
            ORDER BY LOWER(categoria)
        """)
        categorias = []
        for linha in resultado.fetchall():
            categorias.extend(separar_categorias(linha[0]))
        return sorted(set(categorias), key=str.casefold)


def atualizar_categorias_produto(produto_id, categorias):
    categorias_limpa = list(dict.fromkeys(str(c).strip() for c in categorias if str(c).strip()))
    texto = " | ".join(categorias_limpa) if categorias_limpa else "Sem categoria"
    with conectar() as conexao:
        conexao.execute("UPDATE produtos SET categoria = ? WHERE id = ?", (texto, int(produto_id)))


def atualizar_foto_produto(produto_id, foto):
    with conectar() as conexao:
        conexao.execute("UPDATE produtos SET foto = ? WHERE id = ?", (foto, int(produto_id)))


def atualizar_precos_produto(produto_id, custo, preco):
    """Atualiza o custo e o preço de venda de um produto existente."""
    if float(custo) < 0 or float(preco) < 0:
        raise ValueError("Os valores não podem ser negativos.")
    with conectar() as conexao:
        conexao.execute(
            "UPDATE produtos SET custo = ?, preco = ? WHERE id = ?",
            (float(custo), float(preco), int(produto_id)),
        )


def excluir_produto(produto_id):
    with conectar() as conexao:
        conexao.execute("DELETE FROM produtos WHERE id = ?", (produto_id,))


def ajustar_estoque(produto_id, quantidade, operacao, observacao=""):
    quantidade = int(quantidade)
    if quantidade < 1:
        raise ValueError("Informe uma quantidade maior que zero.")

    with conectar() as conexao:
        conexao.execute("BEGIN IMMEDIATE")
        produto = conexao.execute(
            "SELECT nome, quantidade FROM produtos WHERE id = ?", (produto_id,)
        ).fetchone()
        if produto is None:
            raise ValueError("Esse produto não foi encontrado.")

        saldo_anterior = int(produto["quantidade"])
        if operacao == "Adicionar":
            saldo_novo = saldo_anterior + quantidade
        else:
            if saldo_anterior < quantidade:
                raise ValueError(
                    f"Não é possível retirar {quantidade} unidade(s). "
                    f"Há apenas {saldo_anterior} no estoque."
                )
            saldo_novo = saldo_anterior - quantidade

        conexao.execute(
            "UPDATE produtos SET quantidade = ? WHERE id = ?",
            (saldo_novo, produto_id),
        )
        conexao.execute("""
            INSERT INTO movimentacoes_estoque
                (produto_id, produto_nome, tipo, quantidade, saldo_anterior, saldo_novo, observacao)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            produto_id, produto["nome"], "Entrada manual" if operacao == "Adicionar" else "Saída manual",
            quantidade, saldo_anterior, saldo_novo, observacao.strip() or None,
        ))


def listar_movimentacoes():
    with conectar() as conexao:
        resultado = conexao.execute(
            "SELECT * FROM movimentacoes_estoque ORDER BY id DESC LIMIT 300"
        )
        return [dict(linha) for linha in resultado.fetchall()]


def listar_todas_movimentacoes():
    """Lista todas as movimentações para permitir exclusões individuais."""
    with conectar() as conexao:
        resultado = conexao.execute(
            "SELECT * FROM movimentacoes_estoque ORDER BY id DESC"
        )
        return [dict(linha) for linha in resultado.fetchall()]


def excluir_movimentacao(movimentacao_id):
    """Exclui somente o registro selecionado, sem alterar o saldo do produto."""
    with conectar() as conexao:
        conexao.execute(
            "DELETE FROM movimentacoes_estoque WHERE id = ?",
            (int(movimentacao_id),),
        )


def excluir_todas_movimentacoes():
    """Apaga todos os registros do histórico de movimentações."""
    with conectar() as conexao:
        conexao.execute("DELETE FROM movimentacoes_estoque")


def zerar_estoque():
    """Zera as quantidades dos produtos e registra a operação no histórico."""
    with conectar() as conexao:
        conexao.execute("BEGIN IMMEDIATE")
        produtos = conexao.execute("""
            SELECT id, nome, quantidade
            FROM produtos
            WHERE quantidade > 0
        """).fetchall()

        for produto in produtos:
            quantidade_anterior = int(produto["quantidade"])
            conexao.execute(
                "UPDATE produtos SET quantidade = 0 WHERE id = ?",
                (produto["id"],),
            )
            conexao.execute("""
                INSERT INTO movimentacoes_estoque
                    (produto_id, produto_nome, tipo, quantidade,
                     saldo_anterior, saldo_novo, observacao)
                VALUES (?, ?, 'Zeragem de estoque', ?, ?, 0, ?)
            """, (
                produto["id"], produto["nome"], quantidade_anterior,
                quantidade_anterior, "Zeragem manual do estoque",
            ))
        return len(produtos)


def excluir_todos_produtos():
    """Exclui os produtos cadastrados sem apagar vendas nem movimentações."""
    with conectar() as conexao:
        conexao.execute("BEGIN IMMEDIATE")
        quantidade = conexao.execute(
            "SELECT COUNT(*) FROM produtos"
        ).fetchone()[0]
        conexao.execute("DELETE FROM produtos")
        return quantidade


def registrar_venda(produto_id, cliente, quantidade, forma_pagamento, telefone_cliente="", data_prevista_pagamento=None):
    with conectar() as conexao:
        conexao.execute("BEGIN IMMEDIATE")
        produto = conexao.execute(
            "SELECT id, nome, preco, custo, quantidade FROM produtos WHERE id = ?",
            (produto_id,),
        ).fetchone()

        if produto is None:
            raise ValueError("Esse produto não foi encontrado.")
        if quantidade < 1:
            raise ValueError("A quantidade precisa ser pelo menos 1.")
        if produto["quantidade"] < quantidade:
            raise ValueError(
                f"Estoque insuficiente. Há apenas {produto['quantidade']} unidade(s)."
            )

        total = float(produto["preco"]) * int(quantidade)
        status_pagamento = "Devendo" if forma_pagamento == "A pagar" else "Pago"
        # Mantém o registro interno para os indicadores financeiros; a tela de histórico
        # mostra somente as vendas que ainda têm saldo a receber.
        conexao.execute("""
            INSERT INTO vendas
                (produto_id, produto_nome, cliente, telefone_cliente, quantidade,
                 valor_unitario, custo_unitario, total, forma_pagamento, status_pagamento,
                 valor_pago, data_prevista_pagamento)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            produto["id"], produto["nome"], cliente.strip(),
            telefone_cliente.strip() or None, int(quantidade),
            float(produto["preco"]), float(produto["custo"]), total,
            forma_pagamento, status_pagamento, total if status_pagamento == "Pago" else 0.0,
            data_prevista_pagamento if forma_pagamento == "A pagar" else None,
        ))
        saldo_novo = int(produto["quantidade"]) - int(quantidade)
        conexao.execute(
            "UPDATE produtos SET quantidade = ? WHERE id = ?",
            (saldo_novo, produto_id),
        )
        conexao.execute("""
            INSERT INTO movimentacoes_estoque
                (produto_id, produto_nome, tipo, quantidade, saldo_anterior, saldo_novo, observacao)
            VALUES (?, ?, 'Saída por venda', ?, ?, ?, ?)
        """, (
            produto_id, produto["nome"], int(quantidade), int(produto["quantidade"]),
            saldo_novo, f"Venda para {cliente.strip()}"
        ))
    listar_vendas.clear()


def registrar_venda_varios(itens, cliente, forma_pagamento, telefone_cliente="", data_prevista_pagamento=None):
    """Registra todos os itens de uma compra numa transação só, com estoque validado."""
    if not itens:
        raise ValueError("Adicione pelo menos um produto à venda.")
    grupo_id = uuid.uuid4().hex
    with conectar() as conexao:
        conexao.execute("BEGIN IMMEDIATE")
        preparados = []
        total_geral = 0.0
        for item in itens:
            produto = conexao.execute(
                "SELECT id, nome, preco, custo, quantidade FROM produtos WHERE id = ? FOR UPDATE",
                (int(item["produto_id"]),),
            ).fetchone()
            quantidade = int(item["quantidade"])
            if produto is None:
                raise ValueError("Um dos produtos selecionados não foi encontrado.")
            if quantidade < 1:
                raise ValueError(f"A quantidade de {produto['nome']} precisa ser pelo menos 1.")
            if int(produto["quantidade"]) < quantidade:
                raise ValueError(f"Estoque insuficiente para {produto['nome']}. Há apenas {produto['quantidade']} unidade(s).")
            total_item = round(float(produto["preco"]) * quantidade, 2)
            total_geral += total_item
            preparados.append((produto, quantidade, total_item))

        status_pagamento = "Devendo" if forma_pagamento == "A pagar" else "Pago"
        for produto, quantidade, total_item in preparados:
            # Mantém o registro para os indicadores financeiros, mas a tela de histórico
            # exibe somente vendas com saldo pendente.
            conexao.execute("""
                INSERT INTO vendas
                    (produto_id, produto_nome, cliente, telefone_cliente, quantidade,
                     valor_unitario, custo_unitario, total, forma_pagamento, status_pagamento,
                     valor_pago, data_prevista_pagamento, venda_grupo_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                produto["id"], produto["nome"], cliente.strip(), telefone_cliente.strip() or None,
                quantidade, float(produto["preco"]), float(produto["custo"]), total_item,
                forma_pagamento, status_pagamento, total_item if status_pagamento == "Pago" else 0.0,
                data_prevista_pagamento if forma_pagamento == "A pagar" else None, grupo_id,
            ))
            saldo_novo = int(produto["quantidade"]) - quantidade
            conexao.execute("UPDATE produtos SET quantidade = ? WHERE id = ?", (saldo_novo, produto["id"]))
            conexao.execute("""
                INSERT INTO movimentacoes_estoque
                    (produto_id, produto_nome, tipo, quantidade, saldo_anterior, saldo_novo, observacao)
                VALUES (?, ?, 'Saída por venda', ?, ?, ?, ?)
            """, (produto["id"], produto["nome"], quantidade, int(produto["quantidade"]), saldo_novo,
                  f"Venda {grupo_id[:8]} para {cliente.strip()}"))
    listar_vendas.clear()
    return round(total_geral, 2), grupo_id


@st.cache_data(ttl=15, show_spinner=False)
def listar_vendas():
    """Lista apenas vendas com saldo pendente; as pagas ficam ocultas da interface."""
    with conectar() as conexao:
        resultado = conexao.execute(
            "SELECT * FROM vendas WHERE status_pagamento IN ('Devendo', 'Parcial') ORDER BY id DESC"
        )
        return [dict(linha) for linha in resultado.fetchall()]


def _excluir_vendas_com_reversao(conexao, vendas_para_excluir):
    """Exclui vendas e pagamentos vinculados, devolvendo os itens ao estoque."""
    for venda in vendas_para_excluir:
        produto_id = venda["produto_id"]
        quantidade = int(venda["quantidade"] or 0)
        produto = None
        if produto_id is not None:
            produto = conexao.execute(
                "SELECT nome, quantidade FROM produtos WHERE id = ?", (produto_id,)
            ).fetchone()

        # Como a venda baixou o estoque, o cancelamento devolve essa quantidade.
        if produto is not None and quantidade > 0:
            saldo_anterior = int(produto["quantidade"] or 0)
            saldo_novo = saldo_anterior + quantidade
            conexao.execute(
                "UPDATE produtos SET quantidade = ? WHERE id = ?",
                (saldo_novo, produto_id),
            )
            conexao.execute("""
                INSERT INTO movimentacoes_estoque
                    (produto_id, produto_nome, tipo, quantidade, saldo_anterior, saldo_novo, observacao)
                VALUES (?, ?, 'Estorno de venda excluída', ?, ?, ?, ?)
            """, (
                produto_id, produto["nome"], quantidade, saldo_anterior, saldo_novo,
                f"Exclusão da venda #{venda['id']} — cliente: {venda['cliente']}"
            ))

        conexao.execute(
            "DELETE FROM pagamentos_dividas WHERE venda_id = ?", (venda["id"],)
        )
        conexao.execute("DELETE FROM vendas WHERE id = ?", (venda["id"],))


def excluir_venda(venda_id):
    """Exclui uma venda específica, seus pagamentos e reverte o estoque."""
    with conectar() as conexao:
        conexao.execute("BEGIN IMMEDIATE")
        venda = conexao.execute(
            "SELECT * FROM vendas WHERE id = ?", (int(venda_id),)
        ).fetchone()
        if venda is None:
            raise ValueError("Venda não encontrada.")
        _excluir_vendas_com_reversao(conexao, [venda])


def excluir_todas_vendas():
    """Exclui todas as vendas e pagamentos vinculados, revertendo o estoque."""
    with conectar() as conexao:
        conexao.execute("BEGIN IMMEDIATE")
        vendas = conexao.execute("SELECT * FROM vendas ORDER BY id DESC").fetchall()
        _excluir_vendas_com_reversao(conexao, vendas)
        return len(vendas)


def registrar_pagamento_divida(venda_id, valor):
    """Registra um pagamento parcial ou total e atualiza o saldo restante."""
    valor = round(float(valor), 2)
    if valor <= 0:
        raise ValueError("O pagamento precisa ser maior que zero.")
    with conectar() as conexao:
        conexao.execute("BEGIN IMMEDIATE")
        venda = conexao.execute(
            "SELECT total, COALESCE(valor_pago, 0) AS valor_pago FROM vendas WHERE id = ?",
            (int(venda_id),),
        ).fetchone()
        if venda is None:
            raise ValueError("Venda não encontrada.")
        total = round(float(venda["total"] or 0), 2)
        ja_pago = round(float(venda["valor_pago"] or 0), 2)
        restante = round(total - ja_pago, 2)
        if valor > restante + 0.001:
            raise ValueError(f"O valor informado é maior que o saldo de {moeda(restante)}.")
        acumulado = round(ja_pago + valor, 2)
        status = "Pago" if acumulado >= total - 0.001 else "Parcial"
        conexao.execute(
            "INSERT INTO pagamentos_dividas (venda_id, valor) VALUES (?, ?)",
            (int(venda_id), valor),
        )
        conexao.execute(
            "UPDATE vendas SET valor_pago = ?, status_pagamento = ? WHERE id = ?",
            (acumulado, status, int(venda_id)),
        )
    listar_vendas.clear()


def listar_pagamentos_divida(venda_id):
    """Retorna os pagamentos individuais registrados para uma venda."""
    with conectar() as conexao:
        resultado = conexao.execute(
            "SELECT valor, criado_em FROM pagamentos_dividas WHERE venda_id = ? ORDER BY id DESC",
            (int(venda_id),),
        )
        return [dict(linha) for linha in resultado.fetchall()]


def marcar_venda_paga(venda_id):
    """Registra o saldo restante como pago; a venda deixa de aparecer na lista de pendências."""
    with conectar() as conexao:
        venda = conexao.execute(
            "SELECT total, COALESCE(valor_pago, 0) AS valor_pago FROM vendas WHERE id = ?",
            (int(venda_id),),
        ).fetchone()
    if venda is None:
        raise ValueError("Venda não encontrada.")
    restante = round(float(venda["total"] or 0) - float(venda["valor_pago"] or 0), 2)
    if restante > 0:
        registrar_pagamento_divida(venda_id, restante)


def moeda(valor):
    return f"R$ {float(valor or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


criar_tabelas()


# ------------------------------------------
# 3. ESTILO VISUAL
# ------------------------------------------
st.markdown("""
<style>
    :root {
        --mabel-navy: #59465F;
        --mabel-blue: #A58AB3;
        --mabel-blue-hover: #8D719C;
        --mabel-rose: #C5A2B9;
        --mabel-bg: #FBF8F4;
        --mabel-surface: #FFFFFF;
        --mabel-border: #E8DDE9;
        --mabel-muted: #88788D;
        --mabel-lilac-light: #F2EAF4;
        --mabel-cream: #F9F3EB;
    }

    html, body, [class*="css"] {
        font-family: "Segoe UI", Arial, sans-serif;
    }
    .stApp, [data-testid="stMain"] {
        background: var(--mabel-bg);
        color: var(--mabel-navy);
    }
    .block-container {
        max-width: 1460px;
        padding-top: 1.6rem;
        padding-bottom: 3rem;
    }
    h1, h2, h3, h4 {
        color: var(--mabel-navy) !important;
        letter-spacing: -0.025em;
        font-weight: 700 !important;
    }
    h1 { font-size: clamp(1.8rem, 2.6vw, 2.35rem) !important; }
    h2 { font-size: 1.55rem !important; }
    h3 { font-size: 1.2rem !important; }
    p, li, label, [data-testid="stCaptionContainer"] { color: #746579; }
    [data-testid="stCaptionContainer"] { font-size: 0.88rem; }

    /* Barra lateral em lavanda */
    [data-testid="stSidebar"] {
        background: #F3EBF4;
        border-right: 1px solid #E4D6E8;
    }
    [data-testid="stSidebar"] > div:first-child { padding-top: 1.2rem; }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 { color: var(--mabel-navy) !important; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #88778E; }
    [data-testid="stSidebar"] [role="radiogroup"] { gap: 0.3rem; }
    [data-testid="stSidebar"] [role="radiogroup"] label {
        padding: 0.55rem 0.7rem;
        border-radius: 10px;
        transition: background-color .15s ease;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover { background: #E7D9EB; }

    /* Cartões e indicadores */
    [data-testid="stMetric"] {
        background: var(--mabel-surface);
        border: 1px solid var(--mabel-border);
        border-radius: 15px;
        padding: 1rem 1.15rem;
        box-shadow: 0 4px 14px rgba(106, 76, 115, 0.06);
    }
    [data-testid="stMetricLabel"] {
        color: var(--mabel-muted) !important;
        font-size: 0.88rem;
        font-weight: 600;
    }
    [data-testid="stMetricValue"] {
        color: var(--mabel-navy) !important;
        font-size: clamp(1.15rem, 1.8vw, 1.75rem) !important;
        font-weight: 750;
        letter-spacing: -0.025em;
        line-height: 1.2 !important;
        min-width: 0 !important;
        overflow: visible !important;
        text-overflow: clip !important;
        white-space: normal !important;
        overflow-wrap: anywhere !important;
    }
    [data-testid="stMetricValue"] > div,
    [data-testid="stMetricValue"] p {
        font-size: inherit !important;
        line-height: inherit !important;
        min-width: 0 !important;
        overflow: visible !important;
        text-overflow: clip !important;
        white-space: normal !important;
        overflow-wrap: anywhere !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--mabel-border) !important;
        border-radius: 15px !important;
        background: rgba(255,255,255,.88);
    }
    [data-testid="stExpander"] {
        border: 1px solid var(--mabel-border);
        border-radius: 12px;
        background: #FFFCFE;
    }

    /* Campos e formulários */
    .stTextInput input, .stNumberInput input, .stTextArea textarea,
    [data-baseweb="select"] > div, [data-testid="stDateInput"] input {
        background: #FFFFFF !important;
        color: var(--mabel-navy) !important;
        border: 1px solid #DCCBDD !important;
        border-radius: 10px !important;
    }
    .stTextInput input:focus, .stNumberInput input:focus,
    .stTextArea textarea:focus, [data-testid="stDateInput"] input:focus {
        border-color: var(--mabel-blue) !important;
        box-shadow: 0 0 0 2px rgba(165,138,179,.18) !important;
    }
    [data-baseweb="select"] * { color: var(--mabel-navy) !important; }
    [data-testid="stFileUploader"] section {
        border-radius: 12px;
        border-color: #DCCBDD;
        background: #FFFCFE;
    }

    /* Botões lavanda */
    .stButton > button, .stFormSubmitButton > button,
    [data-testid="stDownloadButton"] > button {
        background: var(--mabel-blue);
        color: #FFFFFF !important;
        border: 1px solid var(--mabel-blue);
        border-radius: 10px;
        min-height: 2.65rem;
        font-weight: 650;
        transition: background .15s ease, transform .15s ease, box-shadow .15s ease;
        box-shadow: 0 3px 8px rgba(128,94,143,.12);
    }
    .stButton > button *, .stFormSubmitButton > button *,
    [data-testid="stDownloadButton"] > button * { color: #FFFFFF !important; }
    .stButton > button:hover, .stFormSubmitButton > button:hover,
    [data-testid="stDownloadButton"] > button:hover {
        background: var(--mabel-blue-hover);
        border-color: var(--mabel-blue-hover);
        box-shadow: 0 4px 10px rgba(128,94,143,.18);
        transform: translateY(-1px);
    }
    .stButton > button:focus, .stFormSubmitButton > button:focus {
        box-shadow: 0 0 0 3px rgba(165,138,179,.22);
    }

    /* Abas, tabelas, alertas e links */
    [data-baseweb="tab-list"] { gap: 8px; }
    [data-baseweb="tab"] { border-radius: 9px 9px 0 0; color: var(--mabel-navy); }
    [aria-selected="true"] { border-bottom-color: var(--mabel-blue) !important; }
    [data-testid="stDataFrame"], [data-testid="stTable"] {
        border: 1px solid var(--mabel-border);
        border-radius: 12px;
        overflow: hidden;
        background: #FFFFFF;
    }
    hr { border-color: var(--mabel-border) !important; margin: 1.25rem 0; }
    [data-testid="stAlert"] { border-radius: 12px; }
    a { color: #8D719C !important; }

    @media (max-width: 768px) {
        .block-container { padding: 1rem 1rem 2rem; }
        [data-testid="stMetric"] { padding: .8rem; }
    }


    /* Grade do catálogo: 3 produtos por linha no computador e 2 no celular. */
    div[class*="st-key-catalogo_grade_responsiva"] div[data-testid="stHorizontalBlock"] {
        display: grid !important;
        grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
        gap: 0.8rem !important;
    }
    div[class*="st-key-catalogo_grade_responsiva"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
        width: auto !important;
        min-width: 0 !important;
        flex: unset !important;
    }
    @media (max-width: 768px) {
        div[class*="st-key-catalogo_grade_responsiva"] div[data-testid="stHorizontalBlock"] {
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
            gap: 0.55rem !important;
        }
        div[class*="st-key-catalogo_grade_responsiva"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
            width: auto !important;
            min-width: 0 !important;
            flex: unset !important;
        }
    }

    /* Ajustes responsivos: preservam as imagens originais e evitam colunas estreitas no celular. */
    @media (max-width: 768px) {
        .block-container {
            padding: 0.8rem 0.75rem 2rem 0.75rem !important;
            max-width: 100% !important;
        }
        h1 { font-size: 1.55rem !important; }
        h2 { font-size: 1.35rem !important; }
        h3 { font-size: 1.15rem !important; }
        div[data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important;
            gap: 0.65rem !important;
        }
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
            flex: 1 1 100% !important;
            width: 100% !important;
            min-width: 100% !important;
        }
        div[data-testid="stMetric"] {
            padding: 0.65rem !important;
        }
        div[data-testid="stImage"] img {
            max-width: 100% !important;
            height: auto !important;
            object-fit: contain !important;
        }
        div[data-testid="stVerticalBlock"] > div {
            min-width: 0;
        }
        .stButton > button, .stDownloadButton > button {
            width: 100%;
            min-height: 2.7rem;
        }
        input, textarea, [data-baseweb="select"] {
            max-width: 100% !important;
        }
    }
    @media (max-width: 420px) {
        .block-container {
            padding-left: 0.55rem !important;
            padding-right: 0.55rem !important;
        }
        div[data-testid="stMetricValue"] { font-size: 1.35rem !important; }
    }

</style>
""", unsafe_allow_html=True)


# ------------------------------------------
# 4. MENU E DADOS GERAIS
# ------------------------------------------
if (PASTA / "logo_store.png").exists():
    st.sidebar.image(str(PASTA / "logo_store.png"), width=170)
else:
    st.sidebar.title("📦 Mabel Store")

st.sidebar.caption("Sistema de estoque e vendas")
st.sidebar.divider()
pagina = st.sidebar.radio(
    "Menu Principal:",
    ["Dashboard", "Cadastrar Produtos", "Estoque", "Catálogo Visual", "Controle de Dívidas", "Vendas"],
)

with conectar() as conexao:
    totais = conexao.execute("""
        SELECT COUNT(*), COALESCE(SUM(quantidade), 0),
               COALESCE(SUM(custo * quantidade), 0)
        FROM produtos
    """).fetchone()

total_produtos, total_unidades, valor_estoque = totais

st.title("Estoque Mabel Store")
st.caption("Gestão da loja · Produtos, estoque, vendas e financeiro")
st.divider()


# ------------------------------------------
# 5. DASHBOARD FINANCEIRO
# ------------------------------------------
if pagina == "Dashboard":
    st.subheader("Dashboard financeiro")
    st.caption("Acompanhe o faturamento, os pagamentos e o desempenho da loja.")

    # Os indicadores são calculados no banco depois que o período é escolhido.
    # Assim não precisamos transferir todas as vendas para o navegador/app.

    # Personalização do dashboard: período e visibilidade dos indicadores.
    hoje_dashboard = date.today()
    with st.expander("Personalizar indicadores do dashboard", expanded=True):
        st.caption("Escolha o período dos indicadores e quais valores deseja exibir. Essas opções só alteram a visualização, sem modificar os registros.")
        periodo_dashboard = st.selectbox(
            "Período",
            ["Últimos 30 dias", "Últimos 3 meses", "Últimos 12 meses", "Este mês", "Este ano", "Todo o período", "Personalizado"],
            index=0,
            key="periodo_indicadores_dashboard",
        )
        data_inicio_dashboard = None
        data_fim_dashboard = hoje_dashboard

        if periodo_dashboard == "Últimos 30 dias":
            data_inicio_dashboard = hoje_dashboard - timedelta(days=29)
        elif periodo_dashboard == "Últimos 3 meses":
            data_inicio_dashboard = hoje_dashboard - timedelta(days=89)
        elif periodo_dashboard == "Últimos 12 meses":
            data_inicio_dashboard = hoje_dashboard - timedelta(days=364)
        elif periodo_dashboard == "Este mês":
            data_inicio_dashboard = hoje_dashboard.replace(day=1)
        elif periodo_dashboard == "Este ano":
            data_inicio_dashboard = date(hoje_dashboard.year, 1, 1)
        elif periodo_dashboard == "Personalizado":
            col_inicio, col_fim = st.columns(2)
            with col_inicio:
                data_inicio_dashboard = st.date_input(
                    "Data inicial", value=hoje_dashboard.replace(day=1), key="dashboard_data_inicio_custom"
                )
            with col_fim:
                data_fim_dashboard = st.date_input(
                    "Data final", value=hoje_dashboard, key="dashboard_data_fim_custom"
                )

        st.divider()
        col_faturamento, col_lucro = st.columns(2)
        mostrar_faturamento = col_faturamento.checkbox(
            "Mostrar faturamento recebido", value=True, key="mostrar_faturamento_dashboard"
        )
        mostrar_lucro = col_lucro.checkbox(
            "Mostrar lucro bruto estimado", value=True, key="mostrar_lucro_dashboard"
        )

    periodo_valido = not (data_inicio_dashboard is not None and data_inicio_dashboard > data_fim_dashboard)
    faturamento_recebido = 0.0
    valores_a_receber = 0.0
    quantidade_vendas = 0
    lucro_estimado = 0.0

    if not periodo_valido:
        st.error("A data inicial não pode ser posterior à data final. Ajuste o período para ver os indicadores.")
    else:
        condicao_data = ""
        parametros = []
        if data_inicio_dashboard is not None:
            condicao_data = "WHERE (criado_em AT TIME ZONE 'America/Sao_Paulo')::date >= ? AND (criado_em AT TIME ZONE 'America/Sao_Paulo')::date <= ?"
            parametros = [data_inicio_dashboard.isoformat(), data_fim_dashboard.isoformat()]
        with conectar() as conexao:
            resumo = conexao.execute(f"""
                SELECT
                    COUNT(*) AS quantidade,
                    COALESCE(SUM(COALESCE(valor_pago, 0)), 0) AS recebido,
                    COALESCE(SUM(CASE WHEN status_pagamento IN ('Devendo', 'Parcial')
                        THEN GREATEST(COALESCE(total, 0) - COALESCE(valor_pago, 0), 0) ELSE 0 END), 0) AS a_receber,
                    COALESCE(SUM(CASE WHEN status_pagamento = 'Pago'
                        THEN (COALESCE(valor_unitario, 0) - COALESCE(custo_unitario, 0)) * COALESCE(quantidade, 0)
                        ELSE 0 END), 0) AS lucro
                FROM vendas
                {condicao_data}
            """, tuple(parametros)).fetchone()
        faturamento_recebido = float(resumo["recebido"] or 0)
        valores_a_receber = float(resumo["a_receber"] or 0)
        quantidade_vendas = int(resumo["quantidade"] or 0)
        lucro_estimado = float(resumo["lucro"] or 0)

    if periodo_dashboard == "Todo o período":
        legenda_periodo = "Todo o período"
    elif data_inicio_dashboard is not None and data_inicio_dashboard <= data_fim_dashboard:
        legenda_periodo = f"{data_inicio_dashboard.strftime('%d/%m/%Y')} a {data_fim_dashboard.strftime('%d/%m/%Y')}"
    else:
        legenda_periodo = "Período inválido"
    st.caption(f"Os indicadores abaixo consideram vendas registradas em: {legenda_periodo}.")

    indicadores = []
    if mostrar_faturamento:
        indicadores.append(("Faturamento recebido no período", moeda(faturamento_recebido)))
    if mostrar_lucro:
        indicadores.append(("Lucro bruto estimado no período", moeda(lucro_estimado)))
    indicadores.extend([
        ("Vendas no período", quantidade_vendas),
        ("A receber nessas vendas", moeda(valores_a_receber)),
    ])

    colunas_indicadores = st.columns(len(indicadores))
    for coluna, (rotulo, valor) in zip(colunas_indicadores, indicadores):
        coluna.metric(rotulo, valor)

    st.divider()
    st.subheader("Visão do estoque")
    e1, e2 = st.columns(2)
    e1.metric("Produtos cadastrados", total_produtos)
    e2.metric("Unidades em estoque", total_unidades)
    st.info("Use o menu lateral para cadastrar produtos, ajustar o estoque e registrar vendas.")


# ------------------------------------------
# 6. PRODUTOS
# ------------------------------------------
elif pagina == "Cadastrar Produtos":
    st.subheader("Cadastrar produto")
    categorias_salvas = listar_categorias()
    opcoes_categoria = categorias_salvas.copy()
    if "Sem categoria" not in opcoes_categoria:
        opcoes_categoria.append("Sem categoria")

    with st.form("form_produto", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            nome = st.text_input("Nome do produto *").strip()
            categorias_selecionadas = st.multiselect(
                "Categorias salvas (você pode escolher várias)",
                options=categorias_salvas,
                help="Um produto pode pertencer a várias categorias.",
            )
            novas_categorias = st.text_input(
                "Novas categorias (opcional)",
                placeholder="Separe várias categorias com vírgula",
                help="Exemplo: Verão, Promoção, Presentes",
            ).strip()
            foto_enviada = st.file_uploader(
                "Foto do produto (opcional)",
                type=["png", "jpg", "jpeg", "webp"],
                help="Você pode deixar este campo vazio.",
            )
        with col2:
            custo = st.number_input("Preço de custo (R$)", min_value=0.0, value=0.0, step=1.0, format="%.2f")
            preco = st.number_input("Preço de venda (R$)", min_value=0.0, value=0.0, step=1.0, format="%.2f")
            quantidade = st.number_input("Quantidade inicial", min_value=0, value=0, step=1)

        enviar = st.form_submit_button("Salvar produto", use_container_width=True)
        if enviar:
            if not nome:
                st.error("Preencha o nome do produto.")
            else:
                categorias_novas = [c.strip() for c in novas_categorias.split(",") if c.strip()]
                categorias_finais = list(dict.fromkeys(categorias_selecionadas + categorias_novas))
                categoria_final = " | ".join(categorias_finais) if categorias_finais else "Sem categoria"
                foto = otimizar_foto(foto_enviada.getvalue()) if foto_enviada is not None else None
                try:
                    cadastrar_produto(nome, categoria_final, custo, preco, quantidade, foto)
                    st.success(f"Produto '{nome}' cadastrado!")
                    st.rerun()
                except psycopg2.IntegrityError:
                    st.error("Não foi possível cadastrar o produto. Tente novamente.")

    with st.expander("Editar valores de um produto"):
        st.caption("Altere o custo e/ou o preço de venda de um produto já cadastrado. As vendas anteriores permanecem com os valores registrados na época da venda.")
        pesquisa_edicao = st.text_input(
            "Pesquisar produto para editar",
            placeholder="Digite o nome ou a categoria do produto...",
            key="pesquisa_produto_edicao_precos",
        ).strip().lower()
        produtos_para_editar = [
            p for p in listar_produtos("", incluir_fotos=False)
            if pesquisa_edicao in str(p["nome"]).lower()
            or pesquisa_edicao in str(p["categoria"]).lower()
            or pesquisa_edicao in str(p["id"])
        ]
        if produtos_para_editar:
            opcoes_edicao = {
                f"{p['nome']} — {p['categoria']} (ID {p['id']})": p
                for p in produtos_para_editar
            }
            produto_edicao = st.selectbox(
                "Selecione o produto encontrado",
                list(opcoes_edicao.keys()),
                key="produto_edicao_precos",
            )
            selecionado = opcoes_edicao[produto_edicao]
            with st.form(f"form_editar_precos_{selecionado['id']}"):
                c1, c2 = st.columns(2)
                with c1:
                    custo_novo = st.number_input(
                        "Novo preço de custo (R$)", min_value=0.0,
                        value=float(selecionado["custo"] or 0), step=0.5,
                        format="%.2f", key=f"custo_edicao_{selecionado['id']}"
                    )
                with c2:
                    preco_novo = st.number_input(
                        "Novo preço de venda (R$)", min_value=0.0,
                        value=float(selecionado["preco"] or 0), step=0.5,
                        format="%.2f", key=f"preco_edicao_{selecionado['id']}"
                    )
                salvar_precos = st.form_submit_button(
                    "Salvar novos valores", use_container_width=True
                )
                if salvar_precos:
                    try:
                        atualizar_precos_produto(selecionado["id"], custo_novo, preco_novo)
                        st.success(f"Valores de '{selecionado['nome']}' atualizados com sucesso!")
                        st.rerun()
                    except (ValueError, psycopg2.Error) as erro:
                        st.error(f"Não foi possível atualizar os valores: {erro}")

        else:
            st.info("Nenhum produto corresponde à pesquisa. Tente outro nome ou categoria.")

    with st.expander("Editar categorias e imagem de um produto"):
        todos_para_editar = listar_produtos("", incluir_fotos=False)
        if todos_para_editar:
            opcoes_produtos_edicao = {f"{p['nome']} (ID {p['id']})": p for p in todos_para_editar}
            nome_produto_edicao = st.selectbox("Selecione o produto cuja imagem ou categorias deseja alterar", list(opcoes_produtos_edicao), key="produto_edicao_categoria_foto")
            produto_categoria_foto = opcoes_produtos_edicao[nome_produto_edicao]
            categorias_atual = separar_categorias(produto_categoria_foto.get("categoria"))
            if categorias_atual == ["Sem categoria"]:
                categorias_atual = []
            foto_atual = listar_fotos_produtos([produto_categoria_foto["id"]]).get(int(produto_categoria_foto["id"]))
            if foto_atual:
                st.caption("Imagem atual do produto")
                st.image(bytes(foto_atual) if isinstance(foto_atual, memoryview) else foto_atual, width=220)
            else:
                st.info("Este produto ainda não tem imagem cadastrada.")
            with st.form(f"form_categoria_foto_{produto_categoria_foto['id']}"):
                categorias_escolhidas_edicao = st.multiselect(
                    "Categorias do produto", options=sorted(set(listar_categorias() + categorias_atual), key=str.casefold),
                    default=categorias_atual, key=f"categorias_edit_{produto_categoria_foto['id']}"
                )
                categorias_novas_edicao = st.text_input("Adicionar novas categorias (separe por vírgula)", key=f"novas_categorias_edit_{produto_categoria_foto['id']}")
                nova_foto = st.file_uploader("Escolher nova imagem do produto", type=["png", "jpg", "jpeg", "webp"], key=f"foto_edit_{produto_categoria_foto['id']}", help="Selecione uma imagem para substituir a atual. Se deixar vazio, a imagem atual será mantida.")
                salvar_categoria_foto = st.form_submit_button("Salvar categorias e imagem", use_container_width=True)
                if salvar_categoria_foto:
                    categorias_extra = [c.strip() for c in categorias_novas_edicao.split(",") if c.strip()]
                    categorias_final_edicao = list(dict.fromkeys(categorias_escolhidas_edicao + categorias_extra))
                    try:
                        atualizar_categorias_produto(produto_categoria_foto["id"], categorias_final_edicao)
                        if nova_foto is not None:
                            atualizar_foto_produto(produto_categoria_foto["id"], otimizar_foto(nova_foto.getvalue()))
                        st.success("Categorias e imagem atualizadas com sucesso.")
                        st.rerun()
                    except (ValueError, psycopg2.Error) as erro:
                        st.error(f"Não foi possível salvar as alterações: {erro}")

    with st.expander("Excluir um produto"):
        st.warning("A exclusão de um produto pode ser permanente. Confira o nome antes de confirmar.")
        pesquisa_exclusao = st.text_input(
            "Pesquisar produto para excluir",
            placeholder="Digite o nome, a categoria ou o ID...",
            key="pesquisa_produto_exclusao",
        ).strip().lower()
        produtos_para_excluir = [
            p for p in listar_produtos("")
            if pesquisa_exclusao in str(p["nome"]).lower()
            or pesquisa_exclusao in str(p["categoria"]).lower()
            or pesquisa_exclusao in str(p["id"])
        ]
        if produtos_para_excluir:
            opcoes = {
                f"{p['nome']} — {p['categoria']} (ID {p['id']})": p["id"]
                for p in produtos_para_excluir
            }
            escolhido = st.selectbox(
                "Selecione o produto encontrado",
                list(opcoes.keys()),
                key="produto_selecionado_para_excluir",
            )
            confirmar = st.checkbox(
                "Confirmo que quero excluir este produto.",
                key="confirmar_exclusao_produto",
            )
            if st.button("Excluir produto", type="secondary"):
                if confirmar:
                    excluir_produto(opcoes[escolhido])
                    st.success("Produto excluído do catálogo.")
                    st.rerun()
                else:
                    st.warning("Marque a confirmação antes de excluir.")
        else:
            st.info("Nenhum produto corresponde à pesquisa. Tente outro nome, categoria ou ID.")

    st.divider()
    st.subheader("Produtos cadastrados")
    busca = st.text_input("Pesquisar por nome ou categoria", placeholder="Digite para pesquisar...")
    produtos = listar_produtos(busca, incluir_fotos=False)
    if produtos:
        total_produtos_lista = len(produtos)
        pagina_produtos = st.number_input(
            "Página de produtos", min_value=1,
            max_value=max(1, (total_produtos_lista + 29) // 30),
            value=1, step=1, key="pagina_produtos_cadastro"
        )
        inicio_produtos = (int(pagina_produtos) - 1) * 30
        produtos_exibidos = produtos[inicio_produtos:inicio_produtos + 30]
        fotos_produtos = listar_fotos_produtos([p["id"] for p in produtos_exibidos])
        for produto in produtos_exibidos:
            produto["foto"] = fotos_produtos.get(int(produto["id"]))
        st.caption(f"Exibindo {len(produtos_exibidos)} de {total_produtos_lista} produto(s)")
        for inicio in range(0, len(produtos_exibidos), 3):
            colunas = st.columns(3)
            for coluna, produto in zip(colunas, produtos_exibidos[inicio:inicio + 3]):
                with coluna:
                    with st.container(border=True):
                        if produto.get("foto"):
                            st.image(bytes(produto["foto"]) if isinstance(produto["foto"], memoryview) else produto["foto"], use_container_width=True)
                        else:
                            st.caption("Sem foto cadastrada")
                        st.markdown(f"**{produto['nome']}**")
                        st.caption(f"Categoria: {produto['categoria']}")
                        st.write(f"Preço de venda: {moeda(produto['preco'])}")
                        st.write(f"Quantidade: {produto['quantidade']}")

    else:
        st.info("Nenhum produto encontrado.")


# ------------------------------------------
# 7. ESTOQUE
# ------------------------------------------
elif pagina == "Estoque":
    st.subheader("Controle completo de estoque")
    st.caption("Consulte quais produtos estão disponíveis, ajuste quantidades e acompanhe o histórico de movimentações.")
    produtos = listar_produtos(incluir_fotos=False)

    if produtos:
        sem_estoque = sum(1 for p in produtos if int(p["quantidade"]) == 0)
        unidades = sum(int(p["quantidade"]) for p in produtos)
        a, b, c = st.columns(3)
        a.metric("Produtos cadastrados", len(produtos))
        b.metric("Unidades em estoque", unidades)
        c.metric("Fora de estoque", sem_estoque)

        if sem_estoque:
            st.warning(f"{sem_estoque} produto(s) estão fora de estoque.")

        st.divider()
        st.markdown("### Ajustar estoque")
        opcoes_estoque = {
            f"{p['nome']} — atual: {p['quantidade']} un.": p for p in produtos
        }
        with st.form("form_ajuste_estoque", clear_on_submit=True):
            produto_estoque_label = st.selectbox("Produto", list(opcoes_estoque.keys()))
            produto_estoque = opcoes_estoque[produto_estoque_label]
            operacao_estoque = st.radio(
                "Tipo de movimentação", ["Adicionar", "Retirar"], horizontal=True
            )
            quantidade_ajuste = st.number_input(
                "Quantidade", min_value=1, value=1, step=1
            )
            observacao_estoque = st.text_input(
                "Observação (opcional)", placeholder="Ex.: compra de fornecedor, perda, correção de contagem"
            )
            confirmar_ajuste = st.form_submit_button("Registrar movimentação", use_container_width=True)

        if confirmar_ajuste:
            try:
                ajustar_estoque(
                    produto_estoque["id"], int(quantidade_ajuste),
                    operacao_estoque, observacao_estoque
                )
                st.success(f"Movimentação registrada para {produto_estoque['nome']}.")
                st.rerun()
            except ValueError as erro:
                st.error(str(erro))

        st.divider()
        st.markdown("### Inventário atual")
        filtro_situacao = st.selectbox(
            "Filtrar por disponibilidade", ["Todos", "Disponíveis", "Fora de estoque"], key="filtro_situacao_estoque"
        )
        busca_estoque = st.text_input("Pesquisar produto ou categoria", placeholder="Digite um nome ou categoria...")

        tabela = []
        for p in produtos:
            qtd = int(p["quantidade"])
            situacao = "Fora de estoque" if qtd == 0 else "Disponível"
            situacao_filtro = "Fora de estoque" if qtd == 0 else "Disponíveis"
            if filtro_situacao != "Todos" and situacao_filtro != filtro_situacao:
                continue
            if busca_estoque and busca_estoque.casefold() not in p["nome"].casefold() and busca_estoque.casefold() not in p["categoria"].casefold():
                continue
            tabela.append({
                "Produto": p["nome"], "Categoria": p["categoria"],
                "Qtd. atual": qtd, "Situação": situacao,
                "Preço de custo": moeda(p["custo"]),
                "Preço de venda": moeda(p["preco"]),
            })
        if tabela:
            st.dataframe(tabela, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum produto corresponde aos filtros selecionados.")


    else:
        st.info("Cadastre produtos para consultar e controlar o estoque.")

    st.divider()
    with st.expander("Gerenciar estoque", expanded=False):
        st.subheader("Limpar quantidades do estoque")
        st.warning(
            "Esta ação define a quantidade de todos os produtos como zero. "
            "Os produtos continuam cadastrados e as vendas anteriores são preservadas."
        )
        confirmar_zeragem = st.checkbox(
            "Confirmo que quero zerar todas as quantidades.",
            key="confirmar_zeragem_estoque",
        )
        if st.button("Zerar todo o estoque", key="botao_zerar_estoque"):
            if confirmar_zeragem:
                quantidade_zerada = zerar_estoque()
                st.success(
                    f"Estoque zerado. {quantidade_zerada} produto(s) atualizado(s)."
                )
                st.rerun()
            else:
                st.warning("Marque a confirmação antes de continuar.")

        st.divider()
        st.subheader("Excluir todos os produtos")
        st.warning(
            "Esta ação remove permanentemente todos os produtos cadastrados e suas fotos. "
            "As vendas e os registros anteriores serão preservados."
        )
        confirmar_produtos = st.checkbox(
            "Confirmo que quero excluir TODOS os produtos cadastrados.",
            key="confirmar_exclusao_todos_produtos",
        )
        if st.button("Excluir todos os produtos", key="botao_excluir_todos_produtos"):
            if confirmar_produtos:
                quantidade_excluida = excluir_todos_produtos()
                st.success(f"{quantidade_excluida} produto(s) excluído(s).")
                st.rerun()
            else:
                st.warning("Marque a confirmação antes de continuar.")


# ------------------------------------------
# 8. CATÁLOGO VISUAL
# ------------------------------------------
elif pagina == "Catálogo Visual":
    st.subheader("Catálogo visual de produtos")

    todos_produtos_catalogo = listar_produtos(incluir_fotos=False)
    if todos_produtos_catalogo:
        total_catalogo = len(todos_produtos_catalogo)
        unidades_catalogo = sum(int(p["quantidade"]) for p in todos_produtos_catalogo)
        disponiveis_catalogo = sum(1 for p in todos_produtos_catalogo if int(p["quantidade"]) > 0)
        sem_estoque_catalogo = total_catalogo - disponiveis_catalogo

        met1, met2, met3 = st.columns(3)
        met1.metric("Tipos de produtos", total_catalogo)
        met2.metric("Unidades disponíveis", unidades_catalogo)
        met3.metric("Produtos sem estoque", sem_estoque_catalogo)

        filtro_col1, filtro_col2 = st.columns([2, 1])
        with filtro_col1:
            busca_catalogo = st.text_input(
                "Buscar produto", placeholder="Digite o nome ou a categoria...",
                key="busca_catalogo_visual",
            ).strip().casefold()
        with filtro_col2:
            categorias_catalogo = listar_categorias()
            categorias_selecionadas_catalogo = st.multiselect(
                "Categorias",
                options=categorias_catalogo,
                default=[],
                placeholder="Selecione uma ou mais categorias...",
                help="Se escolher várias categorias, serão exibidos produtos que pertençam a pelo menos uma delas.",
                key="categorias_catalogo_visual",
            )

        filtro_col3, filtro_col4 = st.columns([1, 2])
        with filtro_col3:
            disponibilidade_catalogo = st.selectbox(
                "Disponibilidade", ["Todos", "Disponíveis", "Sem estoque"],
                key="disponibilidade_catalogo_visual",
            )
        with filtro_col4:
            ordem_catalogo = st.selectbox(
                "Ordenar por",
                ["Nome (A–Z)", "Nome (Z–A)", "Menor preço", "Maior preço", "Maior quantidade"],
                key="ordem_catalogo_visual",
            )

        produtos_catalogo = [
            produto for produto in todos_produtos_catalogo
            if busca_catalogo in (produto["nome"] or "").casefold()
            or busca_catalogo in (produto["categoria"] or "").casefold()
        ]
        if categorias_selecionadas_catalogo:
            selecionadas = set(categorias_selecionadas_catalogo)
            produtos_catalogo = [
                p for p in produtos_catalogo
                if selecionadas.intersection(separar_categorias(p["categoria"]))
            ]
        if disponibilidade_catalogo == "Disponíveis":
            produtos_catalogo = [p for p in produtos_catalogo if int(p["quantidade"]) > 0]
        elif disponibilidade_catalogo == "Sem estoque":
            produtos_catalogo = [p for p in produtos_catalogo if int(p["quantidade"]) <= 0]

        if ordem_catalogo == "Nome (A–Z)":
            produtos_catalogo.sort(key=lambda p: (p["nome"] or "").casefold())
        elif ordem_catalogo == "Nome (Z–A)":
            produtos_catalogo.sort(key=lambda p: (p["nome"] or "").casefold(), reverse=True)
        elif ordem_catalogo == "Menor preço":
            produtos_catalogo.sort(key=lambda p: float(p["preco"] or 0))
        elif ordem_catalogo == "Maior preço":
            produtos_catalogo.sort(key=lambda p: float(p["preco"] or 0), reverse=True)
        elif ordem_catalogo == "Maior quantidade":
            produtos_catalogo.sort(key=lambda p: int(p["quantidade"] or 0), reverse=True)

        # Quando a pesquisa/filtros mudam, volta para a primeira página para evitar
        # uma página antiga inválida ou uma lista aparentemente vazia.
        assinatura_filtros_catalogo = (
            busca_catalogo,
            tuple(sorted(categorias_selecionadas_catalogo)),
            disponibilidade_catalogo,
            ordem_catalogo,
        )
        assinatura_anterior = st.session_state.get("assinatura_filtros_catalogo")
        if assinatura_anterior != assinatura_filtros_catalogo:
            st.session_state["pagina_catalogo_visual"] = 1
            st.session_state["assinatura_filtros_catalogo"] = assinatura_filtros_catalogo

        st.divider()
        if produtos_catalogo:
            total_filtrados_catalogo = len(produtos_catalogo)
            controle_col1, controle_col2 = st.columns([1, 2])
            with controle_col1:
                itens_por_pagina = st.selectbox(
                    "Produtos por página", [6, 12, 18, 24, 30], index=1,
                    key="itens_por_pagina_catalogo",
                    help="Comece com 12 produtos para reduzir o trabalho de renderização, especialmente no celular.",
                )
            total_paginas_catalogo = max(1, (total_filtrados_catalogo + itens_por_pagina - 1) // itens_por_pagina)
            pagina_salva = st.session_state.get("pagina_catalogo_visual", 1)
            if not isinstance(pagina_salva, int) or pagina_salva < 1 or pagina_salva > total_paginas_catalogo:
                st.session_state["pagina_catalogo_visual"] = 1
            with controle_col2:
                pagina_catalogo = st.selectbox(
                    "Página", list(range(1, total_paginas_catalogo + 1)),
                    format_func=lambda pagina: f"Página {pagina} de {total_paginas_catalogo}",
                    key="pagina_catalogo_visual",
                )
            inicio_pagina_catalogo = (pagina_catalogo - 1) * itens_por_pagina
            produtos_exibidos_catalogo = produtos_catalogo[inicio_pagina_catalogo:inicio_pagina_catalogo + itens_por_pagina]
            fotos_catalogo = listar_fotos_produtos([p["id"] for p in produtos_exibidos_catalogo])
            for produto in produtos_exibidos_catalogo:
                produto["foto"] = fotos_catalogo.get(int(produto["id"]))
            st.caption(f"Exibindo {len(produtos_exibidos_catalogo)} de {total_filtrados_catalogo} produto(s) · Página {pagina_catalogo} de {total_paginas_catalogo}")
            # Agrupa até 6 produtos: CSS mostra 3 por linha no computador e 2 no celular.
            for inicio in range(0, len(produtos_exibidos_catalogo), 6):
                lote_produtos = produtos_exibidos_catalogo[inicio:inicio + 6]
                with st.container(key=f"catalogo_grade_responsiva_{inicio}"):
                    colunas_catalogo = st.columns(len(lote_produtos))
                    for coluna, produto in zip(colunas_catalogo, lote_produtos):
                        with coluna:
                            with st.container(border=True):
                                if produto.get("foto"):
                                    st.image(bytes(produto["foto"]) if isinstance(produto["foto"], memoryview) else produto["foto"], use_container_width=True)
                                else:
                                    st.markdown("<div style='text-align:center; padding:42px 8px; background:#f1f3f5; border-radius:8px; font-size:42px;'>📦</div>", unsafe_allow_html=True)
                                    st.caption("Foto não cadastrada")
                                st.markdown(f"**{produto['nome']}**")
                                st.caption(f"Categoria: {produto['categoria'] or 'Sem categoria'}")
                                qtd = int(produto["quantidade"])
                                if qtd > 0:
                                    st.markdown(f"<span style='color:#16794b;font-weight:600;'>● Em estoque · {qtd} unidade(s)</span>", unsafe_allow_html=True)
                                else:
                                    st.markdown("<span style='color:#b42318;font-weight:600;'>● Fora de estoque</span>", unsafe_allow_html=True)
                                st.markdown(f"<div style='font-size:1.15rem;font-weight:700;margin-top:0.35rem;'>{moeda(produto['preco'])}</div>", unsafe_allow_html=True)

        else:
            st.info("Nenhum produto corresponde aos filtros selecionados. Experimente alterar a pesquisa ou os filtros.")
    else:
        st.info("Ainda não há produtos cadastrados. Cadastre um produto para ele aparecer automaticamente neste catálogo.")


# ------------------------------------------
# 9. CONTROLE DE DÍVIDAS
# ------------------------------------------
elif pagina == "Controle de Dívidas":
    st.subheader("Controle de dívidas")

    vendas = listar_vendas()
    dividas = [v for v in vendas if v["status_pagamento"] in ("Devendo", "Parcial")]
    total_dividas = sum(max(0, float(v["total"] or 0) - float(v.get("valor_pago") or 0)) for v in dividas)
    clientes_devendo = len({(v["cliente"] or "").strip().casefold() for v in dividas})

    c1, c2, c3 = st.columns(3)
    c1.metric("Valor total em aberto", moeda(total_dividas))
    c2.metric("Vendas pendentes", len(dividas))
    c3.metric("Pessoas com dívidas", clientes_devendo)

    st.divider()
    busca_divida = st.text_input(
        "Pesquisar dívida",
        placeholder="Pesquise pelo nome, telefone ou produto...",
        key="busca_divida",
    ).strip().casefold()
    filtro_divida = st.selectbox("Mostrar", ["Todas as pendências", "Uma pessoa específica"])

    dividas_filtradas = []
    for venda in dividas:
        texto = " ".join([
            str(venda.get("cliente") or ""),
            str(venda.get("telefone_cliente") or ""),
            str(venda.get("produto_nome") or ""),
        ]).casefold()
        if busca_divida and busca_divida not in texto:
            continue
        dividas_filtradas.append(venda)

    if filtro_divida == "Uma pessoa específica" and dividas_filtradas:
        pessoas = sorted({v["cliente"] for v in dividas_filtradas}, key=str.casefold)
        pessoa_escolhida = st.selectbox("Selecione a pessoa", pessoas)
        dividas_filtradas = [v for v in dividas_filtradas if v["cliente"] == pessoa_escolhida]

    if not dividas:
        st.success("Não há dívidas em aberto. Todas as vendas estão marcadas como pagas!")
    elif not dividas_filtradas:
        st.info("Nenhuma dívida corresponde à pesquisa.")
    else:
        st.caption("Para registrar uma dívida, faça uma venda na aba Vendas e escolha a forma de pagamento ‘A pagar’.")
        for divida in dividas_filtradas:
            with st.container(border=True):
                esquerda, direita = st.columns([3, 1])
                with esquerda:
                    st.markdown(f"**Venda #{divida['id']} — {divida['cliente']}**")
                    st.write(f"**Produto:** {divida['produto_nome']}")
                    total_venda = float(divida["total"] or 0)
                    valor_pago = float(divida.get("valor_pago") or 0)
                    saldo_devedor = max(0, round(total_venda - valor_pago, 2))
                    st.write(f"**Quantidade:** {divida['quantidade']} · **Total da venda:** {moeda(total_venda)}")
                    st.write(f"**Já pago:** {moeda(valor_pago)} · **Falta pagar:** {moeda(saldo_devedor)}")
                    st.caption(f"Data da venda: {divida['criado_em']} · Forma de pagamento: {divida['forma_pagamento']}")
                    if divida.get("data_prevista_pagamento"):
                        st.write(f"**Data prevista para pagar:** {divida['data_prevista_pagamento']}")
                    if divida.get("telefone_cliente"):
                        st.write(f"**Telefone:** {divida['telefone_cliente']}")
                    pagamentos_venda = listar_pagamentos_divida(divida["id"])
                    with st.expander("Histórico de pagamentos desta dívida"):
                        if pagamentos_venda:
                            st.dataframe([{
                                "Data do pagamento": pagamento["criado_em"],
                                "Valor recebido": moeda(pagamento["valor"]),
                            } for pagamento in pagamentos_venda], use_container_width=True, hide_index=True)
                        else:
                            st.info("Ainda não há pagamentos parciais registrados para esta venda.")
                with direita:
                    st.warning("Pagamento parcial" if valor_pago > 0 else "Em aberto")
                    with st.form(key=f"form_pagamento_divida_{divida['id']}"):
                        valor_recebido = st.number_input(
                            "Valor recebido agora (R$)", min_value=0.01,
                            max_value=float(max(0.01, saldo_devedor)), value=float(round(max(0.01, saldo_devedor), 2)),
                            step=1.0, format="%.2f", key=f"valor_recebido_{divida['id']}"
                        )
                        registrar = st.form_submit_button("Registrar pagamento", use_container_width=True)
                    if registrar:
                        try:
                            registrar_pagamento_divida(divida["id"], valor_recebido)
                            st.success("Pagamento registrado!")
                            st.rerun()
                        except ValueError as erro:
                            st.error(str(erro))

    st.divider()
    st.subheader("Dívidas quitadas")
    st.info("Quando uma dívida é totalmente paga, ela desaparece desta tela. O registro interno é mantido apenas para os indicadores financeiros.")



# ------------------------------------------
# 10. VENDAS
# ------------------------------------------
elif pagina == "Vendas":
    st.subheader("Registrar uma venda")
    produtos_disponiveis = [p for p in listar_produtos() if int(p["quantidade"]) > 0]

    if not produtos_disponiveis:
        st.warning("Não há produtos com estoque disponível. Cadastre produtos ou reponha o estoque antes de registrar uma venda.")
    else:
        busca_produto_venda = st.text_input(
            "Pesquisar produto pelo nome ou categoria",
            placeholder="Digite nome ou categoria para encontrar mais rápido...",
            key="busca_produto_venda",
        ).strip().casefold()
        produtos_filtrados = [p for p in produtos_disponiveis if
            busca_produto_venda in p["nome"].casefold() or busca_produto_venda in (p.get("categoria") or "").casefold()]
        opcoes_produtos = {f"{p['nome']} — {moeda(p['preco'])} (estoque: {p['quantidade']}) · ID {p['id']}": p for p in produtos_filtrados}
        if not opcoes_produtos:
            st.warning("Nenhum produto com estoque disponível corresponde à pesquisa.")
        else:
            selecionados_labels = st.multiselect(
                "Produtos desta venda", options=list(opcoes_produtos.keys()),
                help="Selecione um ou vários produtos para a mesma compra.", key="produtos_venda_multiplos"
            )
            itens_venda = []
            total_previa = 0.0
            for idx, label in enumerate(selecionados_labels):
                produto_selecionado = opcoes_produtos[label]
                col_prod, col_qtd = st.columns([3, 1])
                with col_prod:
                    st.write(f"**{produto_selecionado['nome']}** — {moeda(produto_selecionado['preco'])} cada")
                with col_qtd:
                    qtd = st.number_input(
                        "Quantidade", min_value=1, max_value=int(produto_selecionado["quantidade"]),
                        value=1, step=1, key=f"qtd_venda_produto_{produto_selecionado['id']}"
                    )
                total_previa += float(produto_selecionado["preco"]) * int(qtd)
                itens_venda.append({"produto_id": produto_selecionado["id"], "quantidade": int(qtd)})

            if itens_venda:
                st.metric("Total da venda", moeda(total_previa))
            with st.form("form_venda_varios", clear_on_submit=False):
                cliente = st.text_input("Nome de quem comprou *", placeholder="Nome do cliente").strip()
                telefone_cliente = st.text_input("Telefone de quem comprou (opcional)", placeholder="Ex.: (19) 99999-9999").strip()
                forma_pagamento = st.selectbox("Forma de pagamento", ["Pix", "Dinheiro", "A pagar"])
                data_prevista = st.date_input(
                    "Data prevista para pagamento (se for 'A pagar')",
                    value=date.today() + timedelta(days=7),
                    help="Só será salva para vendas marcadas como 'A pagar'."
                )
                registrar = st.form_submit_button("Registrar venda e baixar estoque", use_container_width=True)
                if registrar:
                    if not cliente:
                        st.error("Informe o nome de quem comprou.")
                    elif not itens_venda:
                        st.error("Selecione pelo menos um produto.")
                    else:
                        try:
                            total_registrado, grupo_id = registrar_venda_varios(
                                itens_venda, cliente, forma_pagamento, telefone_cliente,
                                data_prevista.isoformat() if forma_pagamento == "A pagar" else None
                            )
                            if forma_pagamento == "A pagar":
                                st.success(f"Venda anotada para controle da dívida! Total: {moeda(total_registrado)}. O estoque de todos os itens foi atualizado.")
                            else:
                                st.success(f"Venda paga concluída! Total: {moeda(total_registrado)}. O estoque foi atualizado e ela não aparecerá no histórico de vendas.")
                            st.rerun()
                        except (ValueError, psycopg2.Error) as erro:
                            st.error(f"Não foi possível registrar a venda: {erro}")

    st.divider()
    st.subheader("Vendas a pagar")
    vendas = listar_vendas()
    if not vendas:
        st.info("Não há vendas pendentes. Vendas pagas não ficam registradas no histórico.")
    else:
        total_pendente = sum(max(0, float(v["total"] or 0) - float(v.get("valor_pago") or 0)) for v in vendas if v["status_pagamento"] in ("Devendo", "Parcial"))
        total_recebido = sum(float(v.get("valor_pago") or 0) for v in vendas)
        a, b = st.columns(2)
        a.metric("Total a receber", moeda(total_pendente))
        b.metric("Total marcado como pago", moeda(total_recebido))

        for venda in vendas:
            with st.container(border=True):
                esquerda, direita = st.columns([3, 1])
                with esquerda:
                    st.markdown(f"**Venda #{venda['id']} — {venda['produto_nome']}**")
                    st.write(f"**Cliente:** {venda['cliente']}")
                    if venda.get("telefone_cliente"):
                        st.write(f"**Telefone:** {venda['telefone_cliente']}")
                    valor_pago = float(venda.get("valor_pago") or 0)
                    saldo = max(0, float(venda["total"] or 0) - valor_pago)
                    st.write(
                        f"**Quantidade:** {venda['quantidade']} · "
                        f"**Total:** {moeda(venda['total'])}"
                    )
                    if venda["forma_pagamento"] == "A pagar":
                        st.write(f"**Recebido:** {moeda(valor_pago)} · **Saldo:** {moeda(saldo)}")
                        if venda.get("data_prevista_pagamento"):
                            st.write(f"**Data prevista para pagar:** {venda['data_prevista_pagamento']}")
                        pagamentos_venda = listar_pagamentos_divida(venda["id"])
                        if pagamentos_venda:
                            with st.expander("Ver histórico de pagamentos"):
                                st.dataframe([{
                                    "Data": pagamento["criado_em"],
                                    "Valor": moeda(pagamento["valor"]),
                                } for pagamento in pagamentos_venda], use_container_width=True, hide_index=True)
                    grupo = venda.get("venda_grupo_id")
                    identificador_grupo = f" · Código da venda: {grupo[:8]}" if grupo else ""
                    st.caption(
                        f"Pagamento: {venda['forma_pagamento']} · Data: {venda['criado_em']}{identificador_grupo}"
                    )
                with direita:
                    if venda["status_pagamento"] == "Parcial":
                        st.info("Pagamento parcial")
                    else:
                        st.warning("Devendo")

    # Gerenciamento de exclusão: separado do registro para evitar cliques acidentais.
    st.divider()
    with st.expander("🗑️ Gerenciar exclusão de vendas", expanded=False):
        st.warning(
            "A exclusão manual é permanente. Os pagamentos vinculados também serão removidos. "
            "Quando o produto ainda existir no cadastro, a quantidade vendida será devolvida ao estoque."
        )
        vendas_para_excluir = listar_vendas()
        if not vendas_para_excluir:
            st.info("Não há vendas para excluir.")
        else:
            opcoes_exclusao = {
                f"Venda #{v['id']} — {v['produto_nome']} — {v['cliente']} — {moeda(v['total'])} ({v['criado_em']})": v
                for v in vendas_para_excluir
            }
            venda_label = st.selectbox(
                "Selecione uma venda para excluir",
                list(opcoes_exclusao.keys()),
                key="selecionar_venda_para_excluir",
            )
            venda_selecionada = opcoes_exclusao[venda_label]
            confirmar_venda = st.checkbox(
                f"Confirmo a exclusão da venda #{venda_selecionada['id']}",
                key="confirmar_exclusao_venda_individual",
            )
            if st.button("Excluir venda selecionada", key="botao_excluir_venda_individual", type="secondary"):
                if not confirmar_venda:
                    st.error("Marque a confirmação antes de excluir.")
                else:
                    try:
                        excluir_venda(venda_selecionada["id"])
                        st.success(f"Venda #{venda_selecionada['id']} excluída. O relatório foi atualizado.")
                        st.rerun()
                    except (ValueError, psycopg2.Error) as erro:
                        st.error(f"Não foi possível excluir a venda: {erro}")

            st.divider()
            st.markdown("**Excluir todas as vendas**")
            st.caption("Esta ação remove todos os registros de venda e os pagamentos vinculados. Os produtos cadastrados não serão apagados.")
            confirmar_todas = st.checkbox(
                "Confirmo que quero excluir TODAS as vendas permanentemente.",
                key="confirmar_exclusao_todas_vendas",
            )
            if st.button("Excluir todas as vendas", key="botao_excluir_todas_vendas", type="secondary"):
                if not confirmar_todas:
                    st.error("Marque a confirmação para habilitar a exclusão de todas as vendas.")
                else:
                    try:
                        quantidade_excluida = excluir_todas_vendas()
                        st.success(f"{quantidade_excluida} venda(s) excluída(s). O relatório foi atualizado.")
                        st.rerun()
                    except psycopg2.Error as erro:
                        st.error(f"Não foi possível excluir as vendas: {erro}")


st.divider()
st.caption("Mabel Store • Gestão interna")
