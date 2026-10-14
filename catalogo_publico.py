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
:root {{
    --mabel-purple: {COR_PRINCIPAL};
    --mabel-purple-dark: {COR_ESCURO};
    --mabel-lilac: {COR_CLARA};
    --mabel-border: #E8DDEC;
}}
.stApp {{ background: {COR_FUNDO}; color: {COR_TEXTO}; }}
.block-container {{ max-width: 1240px; padding-top: 1.15rem; padding-bottom: 2.5rem; }}

/* Cabeçalho */
.mabel-header {{
    text-align:center; padding:2rem 1.25rem 1.8rem;
    border:1px solid var(--mabel-border); border-radius:26px;
    background:linear-gradient(135deg,#FFFFFF 0%,#F5EEF9 100%);
    box-shadow:0 12px 32px rgba(89,54,111,.08);
}}
.mabel-logo-img {{ width:min(100%,280px); max-height:270px; object-fit:contain; display:block; margin:.1rem auto .5rem; }}
.mabel-subtitle {{ color:{COR_PRINCIPAL}; margin-top:.45rem; font-size:1.08rem; }}
.mabel-promo {{ display:inline-block; background:{COR_ESCURO}; color:white; border-radius:99px; padding:.38rem .9rem; font-size:.76rem; font-weight:750; letter-spacing:.07em; margin-bottom:.75rem; }}
.section-title {{ color:{COR_TEXTO}; font-size:1.55rem; font-weight:780; margin:1.8rem 0 .85rem; letter-spacing:-.02em; }}

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
.product-name {{ color:{COR_TEXTO}; font-weight:750; font-size:1rem; line-height:1.35; min-height:2.7em; overflow-wrap:anywhere; }}
.product-category {{ display:inline-block; width:fit-content; max-width:100%; margin:.55rem 0; background:{COR_CLARA}; color:{COR_ESCURO}; border-radius:30px; padding:.24rem .62rem; font-size:.74rem; overflow-wrap:anywhere; }}
.product-price {{ color:{COR_ESCURO}; font-weight:800; font-size:1.18rem; margin:.35rem 0 .7rem; }}
.old-price {{ color:#827787; text-decoration:line-through; font-size:.86rem; margin-top:.35rem; }}
.stock-quantity {{ display:inline-block; width:fit-content; max-width:100%; color:#766A7D; font-size:.78rem; line-height:1.35; font-weight:600; margin:.05rem 0 .5rem; white-space:normal; overflow-wrap:anywhere; }}
.buy-link {{ display:block; margin-top:auto; text-align:center; background:#E3D3F0; color:{COR_ESCURO} !important; text-decoration:none !important; border:1px solid #D5BFE7; border-radius:11px; padding:.72rem .6rem; font-weight:750; transition:background .18s ease,transform .18s ease; }}
.buy-link:hover {{ background:#D7C0E8; transform:translateY(-1px); }}

/* Cartões do catálogo principal: mesmo desenho dos cartões de Destaques.
   A foto ocupa um quadrado branco no topo; nome, categoria, quantidade,
   preço e ações ficam alinhados na área inferior do mesmo cartão. */
.st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"] {{
    min-height:100%; width:100%; min-width:0; box-sizing:border-box;
    border:1px solid var(--mabel-border) !important;
    border-radius:18px !important; background:#FFFFFF !important;
    padding:.6rem !important; box-shadow:0 5px 18px rgba(89,54,111,.07);
    display:flex; flex-direction:column; overflow:hidden;
    transition:box-shadow .18s ease,border-color .18s ease;
}}
/* A área branca cobre o cartão inteiro: foto, informações, preço e botão. */
.st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"] > div {{
    min-width:0; width:100%; flex:1; display:flex; flex-direction:column;
    box-sizing:border-box; background:#FFFFFF !important;
    gap:.35rem !important;
}}
.st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stElementContainer"],
.st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stMarkdownContainer"] {{
    background:#FFFFFF !important;
}}
.st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"]:hover {{
    border-color:#D8C3E7 !important; box-shadow:0 8px 23px rgba(89,54,111,.11);
}}
.st-key-catalogo-grid [data-testid="stImage"] {{
    width:100% !important; aspect-ratio:1 / 1; height:auto !important;
    min-width:0; max-width:100%; margin:0 !important;
    display:flex !important; align-items:center; justify-content:center;
    overflow:hidden; background:#FFFFFF !important; border:1px solid #F0EAF4;
    border-radius:17px 17px 13px 13px; padding:9px; box-sizing:border-box;
}}
.st-key-catalogo-grid [data-testid="stImage"] img {{
    display:block; height:100% !important; width:100% !important; max-width:100% !important;
    aspect-ratio:1 / 1; object-fit:contain !important; background:#FFFFFF; border-radius:9px;
    padding:3px; box-sizing:border-box;
}}
.st-key-catalogo-grid [data-testid="stMarkdownContainer"] {{
    width:100%; max-width:100%; min-width:0; padding:0 .3rem; box-sizing:border-box;
    overflow-wrap:anywhere; background:#FFFFFF !important;
}}
.st-key-catalogo-grid .product-image-placeholder {{ aspect-ratio:1 / 1; width:100%; height:auto; background:#FFFFFF; border:1px solid #F0EAF4; border-radius:13px; box-sizing:border-box; }}
.st-key-catalogo-grid .catalog-product-name {{ color:{COR_TEXTO}; font-size:1rem; font-weight:750; line-height:1.35; min-height:2.7em; overflow-wrap:anywhere; margin:.25rem 0 .4rem; }}
.st-key-catalogo-grid .catalog-category {{ display:inline-block; width:fit-content; max-width:100%; color:{COR_ESCURO}; background:{COR_CLARA}; font-size:.74rem; line-height:1.3; min-height:0; margin:.2rem 0 .5rem; padding:.24rem .62rem; border-radius:30px; overflow-wrap:anywhere; }}
.st-key-catalogo-grid .catalog-stock-quantity {{ display:block; color:#766A7D; font-size:.78rem; line-height:1.35; font-weight:600; margin:.05rem 0 .5rem; overflow-wrap:anywhere; }}
.st-key-catalogo-grid [data-testid="stButton"],
.st-key-catalogo-grid [data-testid="stLinkButton"] {{
    width:100%; max-width:100%; min-width:0; padding:0 .3rem; box-sizing:border-box;
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
    font-weight:700 !important; box-shadow:none !important;
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
    .mabel-header {{ padding:1.35rem .75rem; border-radius:18px; }}
    .mabel-logo-img {{ width:min(80%,210px); }}
    .section-title {{ font-size:1.25rem; margin:1.35rem 0 .7rem; }}

    /* O catálogo principal vira uma grade real de 2 colunas no celular.
       Não usa rolagem horizontal nem transforma os produtos em carrossel. */
    .st-key-catalogo-grid {{ width:100% !important; max-width:100% !important; min-width:0 !important; }}
    .st-key-catalogo-grid [data-testid="stHorizontalBlock"] {{
        display:grid !important;
        grid-template-columns:repeat(2,minmax(0,1fr)) !important;
        align-items:stretch !important;
        column-gap:.6rem !important; row-gap:.7rem !important;
        width:100% !important; max-width:100% !important; min-width:0 !important;
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
        padding:.42rem !important; border-radius:14px !important;
        background:#FFFFFF !important; box-shadow:0 4px 14px rgba(89,54,111,.07);
    }}
    .st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"] > div {{
        min-width:0; width:100%; box-sizing:border-box;
        gap:.28rem !important; background:#FFFFFF !important;
    }}
    .st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stElementContainer"],
    .st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stMarkdownContainer"] {{
        background:#FFFFFF !important;
    }}
    .st-key-catalogo-grid [data-testid="stMarkdownContainer"] {{
        padding:0 .3rem; box-sizing:border-box; background:#FFFFFF !important;
    }}
    .st-key-catalogo-grid [data-testid="stButton"],
    .st-key-catalogo-grid [data-testid="stLinkButton"] {{
        padding:0 .3rem; box-sizing:border-box; background:#FFFFFF !important;
    }}
    .st-key-catalogo-grid [data-testid="stImage"] {{
        display:flex !important; width:100% !important; max-width:100% !important;
        min-width:0 !important; aspect-ratio:1 / 1; padding:6px; border-radius:13px 13px 11px 11px;
        box-sizing:border-box !important;
    }}
    .st-key-catalogo-grid [data-testid="stImage"] img {{
        display:block; height:100% !important; width:100% !important;
        max-width:100% !important; object-fit:contain !important;
    }}
    .st-key-catalogo-grid .catalog-product-name {{
        font-size:.88rem !important; line-height:1.3 !important;
        min-height:2.6em; overflow-wrap:anywhere; word-break:normal;
        margin:.2rem 0 .35rem;
    }}
    .st-key-catalogo-grid .catalog-category {{
        font-size:.68rem !important; line-height:1.25 !important;
        overflow-wrap:anywhere; min-height:0; padding:.22rem .42rem;
    }}
    .st-key-catalogo-grid .product-price {{ font-size:1rem !important; overflow-wrap:anywhere; }}
    .st-key-catalogo-grid .old-price {{ font-size:.75rem !important; }}
    .st-key-catalogo-grid [data-testid="stButton"] > button,
    .st-key-catalogo-grid [data-testid="stLinkButton"] > a {{
        display:flex !important; align-items:center !important; justify-content:center !important;
        width:100% !important; max-width:100% !important; min-width:0 !important;
        min-height:42px !important; height:auto !important;
        padding:.42rem .28rem !important; font-size:.72rem !important;
        line-height:1.2 !important; white-space:normal !important;
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
        column-gap:.6rem !important; row-gap:.7rem !important;
        width:100% !important; max-width:100% !important; min-width:0 !important;
    }}
    .product-card {{ width:100%; min-width:0; border-radius:14px; }}
    .product-image,.product-image-placeholder {{ width:100%; height:auto; aspect-ratio:1 / 1; padding:6px; border-radius:11px; }}
    .product-info {{ padding:.6rem; min-width:0; }}
    .product-name {{ font-size:.88rem; min-height:2.6em; overflow-wrap:anywhere; }}
    .product-category {{ font-size:.68rem; padding:.22rem .42rem; max-width:100%; }}
    .stock-quantity,.catalog-stock-quantity {{ font-size:.68rem; line-height:1.3; margin:.05rem 0 .42rem; }}
    /* Menos efeitos/retrabalho no celular e imagens sempre contidas no cartão. */
    .product-card,.st-key-catalogo-grid [data-testid="stVerticalBlockBorderWrapper"] {{
        transform:none !important; transition:none !important;
    }}
    .product-image,.product-image-placeholder {{ max-width:100%; }}
    .st-key-catalogo-grid [data-testid="stImage"] img {{ content-visibility:auto; }}
    .st-key-catalogo-grid .product-image-placeholder {{ width:100%; height:auto; aspect-ratio:1 / 1; border-radius:11px; }}
    .product-price {{ font-size:1rem; overflow-wrap:anywhere; }}
    .buy-link {{ padding:.55rem .3rem; font-size:.72rem; line-height:1.2; overflow-wrap:anywhere; }}
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
                    SELECT id, nome, categoria, preco,
                           quantidade, foto, preco_promocional
                    FROM public.produtos
                    ORDER BY nome
                """)
                produtos = cur.fetchall()

                try:
                    cur.execute("""
                        SELECT p.id, p.nome, p.categoria, p.preco,
                               p.quantidade, p.foto, p.preco_promocional
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
                               p.quantidade, p.foto, p.preco_promocional
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
    _pid, nome, categoria, preco, quantidade, foto, preco_promocional = produto
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
        f'{quantidade_html}{preco_html}'
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
    pid, nome, categoria, preco, quantidade, foto, preco_promocional = produto
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
    produtos_por_id = {str(p[0]): p for p in produtos}
    carrinho = st.session_state.setdefault("mabel_store_carrinho", {})

    # Retira do carrinho itens que foram excluídos do estoque pelo administrador.
    for pid_chave in list(carrinho.keys()):
        if pid_chave not in produtos_por_id:
            carrinho.pop(pid_chave, None)

    quantidade_itens = sum(int(q) for q in carrinho.values())
    st.markdown(
        f'<h2 class="section-title">🛒 Meu carrinho <span '
        f'style="font-size:1rem;color:{COR_PRINCIPAL}">({quantidade_itens} item(ns))</span></h2>',
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        if not carrinho:
            st.info("Seu carrinho está vazio. Adicione os produtos que deseja pedir.")
            return

        total = 0.0
        tem_indisponivel = False
        tem_quantidade_acima_estoque = False

        for pid_chave in list(carrinho.keys()):
            produto = produtos_por_id.get(pid_chave)
            if not produto:
                continue

            pid, nome, categoria, preco, quantidade, foto, preco_promocional = produto
            qtd = int(carrinho.get(pid_chave, 1))
            estoque = max(0, int(quantidade or 0))
            preco_atual = preco_efetivo(produto)
            subtotal = preco_atual * qtd
            total += subtotal

            linha = st.columns([4, 1, 1, 1, 1])
            with linha[0]:
                st.markdown(f"**{html.escape(str(nome or 'Produto'))}**", unsafe_allow_html=True)
                st.caption(f"{moeda(preco_atual)} cada · Subtotal: {moeda(subtotal)}")
                if estoque <= 0:
                    st.caption("Quantidade disponível: 0")
                    tem_indisponivel = True
                elif qtd > estoque:
                    st.warning(f"Estoque atual: {estoque}. Reduza a quantidade.")
                    tem_quantidade_acima_estoque = True
            with linha[1]:
                st.markdown(f"**Qtd. {qtd}**")
            with linha[2]:
                if st.button("−", key=f"cart_menos_{pid_chave}", disabled=qtd <= 1, help="Diminuir quantidade"):
                    carrinho[pid_chave] = qtd - 1
                    st.rerun()
            with linha[3]:
                if st.button("+", key=f"cart_mais_{pid_chave}", disabled=(estoque <= 0 or qtd >= estoque), help="Aumentar quantidade"):
                    carrinho[pid_chave] = qtd + 1
                    st.rerun()
            with linha[4]:
                if st.button("🗑️", key=f"cart_remover_{pid_chave}", help="Remover do carrinho"):
                    carrinho.pop(pid_chave, None)
                    st.rerun()

        st.markdown(
            f'<div class="cart-total"><strong>Total estimado do pedido: '
            f'{moeda(total)}</strong></div>',
            unsafe_allow_html=True,
        )
        st.caption("O pedido será enviado como mensagem pelo WhatsApp; não há pagamento dentro do site.")

        if tem_indisponivel or tem_quantidade_acima_estoque:
            st.warning(
                "Revise o carrinho: há produto sem unidades disponíveis ou quantidade maior que o saldo atual. "
                "Remova o item indisponível ou reduza a quantidade para enviar o pedido."
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
                "📲 Enviar pedido completo pelo WhatsApp",
                link_whatsapp("\n".join(linhas_pedido)),
                type="primary",
                use_container_width=True,
            )

        if st.button("🧹 Esvaziar carrinho", key="esvaziar_carrinho", use_container_width=True):
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
    f'<header class="mabel-header"><div class="mabel-promo">SUA VITRINE FAVORITA</div>'
    f'<img class="mabel-logo-img" src="data:image/png;base64,{logo_base64}" alt="Logo Mabel Store">'
    f'<p class="mabel-subtitle">Peças escolhidas com carinho para você 💜</p>'
    f'<p style="color:#655B6B;margin-top:.7rem">Explore nossos produtos, aproveite as ofertas '
    f'e peça diretamente pelo WhatsApp.</p></header>',
    unsafe_allow_html=True,
)

# Carrinho interativo: o conteúdo fica guardado na sessão do visitante.
mostrar_carrinho(produtos)

# Produtos marcados no painel aparecem em grades, com a quantidade disponível.
kits = [p for p in produtos if str(p[2] or "").strip().casefold() == "kits"]
html_secoes = (
    secao_grade("✨ Destaques", destaques)
    + secao_grade("🔥 Promoções", promocoes_selecionadas)
    + secao_grade("🎁 Kits", kits)
)
if html_secoes:
    st.html(html_secoes)

st.markdown('<h2 class="section-title">Nosso catálogo</h2>', unsafe_allow_html=True)
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
        st.caption(f"Exibindo {len(filtrados)} produto(s)")
        with st.container(key="catalogo-grid"):
            # Cada grupo de quatro cartões forma uma linha no desktop. No celular,
            # o CSS reorganiza cada grupo em duas linhas de dois, sem trocar a ordem.
            for inicio in range(0, len(filtrados), 4):
                linha_produtos = filtrados[inicio:inicio + 4]
                colunas = st.columns(4, gap="medium")
                for posicao, produto in enumerate(linha_produtos):
                    with colunas[posicao]:
                        renderizar_cartao_interativo(produto, inicio + posicao)
    else:
        st.info("Nenhum produto encontrado com esses filtros.")

st.markdown(
    f'<hr><div style="text-align:center;padding:1rem 0">'
    f'<img src="data:image/png;base64,{logo_base64}" alt="Logo Mabel Store" '
    f'style="width:100px;max-width:30%;height:auto">'
    f'<p style="color:{COR_PRINCIPAL};margin:.3rem 0">Feito com carinho 💜</p></div>',
    unsafe_allow_html=True,
)
