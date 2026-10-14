import base64
import html
import os
import re
from io import BytesIO
from urllib.parse import quote

from PIL import Image, ImageOps

import psycopg2
import streamlit as st

st.set_page_config(
    page_title="Mabel Store | Catálogo",
    page_icon="🛍️",
    layout="wide",
)

WHATSAPP_COMERCIAL = st.secrets.get(
    "WHATSAPP_COMERCIAL",
    os.getenv("WHATSAPP_COMERCIAL", "5511999999999"),
)
WHATSAPP_COMERCIAL = re.sub(r"\D", "", str(WHATSAPP_COMERCIAL))
DB_URL = st.secrets.get(
    "SUPABASE_READONLY_DB_URL",
    os.getenv("SUPABASE_READONLY_DB_URL", ""),
)

# Paleta original da Mabel Store: lilás, branco e roxo.
COR_PRINCIPAL = "#76518F"
COR_ESCURO = "#59366F"
COR_CLARA = "#EDE4F3"
COR_FUNDO = "#FCFAFD"
COR_TEXTO = "#30283A"

st.markdown(f"""
<style>
/* Fonte cursiva decorativa inspirada no estilo "Beauty" enviado como referência.
   O restante do texto mantém fontes de sistema para preservar a leitura. */
@import url('https://fonts.googleapis.com/css2?family=Great+Vibes&display=swap');
:root {{
    --mabel-purple: {COR_PRINCIPAL};
    --mabel-purple-dark: {COR_ESCURO};
    --mabel-lilac: {COR_CLARA};
    --mabel-border: #E8DDEC;
}}
.stApp {{ background: {COR_FUNDO}; color: {COR_TEXTO}; }}
.block-container {{ max-width: 1240px; padding-top: 1.15rem; padding-bottom: 2.5rem; }}

/* Tipografia delicada: títulos cursivos e texto de produto limpo e legível. */
:root {{
    --mabel-font-body: "Aptos", "Segoe UI Variable", "Segoe UI", system-ui, sans-serif;
    --mabel-font-display: "Great Vibes", "URW Chancery L", "Apple Chancery", "Brush Script MT", cursive;
}}
.stApp, .stApp input, .stApp textarea, .stApp button, .stApp select {{
    font-family: var(--mabel-font-body) !important;
    font-weight: 400;
    letter-spacing: .005em;
}}
.stApp {{ -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }}
.mabel-header {{
    padding:.8rem 1rem .75rem; border:1px solid var(--mabel-border); border-radius:22px;
    background:linear-gradient(135deg,#FFFFFF 0%,#F8F3FB 100%);
    box-shadow:0 7px 22px rgba(89,54,111,.055);
}}
.mabel-header-main {{
    display:grid; grid-template-columns:84px minmax(0,1fr) 84px;
    align-items:center; gap:.35rem; min-height:80px;
}}
.mabel-logo-wrap {{ grid-column:1; display:flex; align-items:center; justify-content:flex-start; min-width:0; }}
.mabel-logo-img {{ width:76px; height:76px; max-width:100%; object-fit:contain; display:block; margin:0; }}
.mabel-header-title {{ grid-column:2; text-align:center; min-width:0; }}
.mabel-header-title h1 {{ color:{COR_ESCURO}; margin:0; font-family:var(--mabel-font-display); font-size:clamp(2.25rem,4.1vw,3.05rem); font-weight:400; letter-spacing:0; line-height:1.08; }}
.mabel-header-balance {{ grid-column:3; min-width:0; }}
.mabel-subtitle {{ color:#786B82; margin:.25rem 0 0; text-align:center; font-size:.96rem; font-weight:300; letter-spacing:.035em; line-height:1.55; }}
.section-title, h2.section-title, section .section-title {{
    color:{COR_TEXTO}; font-family:var(--mabel-font-display) !important;
    font-size:1.95rem; font-weight:400 !important; margin:1.65rem 0 .8rem;
    letter-spacing:0; line-height:1.2; text-align:center;
}}

/* Carrinho discreto: abre o conteúdo apenas quando o botão é acionado. */
.st-key-cart-toolbar {{
    margin:.45rem 0 1rem; width:100%; display:flex !important;
    justify-content:flex-end !important; align-items:center !important;
}}
.st-key-cart-toolbar > div[data-testid="stVerticalBlock"] {{
    display:flex !important; flex-direction:row !important; justify-content:flex-end !important;
    align-items:center !important; width:100% !important; min-width:0;
}}
.st-key-cart-toolbar div[data-testid="stPopover"] {{
    width:auto !important; min-width:0 !important; margin-left:auto !important;
}}
.st-key-cart-toolbar div[data-testid="stPopover"] > button {{
    width:auto !important; min-width:0 !important; border-radius:999px !important;
    padding:.46rem .9rem !important; background:#FFFFFF !important;
    color:{COR_ESCURO} !important; border:1px solid #DCCBE7 !important;
    font-size:.85rem !important; font-weight:600 !important; letter-spacing:.01em !important;
    box-shadow:0 3px 12px rgba(89,54,111,.08) !important;
}}
.st-key-cart-toolbar div[data-testid="stPopover"] > button:hover {{
    background:#F5EEF9 !important; border-color:#CFB5E0 !important;
}}
div[data-testid="stPopoverBody"] {{
    width:min(410px, calc(100vw - 1.25rem)) !important;
    max-width:calc(100vw - 1.25rem) !important;
    max-height:min(72vh, 620px); overflow-y:auto;
}}
div[data-testid="stPopoverBody"] div[data-testid="stButton"] > button,
div[data-testid="stPopoverBody"] div[data-testid="stLinkButton"] > a {{ min-height:34px !important; padding:.35rem .55rem !important; font-size:.82rem !important; }}
.cart-popover-heading {{ color:{COR_ESCURO}; font-family:var(--mabel-font-display); font-weight:400; font-size:1.5rem; letter-spacing:0; line-height:1.2; margin:.1rem 0 .5rem; }}
.cart-popover-intro {{ color:#786B82; font-size:.82rem; font-weight:350; line-height:1.45; margin-bottom:.65rem; }}
.cart-item-mini {{ border:1px solid #EEE5F3; border-radius:12px; background:#FFFFFF; padding:.6rem .7rem; margin:.4rem 0 .45rem; }}
.cart-item-mini-name {{ color:{COR_TEXTO}; font-weight:550; font-size:.88rem; line-height:1.4; letter-spacing:.005em; overflow-wrap:anywhere; }}
.cart-item-mini-detail {{ color:#776C7E; font-size:.78rem; line-height:1.4; margin-top:.2rem; overflow-wrap:anywhere; }}
.cart-popover-total {{ background:#F5EEF9; border:1px solid #E8DDEC; padding:.7rem .8rem; border-radius:12px; color:{COR_ESCURO}; font-size:.92rem; line-height:1.45; }}

/* Grades responsivas para Destaques, Promoções e Kits (sem carrossel) */
.product-section-grid {{
    display:grid; grid-template-columns:repeat(4,minmax(0,1fr));
    align-items:stretch; gap:1rem; width:100%; max-width:100%; min-width:0;
    padding:.25rem 0 .6rem; box-sizing:border-box;
}}
.product-card {{ min-width:0; width:100%; display:flex; flex-direction:column; overflow:hidden; border:1px solid var(--mabel-border); border-radius:18px; background:#fff; box-shadow:0 5px 18px rgba(89,54,111,.07); transition:transform .18s ease,box-shadow .18s ease; box-sizing:border-box; }}
.product-card:hover {{ transform:translateY(-2px); box-shadow:0 9px 24px rgba(89,54,111,.12); }}
.product-image {{ width:100%; aspect-ratio:1 / 1; height:auto; object-fit:contain; background:#fff; border:1px solid #F0EAF4; border-radius:13px; display:block; padding:9px; box-sizing:border-box; }}
.product-image-placeholder {{ width:100%; aspect-ratio:1 / 1; height:auto; display:flex; align-items:center; justify-content:center; background:#fff; border:1px solid #F0EAF4; border-radius:13px; color:{COR_PRINCIPAL}; font-size:2.6rem; box-sizing:border-box; }}
.product-info {{ padding:1rem; display:flex; flex-direction:column; flex:1; }}
.product-name {{ color:{COR_TEXTO}; font-weight:600; font-size:1rem; line-height:1.4; letter-spacing:.002em; min-height:2.7em; overflow-wrap:anywhere; }}
.product-category {{ display:inline-block; width:fit-content; max-width:100%; margin:.55rem 0; background:{COR_CLARA}; color:{COR_ESCURO}; border-radius:30px; padding:.24rem .62rem; font-size:.74rem; font-weight:400; letter-spacing:.01em; overflow-wrap:anywhere; }}
.product-price {{ color:{COR_ESCURO}; font-weight:700; font-size:1.16rem; letter-spacing:.005em; margin:.35rem 0 .7rem; }}
.old-price {{ color:#827787; text-decoration:line-through; font-size:.86rem; margin-top:.35rem; }}
.stock-quantity {{ display:inline-block; width:fit-content; max-width:100%; color:#766A7D; font-size:.78rem; line-height:1.4; font-weight:450; margin:.05rem 0 .5rem; white-space:normal; overflow-wrap:anywhere; }}
.buy-link {{ display:block; margin-top:auto; text-align:center; background:#E3D3F0; color:{COR_ESCURO} !important; text-decoration:none !important; border:1px solid #D5BFE7; border-radius:11px; padding:.72rem .6rem; font-weight:600; letter-spacing:.005em; transition:background .18s ease,transform .18s ease; }}
.buy-link:hover {{ background:#D7C0E8; transform:translateY(-1px); }}
.description-toggle {{ width:100%; max-width:100%; min-width:0; margin:.1rem 0 .65rem; box-sizing:border-box; }}
.description-toggle summary {{
    display:block; width:100%; box-sizing:border-box; list-style:none; cursor:pointer;
    text-align:center; background:#E3D3F0; color:{COR_ESCURO}; border:1px solid #D5BFE7;
    border-radius:11px; padding:.62rem .55rem; font-size:.88rem; line-height:1.3; font-weight:750;
    overflow-wrap:anywhere; transition:background .18s ease;
}}
.description-toggle summary::-webkit-details-marker {{ display:none; }}
.description-toggle summary::after {{ content:"＋"; margin-left:.45rem; font-weight:800; }}
.description-toggle[open] summary::after {{ content:"−"; }}
.description-toggle summary:hover {{ background:#D7C0E8; }}
.description-content {{ margin-top:.45rem; padding:.7rem; border:1px solid #E8DDEC; border-radius:10px;
    background:#FCFAFD; color:#4F4557; font-size:.88rem; line-height:1.45; white-space:pre-line;
    overflow-wrap:anywhere; box-sizing:border-box; }}

/* Cartões do catálogo principal: visual coordenado com os Destaques,
   porém mais compacto para mostrar mais produtos de uma vez. */
.st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"] {{
    min-height:100%; width:100%; min-width:0; box-sizing:border-box;
    border:1px solid var(--mabel-border) !important;
    border-radius:18px !important; background:#FFFFFF !important;
    padding:0 !important; box-shadow:0 5px 18px rgba(89,54,111,.07);
    display:flex; flex-direction:column; overflow:hidden;
    transition:box-shadow .18s ease,border-color .18s ease;
}}
.st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"] > div {{
    min-width:0; flex:1; display:flex; flex-direction:column; box-sizing:border-box;
}}
.st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"]:hover {{
    border-color:#D8C3E7 !important; box-shadow:0 8px 23px rgba(89,54,111,.11);
}}
.st-key-catalogo-grid [data-testid="stImage"] {{
    width:84% !important; max-width:178px !important; aspect-ratio:1 / 1; height:auto !important;
    min-width:0; margin:.5rem auto .2rem !important;
    display:flex !important; align-items:center; justify-content:center;
    overflow:hidden; background:#FFFFFF !important; border:1px solid #F0EAF4;
    border-radius:13px; padding:6px; box-sizing:border-box;
}}
.st-key-catalogo-grid [data-testid="stImage"] img {{
    display:block; height:100% !important; width:100% !important; max-width:100% !important;
    aspect-ratio:1 / 1; object-fit:contain !important; background:#FFFFFF; border-radius:9px;
    padding:3px; box-sizing:border-box;
}}
.st-key-catalogo-grid [data-testid="stMarkdownContainer"] {{
    width:100%; max-width:100%; min-width:0; padding:0 .68rem; box-sizing:border-box;
    overflow-wrap:anywhere;
}}
.st-key-catalogo-grid .product-image-placeholder {{ aspect-ratio:1 / 1; width:100%; height:auto; background:#FFFFFF; border:1px solid #F0EAF4; border-radius:13px; box-sizing:border-box; }}
.st-key-catalogo-grid .catalog-product-name {{ color:{COR_TEXTO}; font-size:.94rem; font-weight:600; letter-spacing:.002em; line-height:1.35; min-height:2.45em; overflow-wrap:anywhere; margin:.16rem 0 .28rem; }}
.st-key-catalogo-grid .catalog-category {{ display:inline-block; width:fit-content; max-width:100%; color:{COR_ESCURO}; background:{COR_CLARA}; font-size:.72rem; font-weight:400; letter-spacing:.01em; line-height:1.3; min-height:0; margin:.12rem 0 .34rem; padding:.22rem .52rem; border-radius:30px; overflow-wrap:anywhere; }}
.st-key-catalogo-grid .catalog-stock-quantity {{ display:block; color:#766A7D; font-size:.74rem; line-height:1.35; font-weight:450; margin:.02rem 0 .34rem; overflow-wrap:anywhere; }}
.st-key-catalogo-grid [data-testid="stButton"],
.st-key-catalogo-grid [data-testid="stLinkButton"] {{
    width:100%; max-width:100%; min-width:0; padding:0 .68rem; box-sizing:border-box;
}}
.st-key-catalogo-grid [data-testid="stButton"] > button,
.st-key-catalogo-grid [data-testid="stLinkButton"] > a {{
    width:100% !important; max-width:100% !important; box-sizing:border-box !important;
}}

/* Botões: lilás claro, inclusive os antigos botões escuros */
div[data-testid="stButton"] > button,
div[data-testid="stLinkButton"] > a {{
    border-radius:11px !important; border:1px solid #D5BFE7 !important;
    background:#E3D3F0 !important; color:{COR_ESCURO} !important;
    font-weight:600 !important; letter-spacing:.005em; box-shadow:none !important;
    transition:background .18s ease,border-color .18s ease,transform .18s ease;
}}
div[data-testid="stButton"] > button:hover,
div[data-testid="stLinkButton"] > a:hover {{
    background:#D7C0E8 !important; border-color:#C6A9DE !important;
    color:{COR_ESCURO} !important;
}}
div[data-testid="stButton"] > button:focus,
div[data-testid="stLinkButton"] > a:focus {{
    box-shadow:0 0 0 .18rem rgba(118,81,143,.18) !important;
}}
div[data-testid="stButton"] > button:disabled {{
    background:#F4EFF8 !important; color:#95869F !important; border-color:#E9E0EF !important;
}}

/* Entradas e área do carrinho */
.stTextInput input, .stMultiSelect [data-baseweb="select"],
.stSelectbox [data-baseweb="select"] {{ border-radius:11px; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius:17px; }}
.cart-total {{ background:#F5EEF9; border:1px solid #E8DDEC; padding:1rem 1.1rem; border-radius:14px; color:{COR_ESCURO}; line-height:1.5; }}
@media(max-width:900px) {{ .product-section-grid {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} }}
@media(max-width:620px) {{
    .block-container {{
        width:100% !important; max-width:100% !important;
        padding-left:.65rem !important; padding-right:.65rem !important;
        padding-top:.7rem; padding-bottom:1.5rem;
        box-sizing:border-box !important;
    }}
    .mabel-header {{ padding:.65rem .65rem .7rem; border-radius:17px; }}
    .mabel-header-main {{ grid-template-columns:60px minmax(0,1fr) 60px; min-height:60px; gap:.2rem; }}
    .mabel-logo-img {{ width:56px; height:56px; }}
    .mabel-header-title h1 {{ font-size:2.2rem; letter-spacing:0; line-height:1.05; }}
    .mabel-subtitle {{ font-size:.78rem; line-height:1.4; margin-top:.3rem; letter-spacing:.01em; }}
    .st-key-cart-toolbar {{ margin:.35rem 0 .75rem; width:100% !important; }}
    .st-key-cart-toolbar > div[data-testid="stVerticalBlock"] {{
        display:flex !important; flex-direction:row !important; justify-content:flex-end !important;
        align-items:center !important; width:100% !important;
    }}
    .st-key-cart-toolbar div[data-testid="stPopover"] {{ margin-left:auto !important; }}
    .st-key-cart-toolbar div[data-testid="stPopover"] > button {{
        padding:.36rem .68rem !important; font-size:.78rem !important; max-width:100% !important;
    }}
    .section-title, h2.section-title, section .section-title {{
        font-size:1.72rem; margin:1.25rem 0 .7rem; text-align:center;
        font-family:var(--mabel-font-display) !important; font-weight:400 !important;
    }}

    /* O catálogo principal vira uma grade real de 2 colunas no celular.
       Não usa rolagem horizontal nem transforma os produtos em carrossel. */
    .st-key-catalogo-grid {{ width:100% !important; max-width:100% !important; min-width:0 !important; }}
    .st-key-catalogo-grid [data-testid="stHorizontalBlock"] {{
        display:grid !important;
        grid-template-columns:repeat(2,minmax(0,1fr)) !important;
        align-items:stretch !important;
        column-gap:.72rem !important; row-gap:.82rem !important;
        width:94% !important; max-width:460px !important; min-width:0 !important;
        margin-left:auto !important; margin-right:auto !important;
        box-sizing:border-box !important;
    }}
    .st-key-catalogo-grid [data-testid="column"] {{
        width:100% !important; max-width:100% !important; min-width:0 !important;
        flex:none !important; margin:0 !important; padding:0 !important;
        box-sizing:border-box !important;
    }}
    .st-key-catalogo-grid [data-testid="column"] > div,
    .st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"] {{
        width:100% !important; max-width:100% !important; min-width:0 !important;
        box-sizing:border-box !important;
    }}
    .st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"] {{
        width:92% !important; max-width:100% !important;
        margin:.1rem auto !important; padding:0 !important;
        border-radius:13px !important;
    }}
    .st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"] > div {{
        min-width:0; width:100%; box-sizing:border-box;
    }}
    .st-key-catalogo-grid [data-testid="stMarkdownContainer"] {{
        padding:0 .42rem; box-sizing:border-box;
    }}
    .st-key-catalogo-grid [data-testid="stButton"],
    .st-key-catalogo-grid [data-testid="stLinkButton"] {{
        padding:0 .42rem; box-sizing:border-box;
    }}
    .st-key-catalogo-grid [data-testid="stImage"] {{
        display:flex !important; width:78% !important; max-width:124px !important;
        min-width:0 !important; aspect-ratio:1 / 1; height:auto !important;
        margin:.42rem auto .12rem !important; padding:5px; border-radius:11px;
        box-sizing:border-box !important;
    }}
    .st-key-catalogo-grid [data-testid="stImage"] img {{
        display:block; height:100% !important; width:100% !important;
        max-width:100% !important; object-fit:contain !important;
    }}
    .st-key-catalogo-grid .catalog-product-name {{
        font-size:.82rem !important; line-height:1.28 !important;
        min-height:2.45em; overflow-wrap:anywhere; word-break:normal;
        margin:.12rem 0 .25rem;
    }}
    .st-key-catalogo-grid .catalog-category {{
        font-size:.64rem !important; line-height:1.22 !important;
        overflow-wrap:anywhere; min-height:0; margin:.1rem 0 .28rem; padding:.19rem .35rem;
    }}
    .st-key-catalogo-grid .product-price {{ font-size:.9rem !important; overflow-wrap:anywhere; margin:.2rem 0 .4rem; }}
    .st-key-catalogo-grid .old-price {{ font-size:.72rem !important; }}
    .st-key-catalogo-grid [data-testid="stButton"] > button,
    .st-key-catalogo-grid [data-testid="stLinkButton"] > a {{
        display:flex !important; align-items:center !important; justify-content:center !important;
        width:100% !important; max-width:100% !important; min-width:0 !important;
        min-height:36px !important; height:auto !important;
        padding:.32rem .22rem !important; font-size:.66rem !important;
        line-height:1.16 !important; white-space:normal !important;
        overflow-wrap:anywhere !important; word-break:normal !important;
        box-sizing:border-box !important;
    }}
    .st-key-catalogo-grid [data-testid="stMarkdownContainer"] {{
        width:100%; max-width:100%; min-width:0; overflow-wrap:anywhere;
    }}
    /* Todas as seções de produtos também usam 2 colunas no celular.
       Sem trilho horizontal: nenhum cartão empurra o vizinho para o lado. */
    .product-section-grid {{
        grid-template-columns:repeat(2,minmax(0,1fr)) !important;
        column-gap:.72rem !important; row-gap:.82rem !important;
        width:94% !important; max-width:460px !important; min-width:0 !important;
        margin-left:auto !important; margin-right:auto !important;
    }}
    .product-card {{ width:100%; min-width:0; margin:0; border-radius:13px; }}
    .product-image,.product-image-placeholder {{ width:100%; height:auto; aspect-ratio:1 / 1; padding:5px; border-radius:10px; }}
    .product-info {{ padding:.48rem .42rem; min-width:0; }}
    .product-name {{ font-size:.8rem; line-height:1.28; min-height:2.4em; overflow-wrap:anywhere; }}
    .product-category {{ font-size:.62rem; padding:.19rem .34rem; max-width:100%; margin:.32rem 0; }}
    .stock-quantity,.catalog-stock-quantity {{ font-size:.63rem; line-height:1.26; margin:.02rem 0 .3rem; }}
    /* Menos efeitos/retrabalho no celular e imagens sempre contidas no cartão. */
    .product-card,.st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"] {{
        transform:none !important; transition:none !important;
    }}
    .product-image,.product-image-placeholder {{ max-width:100%; }}
    .st-key-catalogo-grid [data-testid="stImage"] img {{ content-visibility:auto; }}
    .st-key-catalogo-grid .product-image-placeholder {{ width:100%; height:auto; aspect-ratio:1 / 1; border-radius:11px; }}
    .product-price {{ font-size:.96rem; overflow-wrap:anywhere; margin:.28rem 0 .55rem; }}
    .buy-link {{ padding:.42rem .2rem; font-size:.65rem; line-height:1.18; overflow-wrap:anywhere; border-radius:8px; }}
    .description-toggle {{ margin-bottom:.38rem; }}
    .description-toggle summary {{ padding:.4rem .2rem; font-size:.65rem; line-height:1.18; border-radius:8px; }}
    .description-content {{ padding:.45rem; font-size:.7rem; line-height:1.35; }}
}}
</style>
""", unsafe_allow_html=True)


def moeda(valor):
    return (
        f"R$ {float(valor or 0):,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def preco_efetivo(produto):
    preco_normal = float(produto[3] or 0)
    promocional = float(produto[6] or 0)
    if 0 < promocional < preco_normal:
        return promocional
    return preco_normal


def abrir_conexao():
    if not DB_URL:
        raise RuntimeError(
            "Configure SUPABASE_READONLY_DB_URL nos Secrets do Streamlit."
        )
    return psycopg2.connect(
        DB_URL,
        sslmode="require",
        connect_timeout=10,
        application_name="MabelStoreCatalogoPublico",
    )


@st.cache_data(ttl=30, max_entries=5, show_spinner=False)
def carregar_dados():
    """Carrega todos os produtos; cache curto reduz acessos ao banco."""
    conn = abrir_conexao()
    try:
        with conn:
            with conn.cursor() as cur:
                # Sem filtro de quantidade: todos os itens permanecem visíveis.
                cur.execute("""
                    SELECT p.id, p.nome, p.categoria, p.preco,
                           p.quantidade, p.foto, p.preco_promocional,
                           COALESCE(to_jsonb(p)->>'descricao', '') AS descricao
                    FROM public.produtos p
                    ORDER BY p.nome
                """)
                produtos = cur.fetchall()

                try:
                    cur.execute("""
                        SELECT p.id, p.nome, p.categoria, p.preco,
                               p.quantidade, p.foto, p.preco_promocional,
                               COALESCE(to_jsonb(p)->>'descricao', '') AS descricao
                        FROM public.catalogo_destaques d
                        JOIN public.produtos p ON p.id = d.produto_id
                        ORDER BY d.ordem, p.nome
                    """)
                    destaques = cur.fetchall()
                except psycopg2.Error:
                    conn.rollback()
                    destaques = []

                try:
                    cur.execute("""
                        SELECT p.id, p.nome, p.categoria, p.preco,
                               p.quantidade, p.foto, p.preco_promocional,
                               COALESCE(to_jsonb(p)->>'descricao', '') AS descricao
                        FROM public.catalogo_promocoes cp
                        JOIN public.produtos p ON p.id = cp.produto_id
                        WHERE p.preco_promocional > 0
                          AND p.preco_promocional < p.preco
                        ORDER BY cp.ordem, p.nome
                    """)
                    promocoes = cur.fetchall()
                except psycopg2.Error:
                    conn.rollback()
                    promocoes = []
        # Normaliza BLOBs para bytes. O cache evita repetir a consulta pesada a cada
        # clique do carrinho; os saldos são atualizados automaticamente em até 30 s.
        def normalizar_fotos(linhas):
            return [
                tuple(bytes(v) if isinstance(v, memoryview) else v for v in linha)
                for linha in linhas
            ]
        return (
            normalizar_fotos(produtos),
            normalizar_fotos(destaques),
            normalizar_fotos(promocoes),
        )
    finally:
        conn.close()


@st.cache_data(ttl=3600, max_entries=500, show_spinner=False)
def otimizar_imagem_catalogo(foto_bytes, max_lado=640, qualidade=74):
    """Gera miniaturas WebP leves para carregar mais rápido em telas móveis."""
    if not foto_bytes:
        return ("image/jpeg", b"")
    foto_bytes = bytes(foto_bytes)
    try:
        with Image.open(BytesIO(foto_bytes)) as original:
            imagem = ImageOps.exif_transpose(original)
            imagem.thumbnail((max_lado, max_lado), Image.Resampling.LANCZOS)
            if "A" in imagem.getbands():
                imagem = imagem.convert("RGBA")
            else:
                imagem = imagem.convert("RGB")
            buffer = BytesIO()
            imagem.save(buffer, format="WEBP", quality=qualidade, method=4)
            return ("image/webp", buffer.getvalue())
    except Exception:
        # Se a imagem não puder ser convertida, preserva o arquivo e seu formato.
        if foto_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            tipo = "image/png"
        elif foto_bytes[:3] == b"GIF":
            tipo = "image/gif"
        elif foto_bytes[:4] == b"RIFF" and foto_bytes[8:12] == b"WEBP":
            tipo = "image/webp"
        else:
            tipo = "image/jpeg"
        return (tipo, foto_bytes)


def quantidade_disponivel_html(quantidade, css_class="stock-quantity"):
    """Mostra somente a quantidade, sem etiquetas de status."""
    estoque = max(0, int(quantidade or 0))
    return f'<div class="{css_class}">Quantidade disponível: {estoque}</div>'


def categorias_do_produto(valor):
    partes = re.split(r"\s*[|,;]\s*", str(valor or "Sem categoria"))
    limpas = [parte.strip() for parte in partes if parte.strip()]
    return limpas or ["Sem categoria"]


def descricao_html(descricao):
    """Cria o botão expansível apenas quando há uma descrição preenchida."""
    texto = str(descricao or "").strip()
    if not texto:
        return ""
    texto_seguro = html.escape(texto)
    return (
        '<details class="description-toggle">'
        '<summary>Ver descrição</summary>'
        f'<div class="description-content">{texto_seguro}</div>'
        '</details>'
    )


def imagem_html(foto, nome):
    if foto:
        tipo, miniatura = otimizar_imagem_catalogo(bytes(foto))
        codificada = base64.b64encode(miniatura).decode("ascii")
        return (
            '<img class="product-image" loading="lazy" decoding="async" '
            f'src="data:{tipo};base64,{codificada}" '
            f'alt="{html.escape(str(nome))}">'
        )
    return '<div class="product-image-placeholder">🛍️</div>'


def link_whatsapp(mensagem):
    numero = WHATSAPP_COMERCIAL
    texto = quote(mensagem, safe="")
    return f"https://wa.me/{numero}?text={texto}"


def card_html(produto):
    """Cartão HTML usado nas grades; mantém o contato direto por WhatsApp."""
    _pid, nome, categoria, preco, quantidade, foto, preco_promocional, descricao = produto
    preco_normal = float(preco or 0)
    promocional = float(preco_promocional or 0)
    em_promocao = 0 < promocional < preco_normal
    preco_atual = promocional if em_promocao else preco_normal
    nome_seguro = html.escape(str(nome or "Produto"))
    categoria_segura = html.escape(" · ".join(categorias_do_produto(categoria)))

    estoque = max(0, int(quantidade or 0))
    quantidade_html = quantidade_disponivel_html(estoque)
    if estoque > 0:
        rotulo_botao = "Pedir pelo WhatsApp"
    else:
        rotulo_botao = "Consultar reposição"

    mensagem = (
        f"Olá! Tenho interesse no produto: {nome or 'Produto'}. "
        f"Preço informado: {moeda(preco_atual)}. "
        + ("No momento, o catálogo mostra 0 unidades disponíveis. Gostaria de consultar a reposição." if int(quantidade or 0) <= 0 else "")
    )
    link = link_whatsapp(mensagem)

    if em_promocao:
        preco_html = (
            f'<div class="old-price">De {moeda(preco_normal)}</div>'
            f'<div class="product-price">Por {moeda(preco_atual)} '
            f'<span style="font-size:.72rem;background:#EDE4F3;'
            f'padding:.18rem .4rem;border-radius:20px">OFERTA</span></div>'
        )
    else:
        preco_html = f'<div class="product-price">{moeda(preco_atual)}</div>'

    return (
        f'<article class="product-card">{imagem_html(foto, nome)}'
        f'<div class="product-info"><div class="product-name">{nome_seguro}</div>'
        f'<span class="product-category">{categoria_segura}</span>'
        f'{quantidade_html}{preco_html}{descricao_html(descricao)}'
        f'<a class="buy-link" href="{link}" target="_blank" rel="noopener">'
        f'{rotulo_botao}</a></div></article>'
    )


def secao_grade(titulo, produtos_secao):
    """Exibe os produtos em grade responsiva, sem rolagem horizontal."""
    if not produtos_secao:
        return ""
    cards = "".join(card_html(p) for p in produtos_secao)
    return (
        f'<section><h2 class="section-title">{titulo}</h2>'
        f'<div class="product-section-grid">{cards}</div></section>'
    )


def renderizar_cartao_interativo(produto, indice):
    pid, nome, categoria, preco, quantidade, foto, preco_promocional, descricao = produto
    pid_chave = str(pid)
    estoque = max(0, int(quantidade or 0))
    preco_normal = float(preco or 0)
    promocional = float(preco_promocional or 0)
    em_promocao = 0 < promocional < preco_normal
    preco_atual = promocional if em_promocao else preco_normal
    carrinho = st.session_state.setdefault("mabel_store_carrinho", {})

    with st.container(border=True):
        if foto:
            _tipo_imagem, foto_otimizada = otimizar_imagem_catalogo(bytes(foto))
            st.image(foto_otimizada, use_container_width=True)
        else:
            st.markdown(
                f'<div class="product-image-placeholder">🛍️</div>',
                unsafe_allow_html=True,
            )

        st.markdown(
            f'<div class="catalog-product-name">{html.escape(str(nome or "Produto"))}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="catalog-category">{html.escape(" · ".join(categorias_do_produto(categoria)))}</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            quantidade_disponivel_html(estoque, "catalog-stock-quantity"),
            unsafe_allow_html=True,
        )

        if em_promocao:
            st.markdown(
                f'<div class="old-price">De {moeda(preco_normal)}</div>'
                f'<div class="product-price">Por {moeda(preco_atual)} 🔥</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="product-price">{moeda(preco_atual)}</div>',
                unsafe_allow_html=True,
            )

        if str(descricao or "").strip():
            st.markdown(descricao_html(descricao), unsafe_allow_html=True)

        if estoque > 0:
            if st.button(
                "🛒 Adicionar ao carrinho",
                key=f"adicionar_carrinho_{pid_chave}_{indice}",
                type="primary",
                use_container_width=True,
            ):
                quantidade_atual = int(carrinho.get(pid_chave, 0))
                if quantidade_atual < estoque:
                    carrinho[pid_chave] = quantidade_atual + 1
                    st.toast(f"{nome} adicionado ao carrinho.")
                else:
                    st.warning(f"Você já adicionou todo o estoque disponível de {nome}.")
                st.rerun()
        else:
            st.button(
                "Indisponível para adicionar",
                key=f"indisponivel_{pid_chave}_{indice}",
                disabled=True,
                use_container_width=True,
            )

        if estoque > 0:
            mensagem = (
                f"Olá! Tenho interesse no produto {nome}. "
                f"Preço: {moeda(preco_atual)}."
            )
            texto_link = "Pedir só este pelo WhatsApp"
        else:
            mensagem = (
                f"Olá! Gostaria de consultar a reposição do produto {nome}, "
                f"que está com 0 unidades disponíveis no catálogo."
            )
            texto_link = "Consultar pelo WhatsApp"
        st.link_button(
            texto_link,
            link_whatsapp(mensagem),
            use_container_width=True,
        )


def mostrar_carrinho(produtos):
    """Mostra um botão compacto que abre o carrinho em um popover."""
    produtos_por_id = {str(p[0]): p for p in produtos}
    carrinho = st.session_state.setdefault("mabel_store_carrinho", {})

    # Remove itens excluídos do estoque pelo administrador.
    for pid_chave in list(carrinho.keys()):
        if pid_chave not in produtos_por_id:
            carrinho.pop(pid_chave, None)

    quantidade_itens = sum(max(0, int(q)) for q in carrinho.values())
    with st.popover(f"🛍️ Meu carrinho · {quantidade_itens}", use_container_width=False):
        st.markdown('<div class="cart-popover-heading">Seu pedido</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="cart-popover-intro">Confira os produtos e envie tudo em uma única mensagem pelo WhatsApp. ✨</div>',
            unsafe_allow_html=True,
        )

        if not carrinho:
            st.caption("Seu carrinho está vazio. Adicione produtos para montar seu pedido.")
            return

        total = 0.0
        tem_indisponivel = False
        tem_quantidade_acima_estoque = False

        for pid_chave in list(carrinho.keys()):
            produto = produtos_por_id.get(pid_chave)
            if not produto:
                continue

            _pid, nome, _categoria, _preco, quantidade, _foto, _preco_promocional, _descricao = produto
            qtd = max(1, int(carrinho.get(pid_chave, 1)))
            estoque = max(0, int(quantidade or 0))
            preco_atual = preco_efetivo(produto)
            subtotal = preco_atual * qtd
            total += subtotal

            st.markdown(
                f'<div class="cart-item-mini">'
                f'<div class="cart-item-mini-name">{html.escape(str(nome or "Produto"))}</div>'
                f'<div class="cart-item-mini-detail">{qtd} × {moeda(preco_atual)} · Subtotal: {moeda(subtotal)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if estoque <= 0:
                st.caption("Este produto está sem unidades disponíveis.")
                tem_indisponivel = True
            elif qtd > estoque:
                st.warning(f"Estoque atual de {nome}: {estoque}. Reduza a quantidade.")
                tem_quantidade_acima_estoque = True

            controles = st.columns([1, 1, 1.45], gap="small")
            with controles[0]:
                if st.button("−", key=f"cart_menos_{pid_chave}", disabled=qtd <= 1, help="Diminuir quantidade", use_container_width=True):
                    carrinho[pid_chave] = qtd - 1
                    st.rerun()
            with controles[1]:
                if st.button("+", key=f"cart_mais_{pid_chave}", disabled=(estoque <= 0 or qtd >= estoque), help="Aumentar quantidade", use_container_width=True):
                    carrinho[pid_chave] = qtd + 1
                    st.rerun()
            with controles[2]:
                if st.button("Remover", key=f"cart_remover_{pid_chave}", help="Remover este item", use_container_width=True):
                    carrinho.pop(pid_chave, None)
                    st.rerun()
            st.divider()

        st.markdown(
            f'<div class="cart-popover-total"><strong>Total estimado: {moeda(total)}</strong></div>',
            unsafe_allow_html=True,
        )
        st.caption("O pagamento não é processado no site; o pedido será enviado para confirmação pelo WhatsApp.")

        if tem_indisponivel or tem_quantidade_acima_estoque:
            st.warning(
                "Revise as quantidades: há produto sem estoque ou uma quantidade maior que a disponível. "
                "Ajuste o carrinho antes de enviar."
            )
        else:
            linhas_pedido = [
                "Olá! Gostaria de fazer este pedido na Mabel Store:",
                "",
            ]
            for pid_chave, qtd in carrinho.items():
                produto = produtos_por_id.get(pid_chave)
                if not produto:
                    continue
                nome_produto = str(produto[1] or "Produto")
                preco_unitario = preco_efetivo(produto)
                subtotal = preco_unitario * int(qtd)
                linhas_pedido.append(
                    f"{int(qtd)} x {nome_produto} — {moeda(preco_unitario)} cada = {moeda(subtotal)}"
                )
            linhas_pedido += ["", f"Total estimado: {moeda(total)}", "", "Aguardo confirmação de disponibilidade e entrega. Obrigado(a)!"]
            st.link_button(
                "Enviar pedido pelo WhatsApp",
                link_whatsapp("\n".join(linhas_pedido)),
                type="primary",
                use_container_width=True,
            )

        if st.button("Esvaziar carrinho", key="esvaziar_carrinho", use_container_width=True):
            carrinho.clear()
            st.rerun()


try:
    produtos, destaques, promocoes_selecionadas = carregar_dados()
except Exception as erro:
    st.error(
        "Não foi possível carregar o catálogo. Confira a conexão do banco e as tabelas necessárias."
    )
    st.caption(str(erro))
    st.stop()

logo_path = os.path.join(os.path.dirname(__file__), "logo_store.png")
try:
    with open(logo_path, "rb") as arquivo_logo:
        logo_base64 = base64.b64encode(arquivo_logo.read()).decode("ascii")
except FileNotFoundError:
    st.error("Não encontrei logo_store.png. Coloque a logo na mesma pasta de catalogo_publico.py.")
    st.stop()

st.markdown(
    f'<header class="mabel-header">'
    f'<div class="mabel-header-main">'
    f'<div class="mabel-logo-wrap"><img class="mabel-logo-img" src="data:image/png;base64,{logo_base64}" alt="Logo Mabel Store"></div>'
    f'<div class="mabel-header-title"><h1>Vitrine</h1></div>'
    f'<div class="mabel-header-balance" aria-hidden="true"></div>'
    f'</div>'
    f'<p class="mabel-subtitle">Veja os produtos disponíveis na loja aqui <span aria-hidden="true">✨</span></p>'
    f'</header>',
    unsafe_allow_html=True,
)

# Carrinho compacto, recolhido até o visitante clicar no botão.
with st.container(key="cart-toolbar"):
    mostrar_carrinho(produtos)

# Produtos marcados no painel aparecem em grades, com a quantidade disponível.
kits = [p for p in produtos if str(p[2] or "").strip().casefold() == "kits"]
html_secoes = (
    secao_grade("Destaques ✨", destaques)
    + secao_grade("Promoções 🔥", promocoes_selecionadas)
    + secao_grade("Kits 🎁", kits)
)
if html_secoes:
    st.html(html_secoes)

st.markdown('<h1 class="section-title">Nosso catálogo</h1>', unsafe_allow_html=True)
if not produtos:
    st.info("Ainda não há produtos cadastrados.")
else:
    c1, c2 = st.columns([2, 1])
    busca = c1.text_input(
        "Pesquisar produto",
        placeholder="Digite o nome do produto...",
    ).strip().casefold()

    categorias = sorted(
        {
            categoria_item
            for p in produtos
            for categoria_item in categorias_do_produto(p[2])
        },
        key=str.casefold,
    )
    categorias_selecionadas = c2.multiselect(
        "Categorias",
        options=categorias,
        default=[],
        placeholder="Todas as categorias",
        help="Selecione uma ou mais categorias. Será exibido qualquer produto que corresponda a pelo menos uma delas.",
    )
    filtrados = [
        p for p in produtos
        if (
            not busca
            or busca in str(p[1] or "").casefold()
            or busca in str(p[2] or "").casefold()
        )
        and (
            not categorias_selecionadas
            or bool(set(categorias_do_produto(p[2])) & set(categorias_selecionadas))
        )
    ]

    ordem = st.selectbox(
        "Ordenar por",
        ["Nome", "Menor preço", "Maior preço"],
        key="catalogo_ordenacao",
    )
    if ordem == "Menor preço":
        filtrados.sort(key=preco_efetivo)
    elif ordem == "Maior preço":
        filtrados.sort(key=preco_efetivo, reverse=True)
    else:
        filtrados.sort(key=lambda p: str(p[1] or "").casefold())

    if filtrados:
        # Paginação do catálogo principal: 30 produtos por página.
        # A página volta à primeira quando a busca, as categorias ou a ordenação mudam.
        produtos_por_pagina = 30
        assinatura_filtros = (
            busca,
            tuple(sorted(categorias_selecionadas, key=str.casefold)),
            ordem,
        )
        if st.session_state.get("catalogo_assinatura_filtros") != assinatura_filtros:
            st.session_state["catalogo_assinatura_filtros"] = assinatura_filtros
            st.session_state["catalogo_pagina"] = 1

        total_produtos = len(filtrados)
        total_paginas = max(1, (total_produtos + produtos_por_pagina - 1) // produtos_por_pagina)
        pagina_atual = int(st.session_state.get("catalogo_pagina", 1))
        pagina_atual = max(1, min(pagina_atual, total_paginas))
        st.session_state["catalogo_pagina"] = pagina_atual

        inicio_pagina = (pagina_atual - 1) * produtos_por_pagina
        fim_pagina = min(inicio_pagina + produtos_por_pagina, total_produtos)
        produtos_pagina = filtrados[inicio_pagina:fim_pagina]

        def controles_paginacao(localizacao):
            anterior, indicador, proxima = st.columns([1, 1.5, 1], gap="small")
            with anterior:
                if st.button(
                    "← Anterior",
                    key=f"catalogo_paginacao_{localizacao}_anterior",
                    disabled=pagina_atual <= 1,
                    use_container_width=True,
                ):
                    st.session_state["catalogo_pagina"] = pagina_atual - 1
                    st.rerun()
            with indicador:
                st.markdown(
                    f'<div style="text-align:center;padding:.45rem 0;color:{COR_ESCURO};font-weight:700">'
                    f'Página {pagina_atual} de {total_paginas}</div>',
                    unsafe_allow_html=True,
                )
            with proxima:
                if st.button(
                    "Próxima →",
                    key=f"catalogo_paginacao_{localizacao}_proxima",
                    disabled=pagina_atual >= total_paginas,
                    use_container_width=True,
                ):
                    st.session_state["catalogo_pagina"] = pagina_atual + 1
                    st.rerun()

        st.caption(f"Exibindo produtos {inicio_pagina + 1}–{fim_pagina} de {total_produtos}")
        if total_paginas > 1:
            controles_paginacao("topo")
        with st.container(key="catalogo-grid"):
            # Cada grupo forma uma linha no desktop; no celular o CSS mostra dois cartões por linha.
            for inicio in range(0, len(produtos_pagina), 4):
                linha_produtos = produtos_pagina[inicio:inicio + 4]
                colunas = st.columns(4, gap="medium")
                for posicao, produto in enumerate(linha_produtos):
                    indice_produto = inicio_pagina + inicio + posicao
                    with colunas[posicao]:
                        renderizar_cartao_interativo(produto, indice_produto)
        if total_paginas > 1:
            controles_paginacao("base")
    else:
        st.info("Nenhum produto encontrado com esses filtros.")

st.markdown(
    f'<hr><div style="text-align:center;padding:1rem 0">'
    f'<img src="data:image/png;base64,{logo_base64}" alt="Logo Mabel Store" '
    f'style="width:100px;max-width:30%;height:auto">'
    f'<p style="color:{COR_PRINCIPAL};margin:.3rem 0">Feito com carinho 💜</p></div>',
    unsafe_allow_html=True,
)
