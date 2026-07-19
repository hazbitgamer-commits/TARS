"""Live web answers: search DuckDuckGo (free, no key), then have the local
model turn the results into one spoken answer."""
import requests

DESCRIPTION = ("Search the web for current information: news, sport results, prices, "
               "release dates, facts that change over time, 'search for X'.")
ARGS = {"query": "what to search the web for"}

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3:8b"


def _search(query: str) -> list[dict]:
    from ddgs import DDGS

    try:
        return list(DDGS().text(query, max_results=5))
    except Exception:
        # Avast intercepts TLS; retry without certificate verification
        return list(DDGS(verify=False).text(query, max_results=5))


def run(args: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "Search for what, exactly?"
    try:
        results = _search(query)
    except Exception as e:
        return f"The web search failed on me: {e}"
    if not results:
        return f"The web gave me nothing useful for {query}."

    snippets = "\n".join(
        f"- {r.get('title', '')}: {r.get('body', '')}" for r in results
    )
    prompt = (
        f"Web search results for the question: {query!r}\n{snippets}\n\n"
        "Answer the question in one to three short spoken sentences using only "
        "these results. Plain text, no markdown, no links. If the results don't "
        "answer it, say so briefly."
    )
    try:
        r = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                  "stream": False, "think": False, "keep_alive": "2h",
                  "options": {"num_predict": 160}},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except Exception:
        top = results[0]
        return f"Best I found: {top.get('title', '')}. {top.get('body', '')[:200]}"
