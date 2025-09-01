# file: smart_librarian.py
import os, json, re, unicodedata
from unidecode import unidecode
from dotenv import load_dotenv
from openai import OpenAI
from openai import OpenAI, Moderation
import chromadb
from chromadb.utils import embedding_functions

load_dotenv()
GPT_MODEL   = os.getenv("OPENAI_MODEL_GPT", "gpt-4o-mini")
EMB_MODEL   = os.getenv("OPENAI_MODEL_EMB", "text-embedding-3-small")
AI          = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 3.1 – conectare la vector-store
client_vs   = chromadb.PersistentClient(path="vectorstore")
collection  = client_vs.get_collection("books")

openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=os.getenv("OPENAI_API_KEY"),
    model_name=EMB_MODEL
)

client_vs  = chromadb.PersistentClient(path="vectorstore")
collection = client_vs.get_collection(
    "books",
    embedding_function=openai_ef       # ← CHEIA problemei
)

BAD_REGEX = re.compile(
    r"\b("
    r"cacat|căcat|câcat|"        # toate variantele
    r"dracu|dracului|drac|draq|" # forme flexionate + “draq”
    r"prost|handicapat|retardat|dobitoc|idiot"   # adaugă ce consideri necesar
    r")\b",
    re.IGNORECASE
)
def contains_bad_local(text: str) -> bool:
    # 1. Normalizează (NFKD) și elimină diacritice
    normalized = unidecode(unicodedata.normalize("NFKD", text))
    # 2. Caută pattern-ul
    return bool(BAD_REGEX.search(normalized))

def contains_bad_openai(text: str) -> bool:
    mod = AI.moderations.create(
        model="omni-moderation-latest",
        input=text
    )
    return any(r.flagged for r in mod.results)

def is_flagged(text: str) -> bool:
    return contains_bad_local(text) or contains_bad_openai(text)

def search_books(query: str, k: int = 3):
    if not query.strip():
        query = "*"          # orice text ne-gol
    res = collection.query(query_texts=[query], n_results=k)
    return list(zip(res['metadatas'][0], res['documents'][0]))

SYSTEM_PROMPT = """
Ești un bibliotecar virtual. Primești o listă de cărți (titlu + rezumat)
în "Context intern". Răspunde astfel:

1. Alege EXACT UN titlu din listă (copiază textul identic).
2. Scrie pe prima linie: "Cartea recomandată: <TITLU>"
3. Oferă 2-3 fraze motiv pentru recomandare.
4. Dacă vrei să oferi rezumatul complet, cheamă tool-ul
   get_summary_by_title cu {"title":"<TITLU ales>"}.
Nu inventa titluri și nu răspunde cu "None".
"""


def run_chat():
    while True:
        user_q = input("\nUtilizator> ").strip()
        if user_q.lower() in {"exit", "quit"}:
            break

        if is_flagged(user_q):
            print("\nBot > Îmi pare rău, dar nu pot continua cu acest tip de limbaj.")
            continue

        # --- RAG ---
        retrieved = search_books(user_q, k=3)
        context = "\n\n".join(f"{m['title']}: {t}" for m, t in retrieved)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_q},
            {"role": "user",   "content": f"Context intern:\n{context}"}
        ]

        response = AI.chat.completions.create(
            model=GPT_MODEL,
            messages=messages,
            tools=[{
                "type": "function",
                "function": {
                    "name": "get_summary_by_title",
                    "description": "Returnează rezumatul complet pentru un titlu dat",
                    "parameters": {
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                        "required": ["title"]
                    }
                }
            }],
            tool_choice="auto"
        )

        msg = response.choices[0].message

        # 1️⃣  Dacă a venit text normal de la GPT, îl afișăm direct
        if msg.content:
            print("\nBot >", msg.content)

        # 2️⃣  Dacă GPT a invocat tool-ul, îl executăm
        if msg.tool_calls:
            for call in msg.tool_calls:
                if call.function.name == "get_summary_by_title":
                    args = json.loads(call.function.arguments)
                    title = args.get("title", "").strip()
                    full = get_summary_by_title(title)
                    # dacă tot n-a găsit titlul, arată un fallback
                    if full == "Rezumat indisponibil.":
                        print("\nBot > Din păcate nu am găsit titlul solicitat.")
                    else:
                        print(f"\nBot > Cartea recomandată: {title}")
                        print("\nRezumat complet:\n", full)


# 4. Tool local pentru rezumate detaliate ─ cerință PDF :contentReference[oaicite:3]{index=3}
book_summaries_dict = { m['title']: t for m, t in search_books("") }

def get_summary_by_title(title: str) -> str:
    return book_summaries_dict.get(title, "Rezumat indisponibil.")

if __name__ == "__main__":
    run_chat()
