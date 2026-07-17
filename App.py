
import os
import uuid
import tempfile
import streamlit as st
import inventory_agent as backend

# Page setup

st.set_page_config(
    page_title="Inventory & Supplier Agent",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stApp { background: #0f172a; }
    .main .block-container { padding-top: 2rem; max-width: 1100px; }

    /* Make default Streamlit text readable on the dark background */
    .stApp, .stApp p, .stApp span, .stApp label, .stMarkdown, .stCaption {
        color: #e2e8f0;
    }
    section[data-testid="stSidebar"] { background: #111827; }
    section[data-testid="stSidebar"] * { color: #e2e8f0 !important; }

    .hero {
        background: linear-gradient(135deg, #4338ca 0%, #7c3aed 55%, #db2777 100%);
        padding: 2rem 2.2rem; border-radius: 18px; color: white;
        margin-bottom: 1.6rem;
    }
    .hero h1 { margin: 0; font-size: 1.9rem; color: white; }
    .hero p { margin: .35rem 0 0 0; opacity: .92; color: white; }

    .metric-card {
        background: #1e293b; border: 1px solid #334155; border-radius: 14px;
        padding: 1rem 1.2rem; box-shadow: 0 1px 4px rgba(0,0,0,.25);
    }
    .metric-card .label { color: #94a3b8; font-size: .8rem; font-weight: 600; text-transform: uppercase; }
    .metric-card .value { font-size: 1.8rem; font-weight: 700; margin-top: .15rem; color: #f1f5f9; }

    .badge { padding: .18rem .6rem; border-radius: 999px; font-size: .75rem; font-weight: 700; }
    .badge-ok { background: #14532d; color: #bbf7d0; }
    .badge-low { background: #78350f; color: #fde68a; }
    .badge-out { background: #7f1d1d; color: #fecaca; }

    .card {
        background: #1e293b; border: 1px solid #334155; border-radius: 14px;
        padding: 1.1rem 1.3rem; margin-bottom: .9rem; box-shadow: 0 1px 4px rgba(0,0,0,.25);
        color: #e2e8f0;
    }
    .card b { color: #f8fafc; }

    .supplier-card {
        background: #2e1065; border: 1px solid #4c1d95; border-radius: 14px;
        padding: 1rem 1.2rem; margin-bottom: .8rem; color: #ede9fe;
    }
    .supplier-card b { color: #f5f3ff; }
    .supplier-card a { color: #c4b5fd; }

    .email-box {
        background: #0b1220; border: 1px solid #334155; border-radius: 12px;
        padding: 1.1rem 1.3rem; font-family: 'Courier New', monospace;
        white-space: pre-wrap; font-size: .92rem;
        color: #d1fae5; line-height: 1.5;
    }

    /* Inputs, buttons, dataframes */
    .stTextInput input, .stNumberInput input, .stTextArea textarea {
        background: #1e293b !important; color: #f1f5f9 !important;
        border: 1px solid #334155 !important;
    }
    .stButton button { border-radius: 8px; }
    hr, [data-testid="stDivider"] { border-color: #334155 !important; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
    <h1>📦 Inventory & Supplier Agent</h1>
    <p>Smart stock tracking, AI product extraction, and automated supplier outreach — powered by LangGraph.</p>
</div>
""", unsafe_allow_html=True)


# Session state

defaults = {
    "thread_id": None,
    "stage": "idle",         
    "pending_extracted": None,
    "pending_user_input": None,
    "pending_input_type": None,
    "result": None,
    "config": None,
    "_send_result": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


def new_thread():
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.config = {"configurable": {"thread_id": st.session_state.thread_id}}
    st.session_state["_send_result"] = None


def reset_flow():
    st.session_state.stage = "idle"
    st.session_state.pending_extracted = None
    st.session_state.pending_user_input = None
    st.session_state.pending_input_type = None
    st.session_state.result = None
    st.session_state["_send_result"] = None

# Sidebar navigation

page = st.sidebar.radio("Navigate", ["🤖 Smart Agent", "📊 Dashboard", "➕ Add Product"], index=0)

with st.sidebar:
    st.markdown("---")
    st.caption("Environment check")
    env_map = {
        "Gemini (api_key)": os.getenv("api_key"),
        "Tavily (tavil)": os.getenv("tavil"),
        "Groq (GROQ_API_KEY)": os.getenv("GROQ_API_KEY"),
        "SMTP (SENDER_EMAIL)": os.getenv("SENDER_EMAIL"),
        "SMTP (SENDER_PASSWORD)": os.getenv("SENDER_PASSWORD"),
    }
    for name, val in env_map.items():
        st.markdown(f"{'✅' if val else '⭕'} {name}")

# DASHBOARD

if page == "📊 Dashboard":
    rows = backend.get_all_products()

    total = len(rows)
    low = sum(1 for r in rows if 0 < r[2] <= 10)
    out = sum(1 for r in rows if r[2] == 0)
    healthy = total - low - out

    c1, c2, c3, c4 = st.columns(4)
    for col, label, value in [
        (c1, "Total Products", total),
        (c2, "Healthy Stock", healthy),
        (c3, "Low Stock (≤10)", low),
        (c4, "Out of Stock", out),
    ]:
        with col:
            st.markdown(f"""<div class="metric-card"><div class="label">{label}</div>
            <div class="value">{value}</div></div>""", unsafe_allow_html=True)

    st.write("")
    st.subheader("Current Inventory")

    if not rows:
        st.info("No products yet — add one from the **➕ Add Product** page.")
    else:
        for name, size, qty, s_email, s_name in rows:
            if qty == 0:
                badge = '<span class="badge badge-out">OUT OF STOCK</span>'
            elif qty <= 10:
                badge = '<span class="badge badge-low">LOW STOCK</span>'
            else:
                badge = '<span class="badge badge-ok">IN STOCK</span>'

            colA, colB, colC, colD = st.columns([3, 2, 2, 1])
            with colA:
                st.markdown(f"<b style='color:#f1f5f9'>{name}</b><br><span style='color:#94a3b8'>{size or '—'}</span>", unsafe_allow_html=True)
            with colB:
                st.markdown(f"{badge}", unsafe_allow_html=True)
            with colC:
                st.markdown(f"<span style='color:#e2e8f0'><b>{qty}</b> units left</span>", unsafe_allow_html=True)
            with colD:
                if st.button("🗑️", key=f"del_{name}", help="Delete product"):
                    backend.delete_product(name)
                    st.rerun()
            st.markdown(f"<span style='color:#94a3b8;font-size:.85rem'>Supplier: {s_name or '—'} · {s_email or 'no email on file'}</span>", unsafe_allow_html=True)
            st.divider()

# ADD PRODUCT

elif page == "➕ Add Product":
    st.subheader("Add / Update a product")
    with st.form("manual_add_form"):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Product name*")
            size = st.text_input("Bottle / pack size*", placeholder="e.g. 100 g, 3 LTR")
            qty = st.number_input("Quantity in stock*", min_value=0, step=1, value=0)
        with c2:
            s_name = st.text_input("Supplier name (optional)")
            s_email = st.text_input("Supplier email (optional)")
        submitted = st.form_submit_button("Save product", type="primary")

    if submitted:
        if not name or not size:
            st.error("Product name and size are required.")
        else:
            backend.add_product(name.strip(), size.strip(), int(qty),
                                 s_email.strip() or None, s_name.strip() or None)
            st.success(f"Saved **{name}** ({size}) — {qty} units.")

# SMART AGENT

elif page == "🤖 Smart Agent":
    st.subheader("Ask the agent about a product")
    st.caption("Type a request in plain English, or upload a photo of a product/label. "
               "The agent checks stock, and if it's low or missing, it drafts a supplier "
               "email or searches the web for suppliers.")

    if st.session_state.stage == "idle":
        input_type = st.radio("Input type", ["Text", "Image"], horizontal=True)

        if input_type == "Text":
            query = st.text_input("Your request", placeholder="e.g. I need Dettol 100 g")
            run_clicked = st.button("🚀 Run Agent", type="primary", disabled=not query)
            image_path = None
        else:
            cam_col, up_col = st.columns(2)
            with cam_col:
                capture_mode = st.checkbox("📷 Use camera instead of upload", value=True)
            uploaded = None
            if capture_mode:
                uploaded = st.camera_input("Point your camera at the product / shelf label")
            else:
                uploaded = st.file_uploader("Upload product/label image", type=["jpg", "jpeg", "png"])

            run_clicked = st.button("🚀 Run Agent", type="primary", disabled=not uploaded)
            query = None
            image_path = None
            if uploaded:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                tmp.write(uploaded.getvalue())
                tmp.close()
                image_path = tmp.name

        if run_clicked:
            user_input = query if input_type == "Text" else image_path
            input_type_key = "text" if input_type == "Text" else "image"

            with st.spinner("Reading the request..."):
                try:
                    if input_type_key == "text":
                        extracted = backend.extract_from_text(user_input)
                    else:
                        extracted = backend.extract_from_image(user_input)
                except Exception as e:
                    st.error(f"Extraction failed: {e}")
                    st.stop()

            product_name = extracted.get("product_name")
            stock_info = backend.check_stock(product_name) if product_name else None

            st.session_state.pending_extracted = extracted
            st.session_state.pending_user_input = user_input
            st.session_state.pending_input_type = input_type_key

            if stock_info is None:
                st.session_state.stage = "needs_registration"
            else:
                new_thread()
                st.session_state.stage = "run_graph"
            st.rerun()

    # ---- Product not found -> register it (replaces the old input() prompt) ----
    elif st.session_state.stage == "needs_registration":
        extracted = st.session_state.pending_extracted
        st.warning(f"**{extracted.get('product_name')}** was not found in the database.")

        with st.form("register_form"):
            st.write("Register this product to continue:")
            c1, c2 = st.columns(2)
            with c1:
                size = st.text_input("Bottle / pack size", value=str(extracted.get("quantity") or ""))
                qty = st.number_input("Initial stock quantity", min_value=0, step=1, value=0)
            with c2:
                s_name = st.text_input("Supplier name (optional)")
                s_email = st.text_input("Supplier email (optional)")
            c_a, c_b = st.columns(2)
            register = c_a.form_submit_button("✅ Register & continue", type="primary")
            skip = c_b.form_submit_button("Skip (treat as 0 stock)")

        if register:
            backend.add_product(extracted.get("product_name"), size, int(qty),
                                 s_email or None, s_name or None)
            new_thread()
            st.session_state.stage = "run_graph"
            st.rerun()
        if skip:
            new_thread()
            st.session_state.stage = "run_graph"
            st.rerun()

        if st.button("← Cancel"):
            reset_flow()
            st.rerun()

    # ---- Invoke the agent graph fresh ----
    elif st.session_state.stage == "run_graph":
        initial_state = {
            "user_input": st.session_state.pending_user_input,
            "input_type": st.session_state.pending_input_type,
            "extracted_product": None,
            "stock_info": None,
            "supplier_recommendations": None,
            "supplier_email": None,
            "user_choice": None,
            "order_quantity": None,
            "final_message": "",
        }
        with st.spinner("Running the agent (checking stock, drafting email / searching suppliers)..."):
            try:
                result = backend.agent.invoke(initial_state, st.session_state.config)
            except Exception as e:
                st.error(f"Agent run failed: {e}")
                if st.button("Start over"):
                    reset_flow()
                    st.rerun()
                st.stop()

        st.session_state.result = result
        st.session_state.stage = "paused"
        st.rerun()

    # ---- Show results, mirror the old CLI satisfied / not-satisfied loop ----
    elif st.session_state.stage in ("paused", "done"):
        result = st.session_state.result
        state_snapshot = backend.agent.get_state(st.session_state.config).values
        extracted = state_snapshot.get("extracted_product", {}) or {}
        stock_info = state_snapshot.get("stock_info") or {}
        supplier_email = state_snapshot.get("supplier_email")
        supplier_rec = state_snapshot.get("supplier_recommendations")

        st.markdown(f"""<div class="card">
            <b>📦 {extracted.get('product_name','—')}</b><br>
            <span style="color:#94a3b8">Requested: {extracted.get('quantity','—')}</span><br>
            <span style="color:#94a3b8">Stock left: {stock_info.get('quantity_left','—') if stock_info else '—'}</span>
        </div>""", unsafe_allow_html=True)

        if supplier_email:
            st.markdown("#### ✉️ Drafted supplier email")
            st.markdown(f"<div class='email-box'>{state_snapshot.get('final_message','')}</div>", unsafe_allow_html=True)
        else:
            st.markdown("#### 📋 Result")
            st.markdown(state_snapshot.get("final_message", ""))
            if supplier_rec and supplier_rec.get("suppliers"):
                st.markdown("#### 🔎 Supplier options found online")
                for s in supplier_rec["suppliers"]:
                    st.markdown(f"""<div class="supplier-card">
                        <b>{s.get('name','—')}</b> · {s.get('source','—')}<br>
                        💰 {s.get('price','—')}  ·  ⭐ {s.get('reviews','—')}<br>
                        <a href="{s.get('url','#')}" target="_blank">{s.get('url','')}</a><br>
                        <span style="color:#c4b5fd">{s.get('reason_to_buy','')}</span>
                    </div>""", unsafe_allow_html=True)

        if st.session_state.stage == "paused":
            st.write("")
            colA, colB = st.columns(2)

            if colA.button("✅ Satisfied — finish", type="primary"):
                if supplier_email and state_snapshot.get("final_message"):
                    ok, msg = backend.send_email_to_supplier(
                        to_email=supplier_email,
                        email_body=state_snapshot.get("final_message"),
                        product_name=extracted.get("product_name", "Inventory Item"),
                    )
                    st.session_state["_send_result"] = (ok, msg)
                backend.agent.update_state(st.session_state.config, {"user_choice": "end"})
                backend.agent.invoke(None, st.session_state.config)
                st.session_state.stage = "done"
                st.rerun()

            with colB:
                if supplier_email:
                    new_qty = st.text_input("New order quantity", value="50", key="new_qty_input")
                    if st.button("🔁 Not satisfied — revise email"):
                        backend.agent.update_state(
                            st.session_state.config,
                            {"user_choice": "continue_search", "order_quantity": new_qty}
                        )
                        with st.spinner("Redrafting..."):
                            result = backend.agent.invoke(None, st.session_state.config)
                        st.session_state.result = result
                        st.rerun()
                else:
                    if st.button("🔁 Not satisfied — search more suppliers"):
                        backend.agent.update_state(st.session_state.config, {"user_choice": "continue_search"})
                        with st.spinner("Searching for more suppliers..."):
                            result = backend.agent.invoke(None, st.session_state.config)
                        st.session_state.result = result
                        st.rerun()

        else:
            send_result = st.session_state.get("_send_result")
            if send_result:
                ok, msg = send_result
                (st.success if ok else st.error)(msg)
            st.success("Session closed.")
            if st.button("🔄 Start a new request"):
                reset_flow()
                st.rerun()
