# app_flask_chroma.py
import os, json, pathlib, re, unicodedata, chromadb
from typing import List, Tuple
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from unidecode import unidecode
from chromadb.utils import embedding_functions
from openai import OpenAI

# --- Config ---
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GPT_MODEL = os.getenv("OPENAI_MODEL_GPT", "gpt-4o-mini")
EMB_MODEL = os.getenv("OPENAI_MODEL_EMB", "text-embedding-3-small")
CHROMA_PATH = "vectorstore"
BOOKS_MD = "book_summaries.md"

if not OPENAI_API_KEY:
    raise RuntimeError("Lipsește OPENAI_API_KEY în .env")

AI = OpenAI(api_key=OPENAI_API_KEY)

# --- Chroma: re-folosește exact ce ai în CLI ---
openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=OPENAI_API_KEY,
    model_name=EMB_MODEL
)
client_vs = chromadb.PersistentClient(path=CHROMA_PATH)
collection = client_vs.get_or_create_collection("books", embedding_function=openai_ef)

# populare de siguranță dacă vectorstore-ul e gol
def ensure_populated():
    if collection.count() > 0: return
    p = pathlib.Path(BOOKS_MD)
    if not p.exists(): return
    text = p.read_text(encoding="utf-8")
    docs = [s.strip() for s in text.split("## Title:") if s.strip()]
    ids, metas, texts = [], [], []
    for raw in docs:
        title, *summary_lines = raw.splitlines()
        title = title.strip()
        summary = " ".join(summary_lines).strip()
        if title:
            ids.append(title); metas.append({"title": title}); texts.append(summary)
    if ids:
        collection.upsert(ids=ids, documents=texts, metadatas=metas)
ensure_populated()

# dicționarul complet (fără query gol)
def build_full_dict():
    all_docs = collection.get(include=["documents", "metadatas"])
    return { meta["title"]: doc for meta, doc in zip(all_docs["metadatas"], all_docs["documents"]) }
BOOKS_FULL = build_full_dict()

def search_books(query: str, k: int = 3) -> List[Tuple[dict, str]]:
    q = (query or "").strip() or "recomandare carte"
    res = collection.query(query_texts=[q], n_results=k)
    return list(zip(res["metadatas"][0], res["documents"][0]))

def get_summary_by_title(title: str) -> str:
    return BOOKS_FULL.get(title, "Rezumat indisponibil.")

SYSTEM_PROMPT = """
Ești un bibliotecar virtual. Primești o listă de cărți (titlu + rezumat)
în „Context intern”. Răspunde în română astfel:
1) Alege EXACT UN titlu din listă (copiat identic).
2) Scrie pe prima linie: 'Cartea recomandată: <TITLU>'.
3) Oferă 2–3 fraze motiv.
4) Dacă dorești să afișezi rezumatul complet, cheamă tool-ul get_summary_by_title
   cu {"title":"<TITLU ales>"}.
Nu inventa titluri. Nu răspunde cu 'None'.
"""

# Filtru de limbaj (opțional din temă)
BAD = re.compile(r"\b(cacat|căcat|câcat|kkt|dracu|dracului|draq|pula|pulă|muie|pizda|pizdă)\b", re.IGNORECASE)
def flagged(text:str)->bool:
    from unidecode import unidecode
    return bool(BAD.search(unidecode(unicodedata.normalize("NFKD", text))))

# --- Flask app (servește și UI-ul static) ---
app = Flask(__name__, static_folder="web", static_url_path="/")
CORS(app, resources={r"/api/*": {"origins": ["http://localhost:*","http://127.0.0.1:*"]}})

@app.get("/")
def root():
    # / -> web/index.html
    return send_from_directory("web", "index.html")

@app.get("/api/health")
def health():
    return jsonify({"ok": True, "count": collection.count()})

@app.post("/api/chat")
def chat():
    try:
        data = request.get_json(force=True) or {}
        user_q = (data.get("message") or "").strip()
        generate_image = bool(data.get("generateImage", True))
        if not user_q:
            return jsonify({"blocked": False, "message": "Mesaj gol."}), 422

        if flagged(user_q):
            return jsonify({"blocked": True, "message": "Îmi pare rău, dar nu pot continua cu acest limbaj."})

        # RAG
        retrieved = search_books(user_q, k=3)
        context = "\n\n".join(f"{m['title']}: {t}" for m, t in retrieved)

        messages = [
            {"role":"system", "content": SYSTEM_PROMPT},
            {"role":"user",   "content": user_q},
            {"role":"user",   "content": f"Context intern:\n{context}"}
        ]

        first = AI.chat.completions.create(
            model=GPT_MODEL,
            messages=messages,
            tools=[{
                "type": "function",
                "function": {
                    "name": "get_summary_by_title",
                    "description": "Returnează rezumatul complet pentru un titlu din colecție",
                    "parameters": {
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                        "required": ["title"]
                    }
                }
            }],
            tool_choice="auto",
        )

        msg = first.choices[0].message
        final_text = msg.content or ""
        final_title = None
        full_summary = None

        # tool calling (rezumat complet)
        if msg.tool_calls:
            tool_msgs = []
            for call in msg.tool_calls:
                if call.function.name == "get_summary_by_title":
                    args = json.loads(call.function.arguments or "{}")
                    title = (args.get("title") or "").strip()
                    final_title = title or final_title
                    full_summary = get_summary_by_title(title)
                    tool_msgs.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": "get_summary_by_title",
                        "content": full_summary,
                    })
            second = AI.chat.completions.create(
                model=GPT_MODEL,
                messages=messages + [
                    {"role": "assistant", "content": msg.content, "tool_calls": msg.tool_calls}
                ] + tool_msgs
            )
            final_text = second.choices[0].message.content or final_text

        # încearcă să extragi titlul dacă nu e explicit
        if not final_title:
            m = re.search(r"Cartea recomandată:\s*(.+)", final_text)
            if m:
                final_title = m.group(1).strip()

        # după ce ai final_title
        if final_title and generate_image:
            prompt_img = f"O copertă sugestivă pentru cartea '{final_title}'"
            try:
                img_resp = AI.images.generate(
                    model="gpt-image-1",
                    prompt=prompt_img,
                    size="512x512"  # poți folosi și 256x256 sau 1024x1024
                )
                image_url = img_resp.data[0].url
            except Exception as e:
                image_url = None
        else:
            image_url = None

        return jsonify({
            "blocked": False,
            "message": final_text,
            "recommendedTitle": final_title,
            "fullSummary": full_summary,
            "imageUrl": image_url,
            "error": None
        })


    except Exception as e:
        return jsonify({"blocked": False, "error": str(e), "message": "Eroare server."}), 500

if __name__ == "__main__":
    # Rulezi totul din PyCharm: un singur Run → UI + API pe același port
    app.run(host="127.0.0.1", port=8000, debug=True)
