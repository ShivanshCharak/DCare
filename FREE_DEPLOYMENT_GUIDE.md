# 100% Free Tier Deployment Guide

Deploy DCare / Discharge Explainer completely free using modern developer cloud platforms:

| Layer | Free Platform | Role |
| :--- | :--- | :--- |
| **Frontend** | **Vercel** or **Cloudflare Pages** | Next.js 14 web client |
| **Backend** | **Render** (Free Web Service) | FastAPI backend with Tesseract OCR (Docker) |
| **Database** | **Supabase** (Free Tier PostgreSQL) | Persistent document storage |
| **Vector Search** | **PostgreSQL `pgvector`** (Supabase) | Embedded semantic search without extra DB fees |
| **AI Inference** | **Groq Cloud** (Free API Tier) or OpenRouter | Llama 3 / Mixtral with high speed and zero GPU cost |
| **Source Control** | **GitHub** | Code repository with auto-deploy webhooks |

---

## Step 1: Database & pgvector (Supabase)

1. Go to [supabase.com](https://supabase.com) and create a free project.
2. In the Supabase Dashboard, open the **SQL Editor**.
3. Copy and run the SQL script from [`supabase/schema.sql`](supabase/schema.sql):
   - Enables `vector` extension (`pgvector`).
   - Creates the `documents` table.
   - Creates the `document_embeddings` table and cosine similarity search function.
4. Go to **Project Settings** ➔ **Database** ➔ **Connection String** ➔ **URI** (mode: Transaction or Session).
5. Copy your URI. It looks like:
   ```text
   postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
   ```

---

## Step 2: Free AI Inference (Groq Cloud)

Instead of paying for expensive cloud GPU instances:

1. Sign up for free at [console.groq.com](https://console.groq.com).
2. Go to **API Keys** and click **Create API Key**.
3. Copy your key (`gsk_...`).
   * Groq provides high rate limits on `llama-3.1-8b-instant` and `llama-3.3-70b-versatile` completely free.

*(Alternatively, you can use OpenRouter free tier or Google Gemini API in OpenAI-compatible format).*

---

## Step 3: Backend on Render (FastAPI + Docker + OCR)

Render can build and run your backend container directly from GitHub.

1. Push your repository to **GitHub**.
2. Go to [render.com](https://render.com) and click **New +** ➔ **Blueprint** (or **Web Service**).
   - If using **Blueprint**: Render will automatically detect [`render.yaml`](render.yaml).
   - If using **Web Service manually**:
     - Connect your GitHub repo.
     - **Runtime:** `Docker`
     - **Dockerfile Path:** `backend/Dockerfile`
     - **Docker Build Context:** `backend`
     - **Instance Type:** `Free`
3. Add the following **Environment Variables** in Render:
   - `APP_ENV`: `production`
   - `DATABASE_URL`: `postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres`
   - `LLM_PROVIDER`: `openai_compatible`
   - `LLM_BASE_URL`: `https://api.groq.com/openai/v1`
   - `LLM_API_KEY`: `gsk_...` (Your Groq API key)
   - `MODEL_ID`: `llama-3.1-8b-instant`
   - `TRANSLATION_JUDGE_MODEL_ID`: `llama-3.1-8b-instant`
   - `TRANSLATION_MODEL_ID`: `llama-3.1-8b-instant`
   - `ALLOW_REMOTE_LLM`: `true`
   - `CORS_ORIGINS`: `*` (or your frontend domain once created)
4. Click **Deploy Web Service**.
5. Copy your live backend URL (e.g., `https://discharge-explainer-backend.onrender.com`).

---

## Step 4: Frontend on Vercel or Cloudflare Pages

### Option A: Vercel (Recommended)
1. Go to [vercel.com](https://vercel.com) and click **Add New...** ➔ **Project**.
2. Import your GitHub repository.
3. Configure the build:
   - **Root Directory:** Click edit and select `frontend`.
   - **Framework Preset:** `Next.js`
4. Under **Environment Variables**, add:
   - `NEXT_PUBLIC_API_BASE_URL`: `https://your-backend-name.onrender.com`
5. Click **Deploy**.

### Option B: Cloudflare Pages
1. Go to **Cloudflare Dashboard** ➔ **Workers & Pages** ➔ **Create application** ➔ **Pages** ➔ **Connect to Git**.
2. Select repository:
   - **Root directory:** `/frontend`
   - **Framework preset:** `Next.js`
   - **Build command:** `npm run build`
   - **Output directory:** `.next`
3. Add environment variable:
   - `NEXT_PUBLIC_API_BASE_URL`: `https://your-backend-name.onrender.com`
4. Deploy!

---

## Step 5: Verification & End-to-End Test

1. Visit your live frontend (`https://your-app.vercel.app`).
2. Paste a sample discharge summary or upload a document.
3. Click **Explain**.
4. The frontend calls Render ➔ Render processes the document with Tesseract OCR ➔ queries Groq LLM for simple language explanations and entailment judging ➔ saves state in Supabase PostgreSQL!
