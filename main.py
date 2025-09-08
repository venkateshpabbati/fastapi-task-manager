import os, json, time, base64, textwrap, mimetypes, re
from typing import Dict, List
import requests
from dotenv import load_dotenv

# ========== Config ==========
load_dotenv()

OPENAI_COMPAT_MODEL = os.getenv("MODEL_NAME", "llama-3.1-8b-instruct")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")  # groq|together|hf
PROJECT_NAME = os.getenv("PROJECT_NAME", "fastapi-task-manager")
PROJECT_SPEC = os.getenv("PROJECT_SPEC", "Build a FastAPI task manager with CRUD and PostgreSQL.")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_PRIVATE = os.getenv("GITHUB_PRIVATE", "false").lower() == "true"

RENDER_API_KEY = os.getenv("RENDER_API_KEY")
RENDER_REPO_BRANCH = os.getenv("RENDER_REPO_BRANCH", "main")

# ========== Helpers ==========
def fail(msg: str):
    raise SystemExit(f"[x] {msg}")

def need(env_name: str):
    if not os.getenv(env_name):
        fail(f"Missing {env_name} in environment")

def http(method: str, url: str, headers=None, json_body=None, data=None):
    r = requests.request(method, url, headers=headers, json=json_body, data=data, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code} {url}\n{r.text}")
    return r.json() if "application/json" in r.headers.get("Content-Type", "") else r.text

# ========== LLM Calls ==========
def call_llm(prompt: str) -> str:
    try:
        if LLM_PROVIDER == "groq":
            groq_key = os.getenv("GROQ_API_KEY") or fail("Missing GROQ_API_KEY")
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = {"model": OPENAI_COMPAT_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}
            headers = {"Authorization": f"Bearer {groq_key}"}
            res = http("POST", url, headers=headers, json_body=payload)
            return res["choices"][0]["message"]["content"].strip()

        if LLM_PROVIDER == "together":
            tk = os.getenv("TOGETHER_API_KEY") or fail("Missing TOGETHER_API_KEY")
            url = "https://api.together.xyz/v1/chat/completions"
            payload = {"model": OPENAI_COMPAT_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}
            headers = {"Authorization": f"Bearer {tk}"}
            res = http("POST", url, headers=headers, json_body=payload)
            return res["choices"][0]["message"]["content"].strip()

        if LLM_PROVIDER == "hf":
            hf = os.getenv("HF_API_KEY") or fail("Missing HF_API_KEY")
            url = "https://api-inference.huggingface.co/v1/chat/completions"
            payload = {"model": OPENAI_COMPAT_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}
            headers = {"Authorization": f"Bearer {hf}"}
            res = http("POST", url, headers=headers, json_body=payload)
            return res["choices"][0]["message"]["content"].strip()

    except RuntimeError as e:
        fail(f"LLM call failed: {e}")

    fail("Unsupported LLM_PROVIDER")

# ========== Planning & Scaffolding ==========
PLAN_PROMPT = """
You are an AI software architect. Given the project spec below, return a JSON object with:
- plan: short bullet list of steps
- files: array of {path, content} to create a minimal, runnable app
Project spec:
"""

def generate_scaffold(spec: str) -> Dict:
    plan_raw = call_llm(PLAN_PROMPT + "\n" + spec + """
Rules:
- Use FastAPI + Uvicorn, include requirements.txt
- Include a simple PostgreSQL integration using SQLAlchemy (env-driven URI)
- Include Dockerfile and render.yaml (Render Blueprint) for web service
- Include a README.md with run and deploy instructions
- Keep code minimal but runnable; no placeholders like “TODO”
- Return ONLY JSON (no markdown) with keys { "plan": string, "files": [ ... ] }
""")
    plan_json = plan_raw.strip().strip("`").strip()
    try:
        return json.loads(plan_json)
    except json.JSONDecodeError:
        plan_raw = call_llm("Return strict JSON only. " + PLAN_PROMPT + "\n" + spec)
        return json.loads(plan_raw)

def write_files(files: List[Dict[str, str]]):
    for f in files:
        path = f["path"].lstrip("./")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(f["content"])

# ========== GitHub ==========
def gh_headers():
    need("GITHUB_TOKEN"); need("GITHUB_OWNER")
    return {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}

def create_github_repo(name: str, private: bool) -> Dict:
    try:
        return http("POST", "https://api.github.com/user/repos", headers=gh_headers(), json_body={"name": name, "private": private, "auto_init": False})
    except RuntimeError as e:
        if "403" in str(e):
            print("[!] No permission to create repo — please create it manually and re-run.")
            return {"html_url": f"https://github.com/{GITHUB_OWNER}/{name}"}
        raise

SECRET_PATTERNS = [
    r"(?i)api[_-]?key\s*=\s*['\"]?[A-Za-z0-9_\-]{16,}['\"]?",
    r"ghp_[A-Za-z0-9]{36,}",
    r"sk-[A-Za-z0-9]{32,}",
]

def contains_secret(text: str) -> bool:
    return any(re.search(pat, text) for pat in SECRET_PATTERNS)

def push_repo_from_disk(owner: str, repo: str, root: str = "."):
    skip_dirs = [".git", ".venv", "__pycache__", ".idea", ".vscode", "node_modules"]
    for dirpath, _, filenames in os.walk(root):
        if any(skip in dirpath for skip in skip_dirs):
            continue
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), root).replace("\\", "/")
            if rel.lower().endswith(".env") or "token" in rel.lower():
                print(f"[!] Skipping sensitive file: {rel}")
                continue
            mime, _ = mimetypes.guess_type(rel)
            is_binary = mime and not mime.startswith("text")
            if not is_binary:
                try:
                    with open(os.path.join(dirpath, fn), "r", encoding="utf-8") as fp:
                        content = fp.read()
                except UnicodeDecodeError:
                    print(f"[!] Skipping non‑UTF8 file: {rel}")
                    continue
                if contains_secret(content):
                    print(f"[!] Skipping file with possible secret: {rel}")
                    continue
                encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
            else:
                print(f"[!] Encoding binary file: {rel}")
                with open(os.path.join(dirpath, fn), "rb") as fp:
                    encoded = base64.b64encode(fp.read()).decode("utf-8")
            payload = {"message": f"Add {rel}", "content": encoded, "branch": "main"}
            url = f"https://api.github.com/repos/{owner}/{repo}/contents/{rel}"
            http("PUT", url, headers=gh_headers(), json_body=payload)

# ========== Render Deploy ==========
def render_headers():
    return {"Authorization": f"Bearer {RENDER_API_KEY}", "Accept": "application/json"}

def trigger_render_blueprint(owner: str, repo: str, branch: str):
    return http("POST", "https://api.render.com/v1/blueprint-deploys", headers=render_headers(),
                json_body={"repo": f"https://github.com/{owner}/{repo}", "branch": branch, "clearCache": True})

def poll_render_deploy(deploy_id: str, timeout_s: int = 600):
    url = f"https://api.render.com/v1/blueprint-deploys/{deploy_id}"
    start = time.time()
    while time.time() - start < timeout_s:
        data = http("GET", url, headers=render_headers())
        if data.get("status") in ("live", "succeeded"):
            urls = []
            for s in data.get("services", []):
                if s.get("service", {}).get("dashboardUrl"):
                    urls.append(s["service"]["dashboardUrl"])
                if s.get("service", {}).get("serviceDetails", {}).get("url"):
                    urls.append(s["service"]["serviceDetails"]["url"])
            return urls or ["(Render deployed; check dashboard)"]
        if data.get("status") in ("failed", "canceled", "deactivated"):
            return ["(Render deploy failed; check dashboard)"]
        time.sleep(5)
    return ["(Timed out waiting for Render)"]

# ========== Default Files (safety net) ==========
def ensure_minimal_files():
    if not os.path.exists("app/main.py"):
        os.makedirs("app", exist_ok=True)
        with open("app/main.py", "w", encoding="utf-8") as f:
            f.write(textwrap.dedent("""\
            from fastapi import FastAPI
            from pydantic import BaseModel
            app = FastAPI()

            class Task(BaseModel):
                id: int
                title: str
                done: bool = False

            DB = {}
            @app.get("/health") 
            def health(): return {"ok": True}
            @app.post("/tasks")
            def create_task(t: Task): DB[t.id] = t.model_dump(); return DB[t.id]
            @app.get("/tasks")
            def list_tasks(): return list(DB.values())
            """))
    if not os.path.exists("requirements.txt"):
        with open("requirements.txt", "w") as f:
            f.write("fastapi\nuvicorn[standard]\nSQLAlchemy\npsycopg2-binary\n")
    if not os.path.exists("Dockerfile"):
        with open("Dockerfile", "w") as f:
            f.write(textwrap.dedent("""\
            FROM python:3.11-slim
            WORKDIR /app
            COPY requirements.txt .
            RUN pip install -r requirements.txt
            COPY . .
            EXPOSE 8000
            CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
            """))
    if not os.path.exists("render.yaml"):
        with open("render.yaml", "w") as f:
            f.write(textwrap.dedent("""\
            services:
              - type: web
                name: fastapi-task-manager
                env: python
                plan: free
                buildCommand: pip install -r requirements.txt
                startCommand: uvicorn app.main:app --host 0.0.0.0 --port 8000
            """))
    if not os.path.exists("README.md"):
        with open("README.md", "w") as f:
            f.write("# FastAPI Task Manager\n\nRun locally: uvicorn app.main:app --reload\n")

# ========== Safety Helpers ==========
def create_gitignore():
    with open(".gitignore", "w", encoding="utf-8") as f:
        f.write(".env\n*.env\n__pycache__/\n*.pyc\n.venv/\n.idea/\n.vscode/\nnode_modules/\n")

def create_env_example():
    if not os.path.exists(".env"):
        return
    example_lines = []
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                key = line.split("=")[0]
                example_lines.append(f"{key}=YOUR_{key}_HERE")
            else:
                example_lines.append(line.strip())
    with open(".env.example", "w", encoding="utf-8") as f:
        f.write("\n".join(example_lines))

# ========== Orchestration ==========
def main():
    print(f"[i] Planning project: {PROJECT_NAME}")
    data = generate_scaffold(PROJECT_SPEC)
    plan = data.get("plan", "")
    files = data.get("files", [])

    if files:
        print("[i] Writing LLM-generated files...")
        write_files(files)
    else:
        print("[!] LLM returned no files; creating minimal scaffold")
        ensure_minimal_files()

    print("[i] Creating GitHub repo and pushing files...")
    repo = create_github_repo(PROJECT_NAME, GITHUB_PRIVATE)

    create_gitignore()
    create_env_example()

    push_repo_from_disk(GITHUB_OWNER, PROJECT_NAME, ".")

    repo_url = repo.get("html_url", f"https://github.com/{GITHUB_OWNER}/{PROJECT_NAME}")
    print(f"[✓] Repo ready: {repo_url}")

    live_urls = []
    if RENDER_API_KEY:
        print("[i] Triggering Render Blueprint deploy...")
        deploy = trigger_render_blueprint(GITHUB_OWNER, PROJECT_NAME, RENDER_REPO_BRANCH)
        deploy_id = deploy.get("id")
        if deploy_id:
            live_urls = poll_render_deploy(deploy_id)
    else:
        print("[i] No Render API key provided; skipping deploy step")

    print("\n======== Summary ========")
    print(f"Plan:\n{plan}\n")
    print(f"GitHub: {repo_url}")
    if live_urls:
        for u in live_urls:
            print(f"Live: {u}")
    print("=========================")

if __name__ == "__main__":
    need("GITHUB_TOKEN"); need("GITHUB_OWNER")
    main()
