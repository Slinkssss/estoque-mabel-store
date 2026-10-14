import base64
import html
import os
import re
from urllib.parse import quote

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
.stApp {{ background: {COR_FUNDO}; color: {COR_TEXTO}; }}
.block-container {{ max-width: 1240px; padding-top: 1.1rem; padding-bottom: 2rem; }}
.mabel-header {{ text-align:center; padding:2.2rem 1.2rem 2rem; border:1px solid #E8DDEC; border-radius:24px; background:linear-gradient(135deg,#FFFFFF 0%,#F5EEF9 100%); box-shadow:0 12px 35px rgba(89,54,111,.08); }}
.mabel-logo-img {{ width:min(100%,300px); max-height:300px; object-fit:contain; display:block; margin:.1rem auto .5rem; }}
.mabel-subtitle {{ color:{COR_PRINCIPAL}; margin-top:.45rem; font-size:1.08rem; }}
.mabel-promo {{ display:inline-block; background:{COR_ESCURO}; color:white; border-radius:99px; padding:.35rem .85rem; font-size:.78rem; font-weight:700; letter-spacing:.06em; margin-bottom:.75rem; }}
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
.old-price {{ color:#827787; text-decoration:line-through; font-size:.88rem; margin-top:.35rem; }}
.availability {{ display:inline-block; background:#E7F5EC; color:#246B45; border-radius:99px; padding:.22rem .55rem; font-size:.72rem; font-weight:700; margin:.1rem 0 .45rem; }}
.out-of-stock {{ display:inline-block; background:#FCE8E8; color:#9B2525; border-radius:99px; padding:.22rem .55rem; font-size:.72rem; font-weight:700; margin:.1rem 0 .45rem; }}
.buy-link {{ display:block; text-align:center; background:{COR_ESCURO}; color:white !important; text-decoration:none !important; border-radius:9px; padding:.65rem .5rem; font-weight:700; }}
div[data-testid="stButton"] > button {{ border-radius:10px; border-color:#DCCCE8; color:{COR_ESCURO}; font-weight:650; }}
div[data-testid="stButton"] > button[kind="primary"] {{ background:{COR_ESCURO}; color:white; border-color:{COR_ESCURO}; }}
div[data-testid="stLinkButton"] a {{ border-radius:10px; }}
.cart-total {{ background:#F5EEF9; border:1px solid #E8DDEC; padding:1rem; border-radius:14px; color:{COR_ESCURO}; }}
@media(max-width:620px) {{ .block-container {{ padding-left:.7rem; padding-right:.7rem; }} .product-card {{ flex-basis:165px; width:165px; }} .product-image,.product-image-placeholder {{ height:155px; }} .mabel-logo-img {{ width:min(80%,230px); }} }}
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


def carregar_dados():
    """Carrega todos os produtos, inclusive os que estão sem estoque."""
    conn = abrir_conexao()
    try:
        with conn:
            with conn.cursor() as cur:
                # Sem filtro de quantidade: itens fora de estoque continuam visíveis.
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
        return produtos, destaques, promocoes
    finally:
        conn.close()


def categorias_do_produto(valor):
    partes = re.split(r"\s*[|,;]\s*", str(valor or "Sem categoria"))
    limpas = [parte.strip() for parte in partes if parte.strip()]
    return limpas or ["Sem categoria"]


def imagem_html(foto, nome):
    if foto:
        if isinstance(foto, memoryview):
            foto = bytes(foto)
        codificada = base64.b64encode(foto).decode("ascii")
        return (
            '<img class="product-image" '
            f'src="data:image/jpeg;base64,{codificada}" '
            f'alt="{html.escape(str(nome))}">'
        )
    return '<div class="product-image-placeholder">🛍️</div>'


def link_whatsapp(mensagem):
    numero = WHATSAPP_COMERCIAL
    texto = quote(mensagem, safe="")
    return f"https://wa.me/{numero}?text={texto}"


def card_html(produto):
    """Cartão HTML usado nos carrosséis; mantém o contato direto por WhatsApp."""
    _pid, nome, categoria, preco, quantidade, foto, preco_promocional = produto
    preco_normal = float(preco or 0)
    promocional = float(preco_promocional or 0)
    em_promocao = 0 < promocional < preco_normal
    preco_atual = promocional if em_promocao else preco_normal
    nome_seguro = html.escape(str(nome or "Produto"))
    categoria_segura = html.escape(" · ".join(categorias_do_produto(categoria)))

    if int(quantidade or 0) > 0:
        status_html = '<div class="availability">✓ Disponível</div>'
        rotulo_botao = "Pedir pelo WhatsApp"
    else:
        status_html = '<div class="out-of-stock">● Fora de estoque</div>'
        rotulo_botao = "Consultar reposição"

    mensagem = (
        f"Olá! Tenho interesse no produto: {nome or 'Produto'}. "
        f"Preço informado: {moeda(preco_atual)}. "
        + ("Vi que está fora de estoque e gostaria de consultar a reposição." if int(quantidade or 0) <= 0 else "")
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
        f'{status_html}{preco_html}'
        f'<a class="buy-link" href="{link}" target="_blank" rel="noopener">'
        f'{rotulo_botao}</a></div></article>'
    )


def secao_carrossel(titulo, produtos_secao):
    if not produtos_secao:
        return ""
    cards = "".join(card_html(p) for p in produtos_secao)
    return (
        f'<section><h2 class="section-title">{titulo}</h2>'
        f'<div class="carousel">{cards}</div></section>'
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
            if isinstance(foto, memoryview):
                foto = bytes(foto)
            st.image(foto, use_container_width=True)
        else:
            st.markdown(
                f'<div class="product-image-placeholder">🛍️</div>',
                unsafe_allow_html=True,
            )

        st.markdown(f"**{html.escape(str(nome or 'Produto'))}**", unsafe_allow_html=True)
        st.caption(" · ".join(categorias_do_produto(categoria)))

        if estoque > 0:
            st.markdown('<span class="availability">✓ Em estoque</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="out-of-stock">● Fora de estoque</span>', unsafe_allow_html=True)

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
                f"que aparece como fora de estoque no catálogo."
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
                    st.markdown('<span class="out-of-stock">Fora de estoque</span>', unsafe_allow_html=True)
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
                "Revise o carrinho: há produto fora de estoque ou quantidade maior que o estoque disponível. "
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

# Carrosséis configurados no painel administrativo. Os produtos fora de estoque
# também são exibidos, com o estado claramente indicado.
kits = [p for p in produtos if str(p[2] or "").strip().casefold() == "kits"]
html_secoes = (
    secao_carrossel("✨ Destaques", destaques)
    + secao_carrossel("🔥 Promoções", promocoes_selecionadas)
    + secao_carrossel("🎁 Kits", kits)
)
if html_secoes:
    st.html(html_secoes)

st.markdown('<h2 class="section-title">Nosso catálogo</h2>', unsafe_allow_html=True)
if not produtos:
    st.info("Ainda não há produtos cadastrados.")
else:
    c1, c2, c3 = st.columns([2, 1, 1])
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
    filtro_estoque = c3.selectbox(
        "Disponibilidade",
        ["Todos os produtos", "Em estoque", "Fora de estoque"],
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
        and (
            filtro_estoque == "Todos os produtos"
            or (filtro_estoque == "Em estoque" and int(p[4] or 0) > 0)
            or (filtro_estoque == "Fora de estoque" and int(p[4] or 0) <= 0)
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
        colunas = st.columns(4)
        for indice, produto in enumerate(filtrados):
            with colunas[indice % len(colunas)]:
                renderizar_cartao_interativo(produto, indice)
    else:
        st.info("Nenhum produto encontrado com esses filtros.")

st.markdown(
    f'<hr><div style="text-align:center;padding:1rem 0">'
    f'<img src="data:image/png;base64,{logo_base64}" alt="Logo Mabel Store" '
    f'style="width:100px;max-width:30%;height:auto">'
    f'<p style="color:{COR_PRINCIPAL};margin:.3rem 0">Feito com carinho 💜</p></div>',
    unsafe_allow_html=True,
)
