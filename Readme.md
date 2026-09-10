# AUTOSAR HLD Document Analysis Assistant

An AI-powered assistant that helps automotive engineers extract, search, and validate architectural knowledge from AUTOSAR High-Level Design (HLD) documents — built as an implementation of **Case Study 1** from the *Automotive Engineering AI: Standard Project Case Study Document*.

## What it does

Upload an AUTOSAR HLD PDF and:
- Ask natural-language questions and get **cited, grounded answers** (RAG pipeline)
- See a **confidence score** for every answer
- Filter questions to a **specific document** when multiple are loaded
- Automatically extract a structured inventory of **components, interfaces, ports, and signals**
- **Compare two documents** and get flagged inconsistencies (e.g., renamed interfaces, contradicting descriptions)
- **Export** any document's data as structured JSON
- Review AI answers with an **Approve/Reject** workflow (role-gated)
- Full **Role-Based Access Control** (engineer / reviewer / admin)
- Automatic **OCR fallback** for scanned/image-based PDF pages
- Every query and review decision is recorded in a **SQLite audit log**

## Architecture

| Layer | Technology | Doc reference |
|---|---|---|
| Frontend | Streamlit | "Streamlit for rapid engineering interfaces" |
| Backend API | FastAPI | "FastAPI as the preferred service layer" |
| LLM | Groq (Llama-family model, `openai/gpt-oss-20b`) | "Any suitable enterprise-approved or open-source LLM" |
| Embeddings | Sentence Transformers (`all-MiniLM-L6-v2`) | "BGE, E5, Sentence Transformers, or equivalent" |
| Vector store | FAISS | "FAISS or ChromaDB... for pilots" |
| OCR | Tesseract | "OCR for scanned pages" |
| Structured storage | SQLite | "SQLite for pilot" |
| Deployment | Docker | "Docker; optional Kubernetes" |

## Feature-to-requirement mapping

| Case Study 1 Requirement | Implementation |
|---|---|
| PDF ingestion | PyMuPDF text extraction |
| OCR for scanned pages | Tesseract fallback when page text < 20 chars |
| Component/interface/signal extraction | `/extract_entities` endpoint, LLM-based structured extraction |
| Natural language search with citations | `/query` endpoint, RAG with page-level citations |
| Document comparison / inconsistency reporting | `/compare_documents` endpoint |
| Export of structured findings | `/export/{source}` endpoint, JSON download |
| Confidence indicators | FAISS distance → confidence score, shown in UI |
| Audit logs | SQLite `query_log` table, timestamped |
| Human review and approval | `/review` endpoint, Approve/Reject buttons (reviewer/admin only) |
| Role-based access control | SQLite `users` table, SHA-256 auth, enforced per-endpoint |
| Deployment | `Dockerfile`, verified running end-to-end |

## Roles

| Role | Permissions |
|---|---|
| `engineer` | Upload, ask questions, extract entities, compare documents, export data |
| `reviewer` | All engineer permissions + Approve/Reject AI answers |
| `admin` | All reviewer permissions + view full audit log and review history |

Role checks are enforced **server-side** (not just hidden in the UI) — verified via direct API calls bypassing the frontend.

## Running locally

```bash
# 1. Set up environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Add your Groq API key to .env
echo "GROQ_API_KEY=your_key_here" > .env

# 3. Run backend
uvicorn backend:app --reload

# 4. Run frontend (separate terminal)
streamlit run app.py
```

## Running with Docker

```bash
docker build -t hld-assistant .
docker run -p 8000:8000 -p 8501:8501 --env-file .env hld-assistant
```

Visit `http://localhost:8501`.

## Known simplifications (pilot-scope decisions)

- **PostgreSQL**: not used — the reference doc explicitly allows SQLite for pilot scale.
- **Neo4j graph store**: not implemented — the doc lists this as a Phase 2+ "scale" feature, not a pilot requirement.
- **Password hashing**: uses SHA-256 for local demonstration purposes; a production system would use a stronger scheme (e.g., bcrypt/argon2) and a managed identity provider.
- **Single-container deployment**: backend and frontend run in one container for simplicity; a production setup would split these into separate services via `docker-compose`.

## Tech stack summary

Python · FastAPI · Streamlit · FAISS · Sentence Transformers · Tesseract OCR · Groq (Llama) · SQLite · Docker