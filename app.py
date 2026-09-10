import streamlit as st
import requests

BACKEND_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="AUTOSAR HLD Document Analysis Assistant", layout="wide")

st.title("🚗 AUTOSAR HLD Document Analysis Assistant")
st.caption("Upload AUTOSAR High-Level Design documents and ask questions with cited answers.")

if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "last_question" not in st.session_state:
    st.session_state.last_question = None
if "last_doc" not in st.session_state:
    st.session_state.last_doc = None
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = None
if "role" not in st.session_state:
    st.session_state.role = None


if not st.session_state.logged_in:
    st.header("🔐 HLD Assistant Login")

    with st.form("login_form"):
        login_username = st.text_input("Username")
        login_password = st.text_input("Password", type="password")
        login_submitted = st.form_submit_button("Login", type="primary")

    if login_submitted:
        response = requests.post(
            f"{BACKEND_URL}/login",
            data={"username": login_username, "password": login_password}
        )
        result = response.json()
        if response.status_code == 200 and result.get("status") == "success":
            st.session_state.logged_in = True
            st.session_state.username = result["username"]
            st.session_state.role = result["role"]
            st.rerun()
        else:
            st.error(result.get("message", "Login failed."))

    with st.expander("Register new account"):
        with st.form("register_form"):
            register_username = st.text_input("New username")
            register_password = st.text_input("New password", type="password")
            register_role = st.selectbox(
                "Role",
                ["engineer", "reviewer", "admin"]
            )
            register_submitted = st.form_submit_button("Register")

        if register_submitted:
            response = requests.post(
                f"{BACKEND_URL}/register",
                data={
                    "username": register_username,
                    "password": register_password,
                    "role": register_role
                }
            )
            result = response.json()
            if response.status_code == 200 and result.get("status") == "success":
                st.success("Account registered. You can now log in.")
            else:
                st.error(result.get("message", "Registration failed."))

    st.stop()

# Sidebar: upload + status
with st.sidebar:
    st.write(f"Logged in as: `{st.session_state.username}` ({st.session_state.role})")
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.role = None
        st.rerun()

    st.divider()
    st.header("📄 Document Upload")
    uploaded_file = st.file_uploader("Upload an HLD PDF", type=["pdf"])

    if uploaded_file is not None:
        if st.button("Ingest Document"):
            with st.spinner("Processing document... extracting, chunking, embedding..."):
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
                response = requests.post(f"{BACKEND_URL}/upload", files=files)
                if response.status_code == 200:
                    result = response.json()
                    if result.get("status") == "success":
                        st.success(f"✅ {result['filename']} ingested")
                        st.write(f"Chunks created: {result['chunks_created']}")
                    else:
                        st.error(result.get("message", "Unknown error"))
                else:
                    st.error(f"Upload failed: {response.text}")

    st.divider()
    st.header("📊 Knowledge Base Status")
    try:
        status = requests.get(f"{BACKEND_URL}/status").json()
        st.metric("Total Chunks", status["total_chunks"])
        st.write("**Documents ingested:**")
        if status["documents"]:
            for doc in status["documents"]:
                st.write(f"- {doc}")
        else:
            st.write("_No documents yet_")
    except Exception as e:
        st.error("Backend not reachable. Is uvicorn running?")

# Main area: tabs for Q&A, Entity Extraction, Document Comparison, and Admin
tab_names = ["💬 Ask Questions", "🔍 Entity Extraction", "📊 Compare Documents"]
if st.session_state.role == "admin":
    tab_names.append("🔐 Admin: Audit & Reviews")

tabs = st.tabs(tab_names)
tab1, tab2, tab3 = tabs[:3]
tab4 = tabs[3] if len(tabs) == 4 else None

with tab1:
    st.header("💬 Ask a Question")

    question = st.text_input("Enter your question about the uploaded HLD document(s):")

    col1, col2 = st.columns([2, 2])
    with col1:
        top_k = st.slider("Sources to retrieve", 1, 10, 4)
    with col2:
        try:
            doc_options = ["All Documents"] + requests.get(f"{BACKEND_URL}/status").json().get("documents", [])
        except Exception:
            doc_options = ["All Documents"]
        selected_doc = st.selectbox("Search within", doc_options)

    if st.button("Ask", type="primary") and question:
        with st.spinner("Retrieving evidence and generating answer..."):
            response = requests.post(
                f"{BACKEND_URL}/query",
                data={
                    "question": question,
                    "top_k": top_k,
                    "source_filter": selected_doc,
                    "username": st.session_state.username
                }
            )
            if response.status_code == 200:
                st.session_state.last_result = response.json()
                st.session_state.last_question = question
                st.session_state.last_doc = selected_doc
            else:
                st.error(f"Query failed: {response.text}")
                st.session_state.last_result = None

    # Render the last answer (persists across button reruns like Approve/Reject)
    if st.session_state.last_result:
        result = st.session_state.last_result

        st.subheader("Answer")
        st.write(result["answer"])

        confidence = result.get("confidence", 0)
        if confidence >= 70:
            st.success(f"🟢 Confidence: {confidence}%")
        elif confidence >= 40:
            st.warning(f"🟡 Confidence: {confidence}%")
        else:
            st.error(f"🔴 Confidence: {confidence}% — answer may be unreliable")

        st.subheader("📌 Sources")
        for i, src in enumerate(result["sources"], 1):
            ocr_badge = " 🔍 (OCR)" if src.get("ocr_used") else ""
            with st.expander(f"Source {i}: {src['source']} — Page {src['page']}{ocr_badge}"):
                st.write(src["snippet"] + "...")

        if st.session_state.role in ("reviewer", "admin"):
            st.divider()
            st.write("**Review this answer:**")
            col_approve, col_reject = st.columns(2)
            with col_approve:
                if st.button("👍 Approve"):
                    review_resp = requests.post(f"{BACKEND_URL}/review", data={
                        "question": st.session_state.last_question,
                        "answer": result["answer"],
                        "decision": "approved",
                        "source_filter": st.session_state.last_doc,
                        "role": st.session_state.role,
                        "username": st.session_state.username
                    })
                    review_result = review_resp.json()
                    if review_result.get("status") == "success":
                        st.success("Marked as approved")
                    else:
                        st.error(review_result.get("message", "Could not submit review."))
            with col_reject:
                if st.button("👎 Reject"):
                    review_resp = requests.post(f"{BACKEND_URL}/review", data={
                        "question": st.session_state.last_question,
                        "answer": result["answer"],
                        "decision": "rejected",
                        "source_filter": st.session_state.last_doc,
                        "role": st.session_state.role,
                        "username": st.session_state.username
                    })
                    review_result = review_resp.json()
                    if review_result.get("status") == "success":
                        st.warning("Marked as rejected")
                    else:
                        st.error(review_result.get("message", "Could not submit review."))

with tab2:
    st.header("🔍 Architecture Entity Inventory")
    st.caption("Extract components, interfaces, ports, and signals mentioned in a document.")

    try:
        doc_list = requests.get(f"{BACKEND_URL}/status").json().get("documents", [])
    except Exception:
        doc_list = []

    if not doc_list:
        st.info("Upload a document first to extract entities.")
    else:
        entity_doc = st.selectbox("Select a document to analyze", doc_list, key="entity_doc_select")
        if st.button("Extract Entities"):
            with st.spinner("Analyzing document for components, interfaces, ports, and signals..."):
                resp = requests.post(f"{BACKEND_URL}/extract_entities", data={"source": entity_doc})
                if resp.status_code == 200:
                    result = resp.json()
                    if result.get("status") == "success":
                        entities = result["entities"]
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.write("**🧩 Components**")
                            st.write(entities.get("components", []) or "_None found_")
                            st.write("**🔌 Interfaces**")
                            st.write(entities.get("interfaces", []) or "_None found_")
                        with col_b:
                            st.write("**🔗 Ports**")
                            st.write(entities.get("ports", []) or "_None found_")
                            st.write("**📶 Signals**")
                            st.write(entities.get("signals", []) or "_None found_")
                    else:
                        st.error(result.get("message", "Extraction failed."))
                        if "raw" in result:
                            st.code(result["raw"])
                else:
                    st.error(f"Request failed: {resp.text}")

        st.divider()
        if st.button("📥 Export Document Data as JSON"):
            export_resp = requests.get(f"{BACKEND_URL}/export/{entity_doc}")
            if export_resp.status_code == 200:
                st.download_button(
                    "Download JSON",
                    data=export_resp.text,
                    file_name=f"{entity_doc}_export.json",
                    mime="application/json"
                )

with tab3:
    st.header("📊 Compare Documents")
    st.caption("Compare two ingested documents for shared entities, naming differences, and contradictions.")

    try:
        compare_docs = requests.get(f"{BACKEND_URL}/status").json().get("documents", [])
    except Exception:
        compare_docs = []

    if len(compare_docs) < 2:
        st.info("Upload at least two documents before comparing them.")
    else:
        col_a, col_b = st.columns(2)
        with col_a:
            document_a = st.selectbox("Document A", compare_docs, key="compare_document_a")
        with col_b:
            document_b = st.selectbox("Document B", compare_docs, key="compare_document_b")

        if st.button("Compare Documents", type="primary"):
            with st.spinner("Comparing documents..."):
                resp = requests.post(
                    f"{BACKEND_URL}/compare_documents",
                    data={"source_a": document_a, "source_b": document_b}
                )

            if resp.status_code == 200:
                result = resp.json()
                if result.get("status") == "success":
                    comparison = result.get("comparison", {})

                    st.subheader("🤝 Shared entities")
                    shared_entities = comparison.get("shared_entities", [])
                    if shared_entities:
                        for entity in shared_entities:
                            st.write(f"- {entity}")
                    else:
                        st.write("_None found_")

                    st.divider()
                    st.subheader("⚠️ Inconsistencies found")
                    inconsistencies = comparison.get("inconsistencies", [])
                    if inconsistencies:
                        for inconsistency in inconsistencies:
                            item = inconsistency.get("item", "Unknown item")
                            issue = inconsistency.get("issue", "Unspecified issue")
                            st.warning(f"**{item}** — {issue}")
                    else:
                        st.success("No inconsistencies found.")

                    st.divider()
                    st.subheader("📋 Present in only one document")
                    only_a, only_b = st.columns(2)
                    with only_a:
                        st.write(f"**Only in A — {document_a}**")
                        items_a = comparison.get("only_in_doc_a", [])
                        if items_a:
                            for item in items_a:
                                st.write(f"- {item}")
                        else:
                            st.write("_None found_")
                    with only_b:
                        st.write(f"**Only in B — {document_b}**")
                        items_b = comparison.get("only_in_doc_b", [])
                        if items_b:
                            for item in items_b:
                                st.write(f"- {item}")
                        else:
                            st.write("_None found_")
                else:
                    st.error(result.get("message", "Comparison failed."))
                    if result.get("raw"):
                        st.code(result["raw"])
            else:
                st.error(f"Request failed: {resp.text}")

if tab4 is not None:
    with tab4:
        st.header("🔐 Admin: Audit & Reviews")

        audit_resp = requests.get(
            f"{BACKEND_URL}/audit_log",
            params={"role": st.session_state.role}
        )
        audit_result = audit_resp.json()
        if audit_result.get("status") == "error":
            st.error(audit_result.get("message", "Could not load audit log."))
        else:
            st.subheader("📜 Query Audit Log")
            st.dataframe(audit_result.get("logs", []), use_container_width=True)

        st.divider()
        reviews_resp = requests.get(
            f"{BACKEND_URL}/reviews",
            params={"role": st.session_state.role}
        )
        reviews_result = reviews_resp.json()
        if reviews_result.get("status") == "error":
            st.error(reviews_result.get("message", "Could not load reviews."))
        else:
            st.subheader("📝 Answer Reviews")
            st.dataframe(reviews_result.get("reviews", []), use_container_width=True)

st.caption("AI-generated content must be reviewed by qualified engineers before use in compliance, design approval, or release decisions.")