import os
import fitz  # PyMuPDF
import faiss
import numpy as np
import pickle
import io
import json
import sqlite3
import hashlib
from datetime import datetime
from PIL import Image
import pytesseract
pytesseract.pytesseract.tesseract_cmd = "/opt/homebrew/bin/tesseract"
from fastapi import FastAPI, UploadFile, File, Form, Query
from sentence_transformers import SentenceTransformer
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Load embedding model once at startup
embedder = SentenceTransformer('all-MiniLM-L6-v2')

# Groq client
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Paths
UPLOAD_DIR = "uploads"
INDEX_PATH = "data/faiss_index.bin"
CHUNKS_PATH = "data/chunks.pkl"
DB_PATH = "data/audit.db"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs("data", exist_ok=True)

# In-memory storage (loaded/saved to disk)
chunks_store = []  # list of dicts: {text, page, source, ocr_used}
index = None


def load_index():
    global index, chunks_store
    if os.path.exists(INDEX_PATH) and os.path.exists(CHUNKS_PATH):
        index = faiss.read_index(INDEX_PATH)
        with open(CHUNKS_PATH, "rb") as f:
            chunks_store = pickle.load(f)
    else:
        index = faiss.IndexFlatL2(384)  # 384 = embedding dim of MiniLM
        chunks_store = []


def save_index():
    faiss.write_index(index, INDEX_PATH)
    with open(CHUNKS_PATH, "wb") as f:
        pickle.dump(chunks_store, f)


load_index()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS query_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        question TEXT,
        source_filter TEXT,
        confidence REAL,
        username TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password_hash TEXT,
        role TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        question TEXT,
        answer TEXT,
        decision TEXT,
        source_filter TEXT,
        username TEXT
    )""")

    # Migrate databases created by older versions of the application.
    for table, column in (("query_log", "username"), ("reviews", "username")):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")

    conn.commit()
    conn.close()


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def log_query(question, source_filter, confidence, username):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO query_log (timestamp, question, source_filter, confidence, username) VALUES (?, ?, ?, ?, ?)",
        (datetime.now().isoformat(), question, source_filter, confidence, username)
    )
    conn.commit()
    conn.close()


init_db()


VALID_ROLES = {"engineer", "reviewer", "admin"}


@app.post("/register")
async def register(username: str = Form(...), password: str = Form(...), role: str = Form(...)):
    username = username.strip()
    if not username or not password:
        return {"status": "error", "message": "Username and password are required"}
    if role not in VALID_ROLES:
        return {"status": "error", "message": "Invalid role"}

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, hash_password(password), role)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return {"status": "error", "message": "Username already exists"}
    finally:
        conn.close()

    return {"status": "success", "username": username, "role": role}


@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT username, role FROM users WHERE username = ? AND password_hash = ?",
        (username.strip(), hash_password(password))
    ).fetchone()
    conn.close()

    if not row:
        return {"status": "error", "message": "Invalid credentials"}
    return {"status": "success", "username": row[0], "role": row[1]}


def chunk_text(text, page_num, source, ocr_used=False, chunk_size=500):
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append({"text": chunk, "page": page_num, "source": source, "ocr_used": ocr_used})
    return chunks


def ocr_page(page):
    """Render a PDF page as an image and run Tesseract OCR on it."""
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    img_bytes = pix.tobytes("png")
    image = Image.open(io.BytesIO(img_bytes))
    ocr_text = pytesseract.image_to_string(image)
    print(f"[OCR DEBUG] Extracted {len(ocr_text)} characters. Preview: {ocr_text[:200]!r}")
    return ocr_text


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        f.write(await file.read())

    doc = fitz.open(file_path)
    all_chunks = []
    total_pages = len(doc)
    ocr_pages_count = 0

    for page_num, page in enumerate(doc, start=1):
        text = page.get_text()
        used_ocr = False

        if len(text.strip()) < 20:
            ocr_text = ocr_page(page)
            if ocr_text.strip():
                text = ocr_text
                used_ocr = True
                ocr_pages_count += 1

        if text.strip():
            page_chunks = chunk_text(text, page_num, file.filename, ocr_used=used_ocr)
            all_chunks.extend(page_chunks)

    doc.close()

    if not all_chunks:
        return {"status": "error", "message": "No extractable text found in PDF, even after OCR."}

    texts = [c["text"] for c in all_chunks]
    embeddings = embedder.encode(texts, convert_to_numpy=True)

    global index, chunks_store
    index.add(embeddings.astype('float32'))
    chunks_store.extend(all_chunks)
    save_index()

    return {
        "status": "success",
        "filename": file.filename,
        "pages_processed": total_pages,
        "pages_ocr_used": ocr_pages_count,
        "chunks_created": len(all_chunks)
    }


@app.post("/query")
async def query_docs(question: str = Form(...), top_k: int = Form(4), source_filter: str = Form(None), username: str = Form(None)):
    if index.ntotal == 0:
        return {"answer": "No documents have been uploaded yet.", "confidence": 0, "sources": []}

    q_embedding = embedder.encode([question], convert_to_numpy=True).astype('float32')

    search_k = min(top_k * 5, index.ntotal)
    distances, indices = index.search(q_embedding, search_k)

    retrieved_chunks = []
    for idx, dist in zip(indices[0], distances[0]):
        if idx < len(chunks_store):
            chunk = chunks_store[idx]
            if source_filter and source_filter != "All Documents" and chunk["source"] != source_filter:
                continue
            retrieved_chunks.append({
                "text": chunk["text"],
                "page": chunk["page"],
                "source": chunk["source"],
                "ocr_used": chunk.get("ocr_used", False),
                "distance": float(dist)
            })
        if len(retrieved_chunks) >= top_k:
            break

    print(f"[QUERY DEBUG] source_filter={source_filter!r}, search_k={search_k}, retrieved={len(retrieved_chunks)}")
    print(f"[QUERY DEBUG] sources found: {[c['source'] for c in retrieved_chunks]}")

    if retrieved_chunks:
        best_distance = min(c["distance"] for c in retrieved_chunks)
        confidence = max(0, min(100, 100 - (best_distance * 10)))
    else:
        confidence = 0

    context = "\n\n".join([f"[Page {c['page']}, {c['source']}]: {c['text']}" for c in retrieved_chunks])

    prompt = f"""You are an assistant helping engineers understand AUTOSAR HLD documents.
Answer the question using ONLY the context below. If the answer isn't in the context, say so clearly.
Cite the page numbers you used in your answer.

Context:
{context}

Question: {question}

Answer:"""

    completion = groq_client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )

    answer = completion.choices[0].message.content

    log_query(question, source_filter, confidence, username)

    return {
        "answer": answer,
        "confidence": round(confidence, 1),
        "sources": [
            {
                "page": c["page"],
                "source": c["source"],
                "snippet": c["text"][:200],
                "ocr_used": c["ocr_used"]
            } for c in retrieved_chunks
        ]
    }


@app.get("/status")
async def status():
    return {"total_chunks": len(chunks_store), "documents": list(set(c["source"] for c in chunks_store))}


@app.post("/extract_entities")
async def extract_entities(source: str = Form(...)):
    doc_chunks = [c for c in chunks_store if c["source"] == source]
    if not doc_chunks:
        return {"status": "error", "message": "No chunks found for this document."}

    doc_chunks.sort(key=lambda c: c["page"])
    full_text = "\n\n".join([f"[Page {c['page']}]: {c['text']}" for c in doc_chunks])

    max_chars = 12000
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars]

    prompt = f"""You are analyzing an AUTOSAR HLD document. Extract a structured inventory of architecture entities mentioned in the text below.

Return ONLY valid JSON, no other text, in exactly this format:
{{
  "components": ["name1", "name2"],
  "interfaces": ["name1", "name2"],
  "ports": ["name1", "name2"],
  "signals": ["name1", "name2"]
}}

If a category has no clear entries, return an empty list for it. Do not invent entities not mentioned in the text.

Document text:
{full_text}
"""

    completion = groq_client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )

    raw = completion.choices[0].message.content.strip()

    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        entities = json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "error", "message": "Could not parse entity extraction result.", "raw": raw}

    return {"status": "success", "source": source, "entities": entities}


@app.post("/compare_documents")
async def compare_documents(source_a: str = Form(...), source_b: str = Form(...)):
    if source_a == source_b:
        return {"status": "error", "message": "Please select two different documents"}

    chunks_a = sorted(
        [c for c in chunks_store if c["source"] == source_a],
        key=lambda c: c["page"]
    )
    chunks_b = sorted(
        [c for c in chunks_store if c["source"] == source_b],
        key=lambda c: c["page"]
    )

    if not chunks_a or not chunks_b:
        return {
            "status": "error",
            "message": "Both documents must contain ingested chunks."
        }

    max_chars = 12000
    text_a = "\n\n".join(
        f"[Page {c['page']}]: {c['text']}" for c in chunks_a
    )[:max_chars]
    text_b = "\n\n".join(
        f"[Page {c['page']}]: {c['text']}" for c in chunks_b
    )[:max_chars]

    prompt = f"""Compare these two AUTOSAR HLD documents.

Identify components, interfaces, and signals mentioned in both documents.
Flag naming inconsistencies, contradictions, and relevant items present in
only one document. Do not invent entities or inconsistencies.

Return ONLY valid JSON in exactly this format:
{{
  "shared_entities": ["EntityName"],
  "inconsistencies": [
    {{"item": "EntityName", "issue": "Description of the inconsistency"}}
  ],
  "only_in_doc_a": ["EntityName"],
  "only_in_doc_b": ["EntityName"]
}}

If a category has no entries, return an empty list.

DOCUMENT A ({source_a}):
{text_a}

DOCUMENT B ({source_b}):
{text_b}
"""

    try:
        completion = groq_client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )

        raw = completion.choices[0].message.content.strip()

        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()

        comparison = json.loads(raw)
        return {"status": "success", "comparison": comparison}
    except json.JSONDecodeError:
        return {
            "status": "error",
            "message": "Could not parse document comparison result.",
            "raw": raw
        }
    except Exception as exc:
        return {"status": "error", "message": f"Document comparison failed: {exc}"}


@app.get("/export/{source}")
async def export_document(source: str):
    doc_chunks = [c for c in chunks_store if c["source"] == source]
    if not doc_chunks:
        return {"status": "error", "message": "No data found for this document."}
    export_data = {
        "document": source,
        "total_chunks": len(doc_chunks),
        "chunks": [{"page": c["page"], "text": c["text"], "ocr_used": c.get("ocr_used", False)} for c in doc_chunks]
    }
    return export_data


@app.get("/audit_log")
async def get_audit_log(role: str = Query(...)):
    if role != "admin":
        return {"status": "error", "message": "Insufficient permissions: admin role required"}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM query_log ORDER BY id DESC LIMIT 50").fetchall()
    conn.close()
    return {"logs": [dict(r) for r in rows]}
@app.post("/review")
async def submit_review(
    question: str = Form(...),
    answer: str = Form(...),
    decision: str = Form(...),
    source_filter: str = Form(None),
    role: str = Form(...),
    username: str = Form(...)
):
    if role not in ("reviewer", "admin"):
        return {"status": "error", "message": "Insufficient permissions: reviewer role required"}

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO reviews (timestamp, question, answer, decision, source_filter, username) VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now().isoformat(), question, answer, decision, source_filter, username)
    )
    conn.commit()
    conn.close()
    return {"status": "success"}


@app.get("/reviews")
async def get_reviews(role: str = Query(...)):
    if role != "admin":
        return {"status": "error", "message": "Insufficient permissions: admin role required"}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM reviews ORDER BY id DESC LIMIT 50").fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return {"reviews": [dict(r) for r in rows]}