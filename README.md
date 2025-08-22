# AI Mail Assistant

Local-first Outlook add-in that processes emails using a Gemini LLM. See the External Providers section on how to acquire an API key.

## AI Mail Assistant – Local setup and sideload guide

### Prerequisites
- Node.js (LTS) and npm
- Python 3.10+ and pip
- Outlook (Web or Desktop)
- OpenSSL (on macOS it’s available by default)

### 0) Install and trust local dev certificates (once)
```bash
npm i -g office-addin-dev-certs http-server
office-addin-dev-certs install   # Trust the cert in your OS keychain if prompted
```

### 1) Backend (FastAPI) – start locally on https://localhost:8000
```bash
cd backend
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000 \
  --ssl-keyfile ~/.office-addin-dev-certs/localhost.key \
  --ssl-certfile ~/.office-addin-dev-certs/localhost.crt
# Verify:
#   curl -k https://localhost:8000/health
```

Backend reads environment variables from `backend/.env` (auto‑loaded via python-dotenv). Create this file to keep keys local (no shell profile edits needed). If `GEMINI_API_KEY` is set and `LLM_PROVIDER` is omitted, the backend defaults to Gemini with `gemini-2.5-flash`:
```bash
cat > backend/.env << 'EOF'
# LLM provider selection: mock | gemini (optional when GEMINI_API_KEY is set)
# LLM_PROVIDER=gemini

# Gemini (Google AI Studio)
GEMINI_API_KEY=
# Default model if not set: gemini-2.5-flash
GEMINI_MODEL=gemini-2.5-flash

EOF
```

### 2) Frontend (taskpane) – serve over HTTPS on https://localhost:3000
```bash
# Serve from addin root so assets resolve
cd addin
http-server -p 3000 --ssl \
  --cert ~/.office-addin-dev-certs/localhost.crt \
  --key ~/.office-addin-dev-certs/localhost.key
```

### 3) Configure the manifest (if needed)
- Ensure `addin/manifest/manifest.xml`:
  - Name is “AI Mail Assistant”
  - Taskpane URL points to `https://localhost:3000/src/taskpane/taskpane.html`
  - Icons point to your `assets/` paths
- In `addin/src/taskpane/taskpane.js`, set:
  - `API_BASE_URL = "https://localhost:8000"`

### 4) Sideload the add-in
- Follow Microsoft’s sideloading instructions: [aka.ms/olksideload](https://aka.ms/olksideload)
- Typical steps:
  - Outlook Web: Settings → View all Outlook settings → Mail → Customize actions → Add-ins → My add-ins → Add a custom add-in → Add from file → select `manifest/manifest.xml`
  - Outlook Desktop: Home tab → Get Add-ins → My add-ins → Add a custom add-in → Add from file → select `manifest/manifest.xml`

### 5) Test the end‑to‑end flow
- Open an email in Outlook
- Open “AI Mail Assistant” from the ribbon
- Click “Test Connection” → should show “Backend: ok”
- Click “Process Email” → Summary, Action Items, and Draft appear
- Click “Process Email (stream)” → Draft text streams in
- Click “Insert as Reply” → Draft is inserted into a reply window

### Troubleshooting
- SSL issues: re-run `office-addin-dev-certs install` and ensure the cert is trusted in your OS keychain
- CORS: backend must allow `https://localhost:3000` (already configured in `backend/app.py`)
- No email selected: open a message and reopen the taskpane
- Outlook Desktop sometimes caches manifests; remove and re-add the add-in after changes
- Browser trust for dev certs: open these URLs in the SAME browser you use for Outlook Web and click “Advanced → Continue” to trust them once:
  - `https://localhost:3000/src/taskpane/taskpane.html`
  - `https://localhost:3000/assets/favicon-32x32.png` (or any asset)
  - `https://localhost:8000/health`
  - Tip (Firefox): set `about:config → security.enterprise_roots.enabled = true`, or import `~/.office-addin-dev-certs/ca.crt` under Certificates → Authorities.

### Switching to a real LLM later
- Keep the mock LLM for local dev
- Implement provider(s) in `backend/services/llm.py` and wire via env (e.g., `LLM_PROVIDER=openai`)
- No changes required in the add-in UI or API contracts

### External LLM provider (Gemini)
You can enable a hosted LLM without changing the UI by choosing `gemini` via env vars. The backend handles the call and returns the same response schema.

Supported providers:
- `mock` (default, no API key)
- `gemini` (Google Generative AI)

Setup:
1) Install deps (already in `backend/requirements.txt`):
   - `google-generativeai`
2) Alternatively, set environment variables before starting the backend (not required if using `.env`):
```bash
export LLM_PROVIDER=gemini
export GEMINI_API_KEY=...            # required when using Gemini
export GEMINI_MODEL=gemini-2.5-flash # optional
```
3) The add-in can still pass `provider: 'mock'|'gemini'` in the request body; if omitted, the backend uses `LLM_PROVIDER`.

Notes:
- Responses are normalized to `{ summary, action_items, draft_reply_html }`.
- Streaming is supported; tokens are sent as SSE `event: token`.
- Keep API keys out of the frontend; set them as env vars for the backend process.

#### Get a Gemini API key (Google AI Studio)
- Go to [Google AI Studio – API keys](https://aistudio.google.com/app/apikey) and sign in.
- Click “Create API key”, select or create a Google Cloud project, and copy the key.
- Put it in `backend/.env` (do not commit). Example shown above.
- Choose a model, e.g. `GEMINI_MODEL=gemini-2.5-flash` (fast) or `gemini-2.0-pro` (stronger). Keep `LLM_PROVIDER=gemini`.
- Start the backend with HTTPS as above and verify in the add-in.

## Using Microsoft Graph / SharePoint (Azure configuration)

You only need Azure configuration if you want to call Microsoft Graph (e.g., search SharePoint for relevant files). Below is a minimal delegated flow suitable for local dev, plus an optional server-side flow for production.

### A) Register an app in Entra ID (Azure AD)
1. Go to Azure Portal → Entra ID → App registrations → New registration
2. Name: AI Mail Assistant (local)
3. Supported account types: Single tenant (recommended for dev)
4. Redirect URI: Single-page application (SPA)
   - `https://localhost:3000/src/taskpane/taskpane.html`
   - Optionally also `https://localhost:3000/`

### B) Grant Microsoft Graph delegated permissions
- openid, profile, offline_access
- User.Read
- Files.Read (basic) and optionally Files.Read.All for all drives
- Sites.Read.All (to search across SharePoint sites)
Then click “Grant admin consent” for your tenant.

### C) Frontend authentication (local dev)
- Add `@azure/msal-browser` to your frontend (served from `addin/`):
  - `npm i @azure/msal-browser`
- Configure MSAL with your app registration:
  - Tenant ID and Client ID from the Azure portal
  - Authority: `https://login.microsoftonline.com/<TENANT_ID>`
  - Scopes: `['User.Read', 'Files.Read', 'Sites.Read.All', 'offline_access']`
- Acquire a token via `loginPopup` or `acquireTokenSilent`, then call Graph directly from the taskpane for quick prototyping:
  - Example endpoints:
    - `GET https://graph.microsoft.com/v1.0/me/drive/search(q='contract')`
    - `GET https://graph.microsoft.com/v1.0/sites?search=legal` then `GET /sites/{site-id}/drive/root/search(q='case-1234')`
- Keep the token in memory only; do not store secrets in the frontend.

### D) Backend-assisted Graph calls (recommended for production)
If you want the backend to call Graph (e.g., to enrich LLM context) without exposing tokens/logic in the browser, use the On-Behalf-Of (OBO) flow:
1. In the same app registration, add a “Web” platform and set a backend redirect URI (e.g., `https://localhost:8000/auth/redirect`) if needed for your flow.
2. Create a client secret (or upload a certificate) and store securely as env vars (do not commit):
   - `AZURE_TENANT_ID`
   - `AZURE_CLIENT_ID`
   - `AZURE_CLIENT_SECRET`
3. Frontend obtains a user token (Step C) and sends it to the backend (e.g., `Authorization: Bearer <token>`).
4. Backend exchanges the user token for a Graph token via OBO, then calls Graph (e.g., SharePoint search) server-side.
5. Return only the minimal data needed to the frontend.

Notes:
- The current repo ships a demo endpoint `POST /api/v1/list_demo_sharepoint_files` that returns static data. Replace it with real Graph calls once authentication is wired.
- Ensure CORS in `backend/app.py` allows `https://localhost:3000` (already configured).
- For enterprise tenants with strict policies, Office SSO is another option. That requires adding a `webApplicationInfo` block in the add-in manifest and using `OfficeRuntime.auth.getAccessToken()`; it’s more complex but reduces sign-in prompts.

## Features
- Process selected email → summary, action items, draft reply
- Streaming and non-streaming modes
- Insert draft as reply in Outlook
- Diagnostics panel
- Demo SharePoint/Graph stub endpoint

## Switch to a real LLM later
Edit `backend/services/llm.py` and implement providers in `get_llm()`.
