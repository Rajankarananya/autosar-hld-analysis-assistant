# AUTOSAR HLD Document Analysis Assistant

An AI-powered assistant for extracting, searching, comparing, and reviewing architectural knowledge from AUTOSAR High-Level Design documents. The project implements the main capabilities described in Case Study 1 of the *Automotive Engineering AI: Standard Project Case Study Document*.

## Screenshots

### Login and registration

![HLD Assistant login screen](docs/Screenshot%202026-09-10%20at%202.21.05 PM.png)

The application starts behind a local login gate. Users can register as engineers, reviewers, or administrators.

### Admin audit and review dashboard

![Admin audit and reviews dashboard](docs/Screenshot%202026-09-10%20at%202.11.23 PM.png)

Administrators can inspect query and review tables, query volume by document, average confidence, and approved versus rejected review counts.

## Capabilities

- Upload PDF-based AUTOSAR HLD documents with PyMuPDF text extraction.
- Fall back to Tesseract OCR for scanned or image-heavy pages.
- Ask natural-language questions using FAISS retrieval and page-cited LLM answers.
- Extract components, interfaces, ports, and signals as structured JSON.
- Compare two documents for shared entities, naming inconsistencies, contradictions, and one-sided entities.
- Export project-scoped document chunks as JSON.
- Organize ingested documents into separate project collections.
- Authenticate local users with engineer, reviewer, and admin roles.
- Record queries and review decisions in SQLite audit tables.
- Display admin-only audit, confidence, and review analytics.
- Run the backend and Streamlit frontend locally or in one Docker container.

## Architecture

```mermaid

flowchart LR
	User[Engineer / Reviewer / Admin] --> UI[Streamlit UI\nLogin, projects, Q&A, extraction, comparison]
	UI -->|HTTP| API[FastAPI API]
	API --> Auth[SQLite users\nroles and permissions]
	API --> Projects[SQLite projects\nproject catalog]
	API --> Chunks[chunks.pkl\ntext and project metadata]
	API --> FAISS[FAISS index\nvector embeddings]
	API --> Embedder[Sentence Transformers\nall-MiniLM-L6-v2]
	API --> OCR[Tesseract OCR\nscanned PDF fallback]
	API --> LLM[Groq\nopenai/gpt-oss-20b]
	API --> Audit[SQLite audit.db\nqueries and reviews]
	UI --> Charts[Streamlit charts\nadmin only]
	Docker[Docker container] --> API
	Docker --> UI
```

### Project isolation

Every ingested chunk carries a `project` value. Existing data is migrated to the `default` project. The active project selected in the sidebar is passed to upload, status, query, entity extraction, comparison, and export operations. A document stored in one project is not returned by another project's status or document operations.

## Technology stack

| Layer | Technology |
|---|---|
| Frontend | Streamlit |
| API | FastAPI |
| LLM | Groq, `openai/gpt-oss-20b` |
| Embeddings | Sentence Transformers, `all-MiniLM-L6-v2` |
| Vector search | FAISS |
| PDF extraction | PyMuPDF |
| OCR | Tesseract and pytesseract |
| Structured storage | SQLite |
| Analytics | pandas and Streamlit charts |
| Deployment | Docker |

## Feature-to-requirement mapping

| Requirement | Implementation |
|---|---|
| PDF ingestion | `/upload` with PyMuPDF extraction and project tagging |
| OCR for scanned pages | Tesseract fallback when extracted page text is very short |
| Natural-language search | `/query` with FAISS retrieval and cited answers |
| Entity inventory | `/extract_entities` with structured LLM JSON |
| Revision comparison | `/compare_documents` with shared entities and inconsistency reporting |
| Project collections | `/projects`, project-scoped chunks, and active sidebar project |
| Data export | `/export/{source}` with project filtering |
| Confidence indicators | Retrieval distance converted to a confidence score |
| Human review | `/review` with Approve/Reject controls |
| RBAC | Server-side engineer, reviewer, and admin checks |
| Auditability | SQLite query and review logs with usernames |
| Admin analytics | Query counts, confidence averages, and review decision charts |
| Deployment | `Dockerfile`, `.dockerignore`, and pinned `requirements.txt` |

## Roles

| Role | Permissions |
|---|---|
| `engineer` | Upload, query, extract entities, compare documents, export data |
| `reviewer` | All engineer permissions plus approve/reject AI answers |
| `admin` | All reviewer permissions plus audit logs, review history, and charts |

Authorization is enforced by the backend as well as reflected in the UI. Hiding a button is not the security boundary.

## API overview

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/register` | Register a local user |
| `POST` | `/login` | Authenticate a local user |
| `POST` | `/projects` | Create a project for a registered user |
| `GET` | `/projects` | List projects |
| `POST` | `/upload` | Ingest a PDF into a selected project |
| `GET` | `/status?project=...` | List project-scoped documents and chunk count |
| `POST` | `/query` | Ask a project-scoped question |
| `POST` | `/extract_entities` | Extract entities from a project-scoped document |
| `POST` | `/compare_documents` | Compare two documents within a project |
| `GET` | `/export/{source}?project=...` | Export project-scoped document data |
| `POST` | `/review` | Submit reviewer/admin feedback |
| `GET` | `/audit_log?role=admin` | Read query audit data |
| `GET` | `/reviews?role=admin` | Read review history |

## Running locally

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with the Groq credential:

```bash
GROQ_API_KEY=your_key_here
```

Start the backend in one terminal:

```bash
uvicorn backend:app --reload
```

Start Streamlit in another:

```bash
streamlit run app.py
```

Open `http://localhost:8501`.

## Running with Docker

The image installs the Python dependencies and Tesseract OCR. The container exposes FastAPI on port 8000 and Streamlit on port 8501.

```bash
docker build -t autosar-hld-analysis-assistant .
docker run --env-file .env -p 8000:8000 -p 8501:8501 autosar-hld-analysis-assistant
```

Open `http://localhost:8501`.

The container is intentionally a pilot deployment with both processes in one container. A production deployment should separate the services and provide persistent volumes for `data/` and `uploads/`.

## Validation performed

- Python compilation for `backend.py` and `app.py`.
- Docker image build with the pinned dependency set.
- Fresh virtual-environment installation and Streamlit HTTP health check.
- Direct RBAC checks for engineer denial, reviewer approval, and admin access.
- Project isolation checks across separate test projects.
- Document comparison checks for related and unrelated documents.
- Friendly error checks with a simulated invalid Groq client.

## Pilot-scope limitations

- SQLite is used instead of PostgreSQL for local pilot simplicity.
- FAISS and pickle-backed metadata are local stores; production deployments should use durable, managed storage.
- Local authentication uses SHA-256 as a pilot simplification. This is not production-grade password storage; production should use a dedicated identity provider or a password hashing scheme such as Argon2 or bcrypt.
- There is no OAuth or SSO integration.
- Backend and frontend run together in the provided single-container Docker command.

## License and usage

This is an engineering pilot. AI-generated answers, extracted entities, and comparison findings must be reviewed by qualified engineers before use in compliance, design approval, or release decisions.