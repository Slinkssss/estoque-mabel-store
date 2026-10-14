import base64
import html
import os
from urllib.parse import quote

import psycopg2
import streamlit as st

st.set_page_config(page_title="Mabel Store | Catálogo", page_icon="🛍️", layout="wide")
WHATSAPP_COMERCIAL = st.secrets.get("WHATSAPP_COMERCIAL", os.getenv("WHATSAPP_COMERCIAL", "5511999999999"))
# Configure uma conexão do banco com permissão SOMENTE DE LEITURA para este app público.
DB_URL = st.secrets.get("SUPABASE_READONLY_DB_URL", os.getenv("SUPABASE_READONLY_DB_URL", ""))

COR_PRINCIPAL = "#76518F"
COR_ESCURO = "#59366F"
COR_CLARA = "#EDE4F3"
COR_FUNDO = "#FCFAFD"
COR_TEXTO = "#30283A"

st.markdown(f"""
<style>
.stApp {{ background: {COR_FUNDO}; color: {COR_TEXTO}; }}
.block-container {{ max-width: 1240px; padding-top: 1.1rem; padding-bottom: 2rem; }}
.mabel-header {{ text-align:center; padding: 2.2rem 1.2rem 2rem; border:1px solid #E8DDEC; border-radius:24px; background:linear-gradient(135deg,#FFFFFF 0%,#F5EEF9 100%); box-shadow:0 12px 35px rgba(89,54,111,.08); }}
.mabel-logo {{ color:{COR_ESCURO}; font-family: Georgia,serif; font-size:2.8rem; font-weight:800; letter-spacing:.02em; margin:0; }}
.mabel-subtitle {{ color:{COR_PRINCIPAL}; margin-top:.45rem; font-size:1.08rem; }}
.mabel-promo {{ display:inline-block; background:#59366F; color:white; border-radius:99px; padding:.35rem .85rem; font-size:.78rem; font-weight:700; letter-spacing:.06em; margin-bottom:.75rem; }}
.availability {{ display:inline-block; background:#E7F5EC; color:#246B45; border-radius:99px; padding:.22rem .55rem; font-size:.72rem; font-weight:700; margin:.1rem 0 .45rem; }}
.old-price {{ color:#827787; text-decoration:line-through; font-size:.88rem; margin-top:.35rem; }}
.section-title {{ color:{COR_TEXTO}; font-size:1.55rem; font-weight:750; margin:1.8rem 0 .85rem; }}
.carousel {{ display:flex; gap:1rem; overflow-x:auto; padding:.2rem .1rem 1rem; scroll-snap-type:x mandatory; -webkit-overflow-scrolling:touch; }}
.carousel::-webkit-scrollbar {{ height:7px; }}
.carousel::-webkit-scrollbar-track {{ background:{COR_CLARA}; border-radius:20px; }}
.carousel::-webkit-scrollbar-thumb {{ background:{COR_PRINCIPAL}; border-radius:20px; }}
.product-card {{ flex:0 0 205px; width:205px; overflow:hidden; border:1px solid #E8DDEC; border-radius:15px; background:#fff; scroll-snap-align:start; box-shadow:0 4px 14px rgba(89,54,111,.07); }}
.product-image {{ width:100%; height:190px; object-fit:contain; background:#fff; display:block; }}
.product-image-placeholder {{ height:190px; display:flex; align-items:center; justify-content:center; background:{COR_CLARA}; color:{COR_PRINCIPAL}; font-size:2.6rem; }}
.product-info {{ padding:.85rem; }}
.product-name {{ color:{COR_TEXTO}; font-weight:700; font-size:.98rem; overflow-wrap:anywhere; }}
.product-category {{ display:inline-block; margin:.45rem 0; background:{COR_CLARA}; color:{COR_ESCURO}; border-radius:30px; padding:.2rem .55rem; font-size:.75rem; }}
.product-price {{ color:{COR_ESCURO}; font-weight:800; font-size:1.12rem; margin:.25rem 0 .65rem; }}
.buy-link {{ display:block; text-align:center; background:{COR_ESCURO}; color:white !important; text-decoration:none !important; border-radius:9px; padding:.65rem .5rem; font-weight:700; }}
.catalog-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:1rem; }}
.catalog-grid .product-card {{ width:auto; min-width:0; }}
@media(max-width:900px) {{ .catalog-grid {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} }}
@media(max-width:620px) {{ .block-container {{ padding-left:.7rem; padding-right:.7rem; }} .catalog-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); gap:.65rem; }} .catalog-grid .product-image,.catalog-grid .product-image-placeholder {{ height:145px; }} .catalog-grid .product-info {{ padding:.65rem; }} .product-card {{ flex-basis:165px; width:165px; }} .product-image,.product-image-placeholder {{ height:155px; }} .mabel-logo {{ font-size:1.9rem; }} }}
</style>
""", unsafe_allow_html=True)


def moeda(valor):
    return f"R$ {float(valor or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def abrir_conexao():
    if not DB_URL:
        raise RuntimeError("Configure SUPABASE_READONLY_DB_URL nos Secrets do Streamlit para conectar o catálogo ao banco.")
    return psycopg2.connect(DB_URL, sslmode="require", connect_timeout=10, application_name="MabelStoreCatalogoPublico")


def carregar_dados():
    """Carrega os produtos disponíveis e os destaques escolhidos no painel administrativo."""
    with abrir_conexao() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nome, categoria, preco, quantidade, foto, preco_promocional
                FROM public.produtos
                WHERE quantidade > 0
                ORDER BY nome
            """)
            produtos = cur.fetchall()

            # A tabela é criada pelo sistema administrativo. Se ainda não existir,
            # o restante do catálogo continua disponível e exibimos uma orientação.
            try:
                cur.execute("""
                    SELECT p.id, p.nome, p.categoria, p.preco, p.quantidade, p.foto, p.preco_promocional
                    FROM public.catalogo_destaques d
                    JOIN public.produtos p ON p.id = d.produto_id
                    WHERE p.quantidade > 0
                    ORDER BY d.ordem, p.nome
                """)
                destaques = cur.fetchall()
            except psycopg2.Error:
                conn.rollback()
                destaques = []
    return produtos, destaques


def imagem_html(foto, nome):
    if foto:
        if isinstance(foto, memoryview):
            foto = bytes(foto)
        codificada = base64.b64encode(foto).decode("ascii")
        return f'<img class="product-image" src="data:image/jpeg;base64,{codificada}" alt="{html.escape(str(nome))}">'
    return '<div class="product-image-placeholder">🛍️</div>'


def card_html(p):
    _pid, nome, categoria, preco, quantidade, foto, preco_promocional = p
    preco_normal = float(preco or 0)
    promo = float(preco_promocional or 0)
    em_promocao = 0 < promo < preco_normal
    preco_atual = promo if em_promocao else preco_normal
    nome_seguro = html.escape(str(nome or "Produto"))
    categoria_segura = html.escape(str(categoria or "Mabel Store"))
    mensagem = quote(f"Olá! Tenho interesse no produto: {nome or 'Produto'}. Preço: {moeda(preco_atual)}.")
    link = f"https://wa.me/{WHATSAPP_COMERCIAL}?text={mensagem}"
    return (f'<article class="product-card">{imagem_html(foto, nome)}'
            f'<div class="product-info"><div class="product-name">{nome_seguro}</div>'
            f'<span class="product-category">{categoria_segura}</span>'
            f'<div class="availability">✓ Disponível</div>'
            + (f'<div class="old-price">De {moeda(preco_normal)}</div><div class="product-price">Por {moeda(preco_atual)} <span style="font-size:.72rem;background:#EDE4F3;padding:.18rem .4rem;border-radius:20px">OFERTA</span></div>' if em_promocao else f'<div class="product-price">{moeda(preco_atual)}</div>') +
            f'<a class="buy-link" href="{link}" target="_blank" rel="noopener">Pedir pelo WhatsApp</a>'
            f'</div></article>')


def secao_carrossel(titulo, produtos_secao):
    if not produtos_secao:
        return ""
    cards = "".join(card_html(p) for p in produtos_secao)
    return f'<section><h2 class="section-title">{titulo}</h2><div class="carousel">{cards}</div></section>'

try:
    produtos, destaques = carregar_dados()
except Exception as erro:
    st.error("Não foi possível carregar o catálogo. Confira a conexão do banco e as tabelas necessárias.")
    st.caption(str(erro))
    st.stop()

st.markdown('<header class="mabel-header"><div class="mabel-promo">SUA VITRINE FAVORITA</div><h1 class="mabel-logo">Mabel Store</h1><p class="mabel-subtitle">Peças escolhidas com carinho para você 💜</p><p style="color:#655B6B;margin-top:.7rem">Explore nossos produtos, aproveite as ofertas e peça diretamente pelo WhatsApp.</p></header>', unsafe_allow_html=True)
kits = [p for p in produtos if str(p[2] or "").strip().casefold() == "kits"]
html_secoes = secao_carrossel("✨ Destaques", destaques) + secao_carrossel("🎁 Kits", kits)
if html_secoes:
    st.html(html_secoes)
else:
    st.info("Em breve teremos destaques e kits por aqui!")

st.markdown('<h2 class="section-title">Nosso catálogo</h2>', unsafe_allow_html=True)
if not produtos:
    st.info("Ainda não há produtos disponíveis.")
else:
    c1, c2, c3 = st.columns([2, 1, 1])
    busca = c1.text_input("Pesquisar produto", placeholder="Digite o nome do produto...").strip().casefold()
    categorias = sorted({str(p[2] or "Sem categoria") for p in produtos}, key=str.casefold)
    categoria = c2.selectbox("Categoria", ["Todas", *categorias])
    ordem = c3.selectbox("Ordenar por", ["Nome", "Menor preço", "Maior preço"])
    filtrados = [p for p in produtos if (not busca or busca in str(p[1] or "").casefold() or busca in str(p[2] or "").casefold()) and (categoria == "Todas" or str(p[2] or "Sem categoria") == categoria)]
    if ordem == "Menor preço":
        filtrados.sort(key=lambda p: float(p[3] or 0))
    elif ordem == "Maior preço":
        filtrados.sort(key=lambda p: float(p[3] or 0), reverse=True)
    else:
        filtrados.sort(key=lambda p: str(p[1]).casefold())
    if filtrados:
        st.caption(f"Exibindo {len(filtrados)} produto(s)")
        st.html('<div class="catalog-grid">' + ''.join(card_html(p) for p in filtrados) + '</div>')
    else:
        st.info("Nenhum produto encontrado com esses filtros.")

st.markdown(f'<hr><p style="text-align:center;color:{COR_PRINCIPAL};padding:1rem 0">Mabel Store · Feito com carinho 💜</p>', unsafe_allow_html=True)
