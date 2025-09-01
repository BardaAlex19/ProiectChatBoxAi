# setup_vector_store.py  – versiunea corectată
import os, pathlib, chromadb
from dotenv import load_dotenv
from chromadb.utils import embedding_functions
load_dotenv()

client = chromadb.PersistentClient(path="vectorstore")
openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=os.getenv("OPENAI_API_KEY"),
    model_name=os.getenv("OPENAI_MODEL_EMB")
)
collection = client.get_or_create_collection("books", embedding_function=openai_ef)

# ------------- fix aici -------------
text = pathlib.Path("book_summaries.md").read_text(encoding="utf-8")
docs = text.split("## Title:")
# -------------------------------------

ids, metas, texts = [], [], []
for raw in filter(None, map(str.strip, docs)):
    title, *summary_lines = raw.splitlines()
    summary = " ".join(summary_lines).strip()
    ids.append(title.strip())
    metas.append({"title": title.strip()})
    texts.append(summary)

collection.upsert(ids=ids, documents=texts, metadatas=metas)
print("Vector-store inițializat cu:", collection.count(), "cărți")
