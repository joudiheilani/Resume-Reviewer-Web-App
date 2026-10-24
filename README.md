# Resume Reviewer

![CI](https://github.com/joudiheilani/Resume-Reviewer-Web-App/actions/workflows/ci.yml/badge.svg)

An AI-powered web app that reviews your resume against the job you're applying for. Upload or paste your resume, choose whether the job is an **internship** or **entry level**, paste the job description, and get:

- a **match score** and summary of how well your resume fits the role,
- **strengths (pros)** and **areas to improve (cons)** in relation to the job description,
- a table of **missing keywords** with where to add them,
- concrete **before → after edits** (rewrites, additions and removals),
- the **top 3 next steps**,
- and a **chat** where you can ask the AI recruiter follow-up questions about your resume and the feedback.

The AI runs on a free model from [OpenRouter](https://openrouter.ai/collections/free-models).

## How it works

```
                 ┌──────────────────────────────────────────────┐
 Resume + Job ──►│ Pass 1 · Persona                             │──► First draft
                 │ "Act as an experienced recruiter for         │
                 │  entry-level and internship roles…"          │
                 └──────────────────────────────────────────────┘
                                     │
                                     ▼
                 ┌──────────────────────────────────────────────┐
                 │ Pass 2 · Iterative Refinement                │──► Final feedback
                 │ "Here is the feedback you just wrote: …      │
                 │  Now act as a strict editor. Check it for…"  │
                 └──────────────────────────────────────────────┘
                                     │
                                     ▼
                 ┌──────────────────────────────────────────────┐
 Your question ─►│ Follow-up chat (same recruiter persona, with │──► Answer
                 │ resume, job description and final feedback)  │
                 └──────────────────────────────────────────────┘
```

### Prompt engineering techniques

**1. Persona.** Every request uses this system prompt, so the model answers with a recruiter's judgment and an encouraging, specific tone:

> Act as an experienced recruiter for entry-level and internship roles. You have reviewed thousands of resumes, and know exactly what to look for in a polished resume. Provide helpful, encouraging, and specific feedback on the resume, with an emphasis on tailoring the resume to that job description.

The persona is extended with guidance for the role type the user picks. For an **internship** it weighs coursework, projects, GPA and availability more than work history; for **entry level** it looks for internships, measurable impact and full-time readiness.

The first pass also asks for a fixed Markdown structure (Overall Match, Strengths, Areas to Improve, Missing Keywords, Suggested Edits, Next Steps) so the UI can display each part clearly.

**2. Iterative Refinement.** The first review is sent back to the model in a second request:

> Here is the feedback you just wrote:
> [first review goes here]
>
> Now act as a strict editor. Check it for these problems:
> 1. Is any advice incorrect or unclear? Replace it with a specific example.
> 2. Did you miss any important keywords from the job description?
> 3. Is the feedback too harsh or not impactful enough?
>
> Then output an improved final version of the feedback.

The resume and job description are included again so the editor can check keywords against the source. In the app, the **Final feedback / First draft** toggle lets you compare the two versions and see what the refinement pass changed.

Both prompts live in [`reviewer.py`](reviewer.py).

## Features

- **Internship or Entry level:** the user picks the role type before pasting the job description, and the feedback is tailored to it.
- **Upload or paste:** PDF, DOCX or TXT (up to 4 MB). Extracted text is shown so you can check and edit it before the review.
- **Two-step progress:** the UI shows which pass is running (recruiter review, then editor check).
- **Clear results:** colour-coded sections, a match-score ring, keyword table, and copy / download as Markdown.
- **Ask the recruiter:** a chat beside the feedback with suggested questions ("Rewrite my weakest bullet point", "Write a professional summary for this job", …). It remembers the conversation.
- **Try with a sample:** fills in an example resume and job posting so you can see how it works.
- **Reliable on free models:** free models are often rate-limited, so the app tries several free models in order until one answers. If the editor pass fails, you still get the first review.
- **Revi the robot mascot:** an animated robot in the corner. Click it for quick answers to common questions (how it works, which role type to pick, file types, the match score, privacy, and more).
- Light and dark mode, and a layout that works on phones.

## Tech stack

| Layer    | Technology |
| -------- | ---------- |
| Frontend | HTML, CSS, vanilla JavaScript, [marked](https://marked.js.org/) + [DOMPurify](https://github.com/cure53/DOMPurify) to render the AI's Markdown safely |
| Backend  | Python, [Flask](https://flask.palletsprojects.com/) |
| AI       | [OpenRouter](https://openrouter.ai) chat completions API, free models (`:free`) |
| Files    | [pypdf](https://pypdf.readthedocs.io/) and [python-docx](https://python-docx.readthedocs.io/) for text extraction |
| Config   | [python-dotenv](https://github.com/theskumar/python-dotenv) loads the API key from `.env` |
| Tests/CI | pytest (the AI call is mocked), GitHub Actions |

## Project structure

```
Resume-Reviewer-Web-App/
├── app.py              # Flask server: pages, file upload, review and chat endpoints
├── reviewer.py         # Prompts (Persona + Iterative Refinement) and OpenRouter client
├── templates/
│   └── index.html      # Single-page UI, including the robot mascot (animated SVG)
├── public/static/      # Served by Vercel's CDN in production, by Flask locally
│   ├── style.css
│   └── app.js          # Upload, role picker, two-pass review flow, results, chat, FAQ
├── tests/
│   └── test_app.py
├── .vercelignore      # Keeps .env and tests out of Vercel uploads
├── .env.example        # Template for your .env (the real .env is git-ignored)
├── requirements.txt
└── requirements-dev.txt
```

## Getting started

**Requirements:** Python 3.10+ and a free [OpenRouter API key](https://openrouter.ai/keys).

1. Clone the repository and install the dependencies:

   ```bash
   git clone https://github.com/joudiheilani/Resume-Reviewer-Web-App.git
   cd Resume-Reviewer-Web-App
   pip install -r requirements.txt
   ```

2. Create a `.env` file next to `app.py` (copy `.env.example`) and add your key:

   ```
   OPENROUTER_API_KEY=your-key-here
   ```

   The key is loaded with `python-dotenv` and is never hard-coded or sent to the browser. `.env` is listed in `.gitignore`.

3. Run the app and open http://127.0.0.1:5000:

   ```bash
   python app.py
   ```

### Choosing a model

By default the app tries these free models in order:

1. `nvidia/nemotron-3-ultra-550b-a55b:free`
2. `google/gemma-4-31b-it:free`
3. `nvidia/nemotron-3.5-lightning:free`
4. `dots-studio/dots-3-note-preview:free`

The free model list changes over time. To use different ones, set `OPENROUTER_MODEL` in `.env` to a comma-separated list. Only model IDs ending in `:free` are accepted.

```
OPENROUTER_MODEL=google/gemma-4-31b-it:free,nvidia/nemotron-3-ultra-550b-a55b:free
```

## API

| Method | Path                 | Body                                                           | Returns |
| ------ | -------------------- | -------------------------------------------------------------- | ------- |
| POST   | `/api/extract`       | multipart `file` (PDF, DOCX, TXT)                              | `{text}` |
| POST   | `/api/review/draft`  | `{resume, job_description, role_level}`                        | `{draft, model}`: Persona pass |
| POST   | `/api/review/refine` | `{resume, job_description, role_level, draft}`                 | `{feedback, model}`: Iterative Refinement pass |
| POST   | `/api/chat`          | `{resume, job_description, role_level, feedback, history, question}` | `{answer, model}` |

`role_level` is `"internship"` or `"entry_level"`. Errors return `{error}` with status 400 (bad input), 413 (file too large) or 503 (all AI models busy).

## Deploying to Vercel (free)

The app runs on Vercel's free Hobby plan using its built-in Flask support. No `vercel.json` is needed.

1. Go to [vercel.com/new](https://vercel.com/new) and import the `Resume-Reviewer-Web-App` GitHub repository.
2. Leave the framework preset as detected (Flask) and the root directory as `./`.
3. Under **Environment Variables**, add `OPENROUTER_API_KEY` with your key. (Optional: `OPENROUTER_MODEL`.)
4. Click **Deploy**. Every push to `main` deploys again automatically.

Notes:

- `.env` is never uploaded (`.gitignore` and `.vercelignore`); the key only lives in Vercel's environment variables.
- Static files are in `public/static/` so Vercel serves them from its CDN.
- A review makes two AI calls of up to ~100 seconds each. That fits within Vercel's default function time limit with Fluid compute (300 seconds), which is on by default for new projects.
- Uploads are capped at 4 MB because Vercel limits request bodies to 4.5 MB.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests mock the OpenRouter request, so they don't need an API key. They check that both prompt patterns are built correctly, that the app falls back to the next free model when one is rate-limited, input validation, file extraction and the API endpoints.

## Privacy and limitations

- Your resume and job description are sent to OpenRouter and the selected model provider to generate feedback. Nothing is stored by this app; refreshing the page clears everything.
- Free models can be slow (a full review usually takes 1–3 minutes) or temporarily unavailable.
- AI feedback can be wrong. Review each suggestion, and only add skills and experience you really have.
