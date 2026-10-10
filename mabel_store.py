import uuid
import psycopg2
from psycopg2.extras import DictCursor
import io
import zipfile
from pathlib import Path
from datetime import date, timedelta

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

    def __enter__(self):
        return self

    def __exit__(self, tipo, valor, traceback):
        try:
            if tipo is None:
                self.raw.commit()
            else:
                self.raw.rollback()
        finally:
            self.raw.close()
        return False

    def execute(self, sql, parametros=None):
        sql = sql.replace("?", "%s")
        sql = sql.replace("BEGIN IMMEDIATE", "BEGIN")
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
    raw = psycopg2.connect(url, sslmode="require", connect_timeout=15)
    return ConexaoPostgres(raw)


# ------------------------------------------
# 2. BANCO DE DADOS
# ------------------------------------------
def criar_tabelas():
    """Confere a conexão e se as quatro tabelas já criadas no Supabase existem."""
    with conectar() as conexao:
        conexao.execute("""
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('produtos', 'movimentacoes_estoque', 'vendas', 'pagamentos_dividas')
        """)
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


def listar_produtos(busca=""):
    with conectar() as conexao:
        if busca:
            resultado = conexao.execute("""
                SELECT * FROM produtos
                WHERE nome ILIKE ? OR categoria ILIKE ?
                ORDER BY nome
            """, (f"%{busca}%", f"%{busca}%"))
        else:
            resultado = conexao.execute("SELECT * FROM produtos ORDER BY nome")
        return [dict(linha) for linha in resultado.fetchall()]


def listar_categorias():
    with conectar() as conexao:
        resultado = conexao.execute("""
            SELECT categoria
            FROM (
                SELECT DISTINCT categoria
                FROM produtos
                WHERE categoria IS NOT NULL
                  AND TRIM(categoria) != ''
            ) AS categorias
            ORDER BY LOWER(categoria)
        """)
        return [linha[0] for linha in resultado.fetchall()]


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


def listar_vendas():
    with conectar() as conexao:
        resultado = conexao.execute("SELECT * FROM vendas ORDER BY id DESC")
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


def listar_pagamentos_divida(venda_id):
    """Retorna os pagamentos individuais registrados para uma venda."""
    with conectar() as conexao:
        resultado = conexao.execute(
            "SELECT valor, criado_em FROM pagamentos_dividas WHERE venda_id = ? ORDER BY id DESC",
            (int(venda_id),),
        )
        return [dict(linha) for linha in resultado.fetchall()]


def marcar_venda_paga(venda_id):
    """Registra o saldo restante como pagamento, preservando o histórico."""
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
    ["Dashboard", "Cadastrar Produtos", "Estoque", "Catálogo Visual", "Controle de Dívidas", "Relatórios e Exportação", "Vendas"],
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

    hoje = date.today()
    inicio_semana = hoje - timedelta(days=6)

    with conectar() as conexao:
        vendas = conexao.execute("""
            SELECT * FROM vendas ORDER BY id DESC
        """).fetchall()

        resumo_hoje = conexao.execute("""
            SELECT
                COUNT(*) AS quantidade_vendas,
                COALESCE(SUM(COALESCE(valor_pago, CASE WHEN status_pagamento = 'Pago' THEN total ELSE 0 END)), 0) AS recebido
            FROM vendas
            WHERE (criado_em AT TIME ZONE 'America/Sao_Paulo')::date = CURRENT_DATE
        """).fetchone()

        resumo_semana = conexao.execute("""
            SELECT (criado_em AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
                   COALESCE(SUM(valor_pago), 0) AS total
            FROM vendas
            WHERE (criado_em AT TIME ZONE 'America/Sao_Paulo')::date >= ?
              AND (criado_em AT TIME ZONE 'America/Sao_Paulo')::date <= ?
            GROUP BY (criado_em AT TIME ZONE 'America/Sao_Paulo')::date
        """, (inicio_semana.isoformat(), hoje.isoformat())).fetchall()

    vendas = [dict(v) for v in vendas]

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

    if data_inicio_dashboard is not None and data_inicio_dashboard > data_fim_dashboard:
        st.error("A data inicial não pode ser posterior à data final. Ajuste o período para ver os indicadores.")
        vendas_periodo = []
    elif data_inicio_dashboard is None and periodo_dashboard == "Todo o período":
        vendas_periodo = vendas
    else:
        vendas_periodo = []
        for venda in vendas:
            try:
                data_venda = date.fromisoformat(str(venda.get("criado_em", ""))[:10])
            except (TypeError, ValueError):
                continue
            if data_inicio_dashboard <= data_venda <= data_fim_dashboard:
                vendas_periodo.append(venda)

    vendas_pagas = [v for v in vendas_periodo if v["status_pagamento"] == "Pago"]
    vendas_pendentes = [v for v in vendas_periodo if v["status_pagamento"] in ("Devendo", "Parcial")]

    faturamento_recebido = sum(float(v.get("valor_pago") or 0) for v in vendas_periodo)
    valores_a_receber = sum(max(0, float(v["total"] or 0) - float(v.get("valor_pago") or 0)) for v in vendas_pendentes)
    quantidade_vendas = len(vendas_periodo)

    # O custo é gravado nas novas vendas. Vendas antigas podem ter custo estimado.
    lucro_estimado = sum(
        (float(v.get("valor_unitario") or 0) - float(v.get("custo_unitario") or 0))
        * int(v.get("quantidade") or 0)
        for v in vendas_pagas
    )

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
    st.subheader("Resumo de hoje")
    h1, h2, h3 = st.columns(3)
    h1.metric("Vendas registradas hoje", int(resumo_hoje["quantidade_vendas"] or 0))
    h2.metric("Recebido hoje", moeda(resumo_hoje["recebido"]))
    h3.metric("Produtos sem estoque", sum(1 for produto in listar_produtos() if int(produto["quantidade"]) == 0))

    st.divider()
    st.subheader("Vendas recebidas — últimos 7 dias")
    valores_por_dia = {
        linha["dia"]: float(linha["total"] or 0)
        for linha in resumo_semana
    }
    dias = [inicio_semana + timedelta(days=i) for i in range(7)]
    dados_grafico = pd.DataFrame({
        "Dia": [d.strftime("%d/%m") for d in dias],
        "Valor recebido": [valores_por_dia.get(d.isoformat(), 0) for d in dias],
    })
    st.bar_chart(dados_grafico, x="Dia", y="Valor recebido", use_container_width=True)


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
            categoria_selecionada = st.selectbox(
                "Categoria salva",
                options=opcoes_categoria,
                help="Escolha uma categoria que você já usou antes.",
            )
            nova_categoria = st.text_input(
                "Ou crie uma nova categoria (opcional)",
                placeholder="Digite apenas se for uma categoria nova",
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
                categoria_final = nova_categoria or categoria_selecionada or "Sem categoria"
                foto = foto_enviada.getvalue() if foto_enviada is not None else None
                try:
                    cadastrar_produto(nome, categoria_final, custo, preco, quantidade, foto)
                    st.success(f"Produto '{nome}' cadastrado!")
                    st.rerun()
                except psycopg2.IntegrityError:
                    st.error("Não foi possível cadastrar o produto. Tente novamente.")

    st.divider()
    st.subheader("Produtos cadastrados")
    busca = st.text_input("Pesquisar por nome ou categoria", placeholder="Digite para pesquisar...")
    produtos = listar_produtos(busca)
    if produtos:
        for inicio in range(0, len(produtos), 3):
            colunas = st.columns(3)
            for coluna, produto in zip(colunas, produtos[inicio:inicio + 3]):
                with coluna:
                    with st.container(border=True):
                        if produto.get("foto"):
                            st.image(bytes(produto["foto"]), use_container_width=True)
                        else:
                            st.caption("Sem foto cadastrada")
                        st.markdown(f"**{produto['nome']}**")
                        st.caption(f"Categoria: {produto['categoria']}")
                        st.write(f"Preço de venda: {moeda(produto['preco'])}")
                        st.write(f"Quantidade: {produto['quantidade']}")

        st.divider()
        st.subheader("Editar valores de um produto")
        st.caption("Altere o custo e/ou o preço de venda de um produto já cadastrado. As vendas anteriores permanecem com os valores registrados na época da venda.")
        pesquisa_edicao = st.text_input(
            "Pesquisar produto para editar",
            placeholder="Digite o nome ou a categoria do produto...",
            key="pesquisa_produto_edicao_precos",
        ).strip().lower()
        produtos_para_editar = [
            p for p in produtos
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
    else:
        st.info("Nenhum produto encontrado.")


# ------------------------------------------
# 7. ESTOQUE
# ------------------------------------------
elif pagina == "Estoque":
    st.subheader("Controle completo de estoque")
    st.caption("Consulte quais produtos estão disponíveis, ajuste quantidades e acompanhe o histórico de movimentações.")
    produtos = listar_produtos()

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

        st.divider()
        st.markdown("### Histórico de movimentações")
        movimentos = listar_movimentacoes()
        if movimentos:
            st.caption("Exibe até as 300 movimentações mais recentes, incluindo estoque inicial, entradas, retiradas e vendas.")
            st.dataframe([{
                "Data": m["criado_em"], "Produto": m["produto_nome"],
                "Movimentação": m["tipo"], "Quantidade": m["quantidade"],
                "Saldo anterior": m["saldo_anterior"], "Saldo novo": m["saldo_novo"],
                "Observação": m["observacao"] or "—",
            } for m in movimentos], use_container_width=True, hide_index=True)
        else:
            st.info("Ainda não há movimentações registradas. Novos ajustes e vendas aparecerão aqui.")
    else:
        st.info("Cadastre produtos para consultar e controlar o estoque.")

    st.divider()
    with st.expander("Gerenciar estoque e histórico", expanded=False):
        st.subheader("Excluir histórico de movimentações")
        movimentos_exclusao = listar_todas_movimentacoes()

        if movimentos_exclusao:
            opcoes_movimentos = {
                f"Movimentação #{m['id']} — {m['produto_nome']} — {m['tipo']} — {m['criado_em']}": m
                for m in movimentos_exclusao
            }
            movimento_label = st.selectbox(
                "Selecione uma movimentação para excluir",
                list(opcoes_movimentos.keys()),
                key="movimento_para_excluir",
            )
            movimento_selecionado = opcoes_movimentos[movimento_label]
            confirmar_movimento = st.checkbox(
                "Confirmo a exclusão desta movimentação.",
                key="confirmar_exclusao_movimentacao",
            )
            if st.button(
                "Excluir movimentação selecionada",
                key="excluir_movimentacao_individual",
            ):
                if confirmar_movimento:
                    excluir_movimentacao(movimento_selecionado["id"])
                    st.success("Movimentação excluída.")
                    st.rerun()
                else:
                    st.warning("Marque a confirmação antes de excluir.")

            confirmar_historico = st.checkbox(
                "Confirmo que quero apagar TODO o histórico de movimentações.",
                key="confirmar_exclusao_todas_movimentacoes",
            )
            if st.button(
                "Excluir todo o histórico de movimentações",
                key="excluir_historico_completo",
            ):
                if confirmar_historico:
                    excluir_todas_movimentacoes()
                    st.success("Histórico de movimentações excluído.")
                    st.rerun()
                else:
                    st.warning("Marque a confirmação antes de excluir.")
        else:
            st.info("Não há movimentações para excluir.")

        st.divider()
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
            "As vendas e as movimentações já registradas serão preservadas."
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

    todos_produtos_catalogo = listar_produtos()
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
            categorias_catalogo = ["Todas as categorias"] + listar_categorias()
            categoria_catalogo = st.selectbox(
                "Categoria", categorias_catalogo, key="categoria_catalogo_visual"
            )

        disponibilidade_catalogo = st.radio(
            "Disponibilidade", ["Todos", "Disponíveis", "Sem estoque"],
            horizontal=True, key="disponibilidade_catalogo_visual",
        )

        produtos_catalogo = [
            produto for produto in todos_produtos_catalogo
            if busca_catalogo in produto["nome"].casefold()
            or busca_catalogo in (produto["categoria"] or "").casefold()
        ]
        if categoria_catalogo != "Todas as categorias":
            produtos_catalogo = [p for p in produtos_catalogo if p["categoria"] == categoria_catalogo]
        if disponibilidade_catalogo == "Disponíveis":
            produtos_catalogo = [p for p in produtos_catalogo if int(p["quantidade"]) > 0]
        elif disponibilidade_catalogo == "Sem estoque":
            produtos_catalogo = [p for p in produtos_catalogo if int(p["quantidade"]) <= 0]

        st.divider()
        if produtos_catalogo:
            st.caption(f"Exibindo {len(produtos_catalogo)} produto(s)")
            for inicio in range(0, len(produtos_catalogo), 3):
                colunas_catalogo = st.columns(3)
                for coluna, produto in zip(colunas_catalogo, produtos_catalogo[inicio:inicio + 3]):
                    with coluna:
                        with st.container(border=True):
                            if produto.get("foto"):
                                st.image(bytes(produto["foto"]), use_container_width=True)
                            else:
                                st.markdown("<div style='text-align:center; padding:42px 8px; background:#f1f3f5; border-radius:8px; font-size:42px;'>📦</div>", unsafe_allow_html=True)
                                st.caption("Foto não cadastrada")
                            st.markdown(f"**{produto['nome']}**")
                            st.caption(f"Categoria: {produto['categoria']}")
                            qtd = int(produto["quantidade"])
                            if qtd > 0:
                                st.success(f"Quantidade disponível: {qtd}")
                            else:
                                st.warning("Quantidade disponível: 0 — sem estoque")
                            st.write(f"Preço: {moeda(produto['preco'])}")

        else:
            st.info("Nenhum produto corresponde aos filtros selecionados.")
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
    st.subheader("Histórico de dívidas quitadas")
    quitadas = [v for v in vendas if v["status_pagamento"] == "Pago" and v["forma_pagamento"] == "A pagar"]
    if quitadas:
        st.dataframe([{
            "Venda": f"#{v['id']}",
            "Pessoa": v["cliente"],
            "Produto": v["produto_nome"],
            "Total da venda": moeda(v["total"]),
            "Valor recebido": moeda(v.get("valor_pago") or v["total"]),
            "Data prevista para pagar": v.get("data_prevista_pagamento") or "—",
            "Data da venda": v["criado_em"],
        } for v in quitadas], use_container_width=True, hide_index=True)
    else:
        st.info("As dívidas quitadas aparecerão aqui depois que o saldo chegar a zero.")


# ------------------------------------------
# 10. RELATÓRIOS E EXPORTAÇÃO
# ------------------------------------------
elif pagina == "Relatórios e Exportação":
    st.subheader("Relatórios e exportação")

    hoje_relatorio = date.today()
    col_data1, col_data2 = st.columns(2)
    with col_data1:
        data_inicio = st.date_input("Data inicial", value=hoje_relatorio.replace(day=1), key="rel_data_inicio")
    with col_data2:
        data_fim = st.date_input("Data final", value=hoje_relatorio, key="rel_data_fim")

    if data_inicio > data_fim:
        st.error("A data inicial não pode ser posterior à data final.")
    else:
        with conectar() as conexao:
            produtos_rel = pd.read_sql_query("""
                SELECT id AS "ID", codigo AS "Código", nome AS "Produto", categoria AS "Categoria",
                       custo AS "Custo unitário (R$)", preco AS "Preço de venda (R$)",
                       quantidade AS "Quantidade em estoque",
                       ROUND((custo * quantidade)::numeric, 2) AS "Valor de custo em estoque (R$)",
                       ROUND((preco * quantidade)::numeric, 2) AS "Valor potencial de venda (R$)", criado_em AS "Cadastrado em"
                FROM produtos ORDER BY LOWER(nome)
            """, conexao.raw)
            vendas_rel = pd.read_sql_query("""
                SELECT id AS "Venda", (criado_em AT TIME ZONE 'America/Sao_Paulo')::date AS "Data",
                       produto_nome AS "Produto", cliente AS "Pessoa", telefone_cliente AS "Telefone",
                       quantidade AS "Quantidade", valor_unitario AS "Preço unitário (R$)",
                       total AS "Total (R$)", COALESCE(valor_pago, 0) AS "Valor recebido (R$)",
                       ROUND((total - COALESCE(valor_pago, 0))::numeric, 2) AS "Saldo devedor (R$)",
                       forma_pagamento AS "Forma de pagamento",
                       status_pagamento AS "Status", custo_unitario AS "Custo unitário (R$)", 
                       ROUND(((COALESCE(valor_unitario, 0) - COALESCE(custo_unitario, 0)) * quantidade)::numeric, 2) AS "Lucro bruto estimado (R$)"
                FROM vendas
                WHERE (criado_em AT TIME ZONE 'America/Sao_Paulo')::date >= %s AND (criado_em AT TIME ZONE 'America/Sao_Paulo')::date <= %s
                ORDER BY criado_em DESC
            """, conexao.raw, params=(data_inicio.isoformat(), data_fim.isoformat()))
            movimentacoes_rel = pd.read_sql_query("""
                SELECT id AS "Movimentação", (criado_em AT TIME ZONE 'America/Sao_Paulo')::date AS "Data", produto_nome AS "Produto",
                       tipo AS "Tipo", quantidade AS "Quantidade movimentada", saldo_anterior AS "Saldo anterior",
                       saldo_novo AS "Saldo novo", observacao AS "Observação"
                FROM movimentacoes_estoque
                WHERE (criado_em AT TIME ZONE 'America/Sao_Paulo')::date >= %s AND (criado_em AT TIME ZONE 'America/Sao_Paulo')::date <= %s
                ORDER BY criado_em DESC
            """, conexao.raw, params=(data_inicio.isoformat(), data_fim.isoformat()))

        dividas_rel = vendas_rel[vendas_rel["Status"].isin(["Devendo", "Parcial"])].copy() if not vendas_rel.empty else vendas_rel.copy()
        vendas_pagas_rel = vendas_rel if not vendas_rel.empty else vendas_rel.copy()
        faturamento_rel = float(vendas_pagas_rel["Valor recebido (R$)"].fillna(0).sum()) if not vendas_pagas_rel.empty else 0.0
        pendente_rel = float(dividas_rel["Saldo devedor (R$)"].fillna(0).sum()) if not dividas_rel.empty else 0.0
        lucro_rel = float(vendas_pagas_rel["Lucro bruto estimado (R$)"].fillna(0).sum()) if not vendas_pagas_rel.empty else 0.0

        st.markdown(f"**Período selecionado:** {data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Vendas no período", len(vendas_rel))
        m2.metric("Valor recebido", moeda(faturamento_rel))
        m3.metric("Dívidas em aberto", moeda(pendente_rel))
        m4.metric("Lucro bruto estimado", moeda(lucro_rel))

        aba_vendas, aba_dividas, aba_produtos, aba_movimentos = st.tabs(["Vendas", "Dívidas", "Estoque atual", "Movimentações"])
        with aba_vendas:
            st.write("Vendas registradas no período selecionado.")
            st.dataframe(vendas_rel, use_container_width=True, hide_index=True)
            st.download_button("Baixar vendas (CSV)", data=vendas_rel.to_csv(index=False).encode("utf-8-sig"), file_name=f"vendas_{data_inicio}_{data_fim}.csv", mime="text/csv", disabled=vendas_rel.empty)
        with aba_dividas:
            st.write("Vendas que ainda estão marcadas como pendentes no momento da consulta, dentro do período selecionado.")
            st.dataframe(dividas_rel, use_container_width=True, hide_index=True)
            st.download_button("Baixar dívidas (CSV)", data=dividas_rel.to_csv(index=False).encode("utf-8-sig"), file_name=f"dividas_{data_inicio}_{data_fim}.csv", mime="text/csv", disabled=dividas_rel.empty)
        with aba_produtos:
            st.write("Posição atual do estoque, independentemente das datas escolhidas.")
            st.dataframe(produtos_rel, use_container_width=True, hide_index=True)
            st.download_button("Baixar estoque atual (CSV)", data=produtos_rel.to_csv(index=False).encode("utf-8-sig"), file_name="estoque_atual_mabel_store.csv", mime="text/csv", disabled=produtos_rel.empty)
        with aba_movimentos:
            st.write("Entradas e saídas registradas no período selecionado.")
            st.dataframe(movimentacoes_rel, use_container_width=True, hide_index=True)
            st.download_button("Baixar movimentações (CSV)", data=movimentacoes_rel.to_csv(index=False).encode("utf-8-sig"), file_name=f"movimentacoes_{data_inicio}_{data_fim}.csv", mime="text/csv", disabled=movimentacoes_rel.empty)

        pacote = io.BytesIO()
        with zipfile.ZipFile(pacote, mode="w", compression=zipfile.ZIP_DEFLATED) as arquivo_zip:
            arquivo_zip.writestr("vendas.csv", vendas_rel.to_csv(index=False).encode("utf-8-sig"))
            arquivo_zip.writestr("dividas_pendentes.csv", dividas_rel.to_csv(index=False).encode("utf-8-sig"))
            arquivo_zip.writestr("estoque_atual.csv", produtos_rel.to_csv(index=False).encode("utf-8-sig"))
            arquivo_zip.writestr("movimentacoes_estoque.csv", movimentacoes_rel.to_csv(index=False).encode("utf-8-sig"))
        st.divider()
        st.download_button(
            "📦 Baixar todos os relatórios (ZIP)", data=pacote.getvalue(),
            file_name=f"relatorios_mabel_store_{data_inicio}_{data_fim}.zip",
            mime="application/zip", use_container_width=True,
        )
        st.info("Os arquivos CSV abrem no Excel e em outros programas de planilhas. O ZIP reúne todos os relatórios em um único download. Exportar não altera nem apaga os dados do sistema.")


# ------------------------------------------
# 11. VENDAS
# ------------------------------------------
elif pagina == "Vendas":
    st.subheader("Registrar uma venda")
    produtos_disponiveis = [p for p in listar_produtos() if p["quantidade"] > 0]

    if not produtos_disponiveis:
        st.warning("Não há produtos com estoque disponível. Cadastre produtos ou reponha o estoque antes de registrar uma venda.")
    else:
        busca_produto_venda = st.text_input(
            "Pesquisar produto pelo nome",
            placeholder="Digite o nome do produto para encontrar mais rápido...",
            key="busca_produto_venda",
        ).strip().casefold()

        produtos_filtrados = [
            p for p in produtos_disponiveis
            if busca_produto_venda in p["nome"].casefold()
        ]

        if not produtos_filtrados:
            st.warning("Nenhum produto com estoque disponível corresponde à pesquisa. Tente outro nome.")
        else:
            opcoes_produtos = {
                f"{p['nome']} — {moeda(p['preco'])} (estoque: {p['quantidade']})": p
                for p in produtos_filtrados
            }
            produto_escolhido = st.selectbox(
                "Produto vendido",
                list(opcoes_produtos.keys()),
                help="Você também pode digitar no campo de pesquisa acima para filtrar os produtos.",
            )
            produto = opcoes_produtos[produto_escolhido]

            with st.form("form_venda", clear_on_submit=True):
                cliente = st.text_input("Nome de quem comprou *", placeholder="Nome do cliente").strip()
                telefone_cliente = st.text_input(
                    "Telefone de quem comprou (opcional)",
                    placeholder="Ex.: (19) 99999-9999",
                    help="Você pode deixar este campo vazio.",
                ).strip()
                quantidade_vendida = st.number_input(
                    "Quantidade vendida", min_value=1,
                    max_value=int(produto["quantidade"]), value=1, step=1
                )
                forma_pagamento = st.selectbox(
                    "Forma de pagamento", ["Pix", "Dinheiro", "A pagar"]
                )
                data_prevista = st.date_input(
                    "Data prevista para pagamento (se for 'A pagar')",
                    value=date.today() + timedelta(days=7),
                    help="Escolha quando o cliente pretende pagar. Essa data só será salva para vendas marcadas como 'A pagar'.",
                )
                st.caption(f"Total desta venda: {moeda(produto['preco'] * quantidade_vendida)}")
                registrar = st.form_submit_button(
                    "Registrar venda e baixar estoque", use_container_width=True
                )

                if registrar:
                    if not cliente:
                        st.error("Informe o nome de quem comprou.")
                    else:
                        try:
                            registrar_venda(
                                produto["id"], cliente, int(quantidade_vendida),
                                forma_pagamento, telefone_cliente,
                                data_prevista.isoformat() if forma_pagamento == "A pagar" else None,
                            )
                            if forma_pagamento == "A pagar":
                                st.success(
                                    f"Venda registrada para {cliente}. O estoque foi atualizado "
                                    f"e o pagamento ficou como 'Devendo'. Data prevista: {data_prevista.strftime('%d/%m/%Y')}. "
                                    "Você poderá registrar pagamentos parciais no Controle de Dívidas."
                                )
                            else:
                                st.success(
                                    f"Venda registrada para {cliente}. O estoque foi atualizado "
                                    "e o pagamento foi marcado como 'Pago'."
                                )
                            st.rerun()
                        except ValueError as erro:
                            st.error(str(erro))

    st.divider()
    st.subheader("Histórico de vendas e pagamentos")
    vendas = listar_vendas()
    if not vendas:
        st.info("Ainda não há vendas registradas.")
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
                    st.caption(
                        f"Pagamento: {venda['forma_pagamento']} · Data: {venda['criado_em']}"
                    )
                with direita:
                    if venda["status_pagamento"] == "Pago":
                        st.success("Pago")
                    elif venda["status_pagamento"] == "Parcial":
                        st.info("Pagamento parcial")
                    else:
                        st.warning("Devendo")
                        if venda["forma_pagamento"] == "A pagar" and st.button(
                            "Quitar saldo", key=f"pagar_{venda['id']}",
                            use_container_width=True
                        ):
                            marcar_venda_paga(venda["id"])
                            st.rerun()

    # Gerenciamento de exclusão: separado do registro para evitar cliques acidentais.
    st.divider()
    with st.expander("🗑️ Gerenciar exclusão de vendas", expanded=False):
        st.warning(
            "A exclusão é permanente. Os pagamentos vinculados também serão removidos. "
            "Quando o produto ainda existir no cadastro, a quantidade vendida será devolvida ao estoque. "
            "O relatório de vendas será atualizado automaticamente."
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