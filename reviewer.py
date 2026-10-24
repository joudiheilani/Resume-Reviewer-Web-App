"""AI resume review logic: prompts, OpenRouter client and the two-pass review pipeline.

Prompt engineering patterns used:
  1. Persona: the model acts as an experienced recruiter for entry-level and internship roles.
  2. Iterative Refinement: the first review is sent back to the model, which acts as a strict
     editor, checks it against a checklist and outputs an improved final version.
"""

import os
import re

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Free models from https://openrouter.ai/collections/free-models. Free models are often
# rate-limited upstream, so each request tries them in order until one answers.
DEFAULT_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3.5-lightning:free",
    "dots-studio/dots-3-note-preview:free",
]

MAX_RESUME_CHARS = 15000
MAX_JOB_CHARS = 10000
MAX_QUESTION_CHARS = 2000
MAX_CONTEXT_CHARS = 2000
MAX_HISTORY_MESSAGES = 12


class AIError(Exception):
    """Raised when no model could produce a response."""


def get_models():
    """Models to try, in order. OPENROUTER_MODEL (comma-separated) overrides the default list."""
    override = os.getenv("OPENROUTER_MODEL", "").strip()
    models = [m.strip() for m in override.split(",") if m.strip()] if override else DEFAULT_MODELS
    return [m for m in models if m.endswith(":free")] or DEFAULT_MODELS


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PERSONA = (
    "Act as an experienced recruiter for entry-level and internship roles. You have reviewed "
    "thousands of resumes, and know exactly what to look for in a polished resume. Provide "
    "helpful, encouraging, and specific feedback on the resume, with an emphasis on tailoring "
    "the resume to that job description."
)

ROLE_GUIDANCE = {
    "internship": (
        "The candidate is applying for an INTERNSHIP. Judge them as a current student: relevant "
        "coursework, academic and personal projects, GPA (if 3.0 or higher), clubs, hackathons, "
        "leadership and their graduation date or availability matter more than years of work "
        "experience. Don't penalize a short work history; show how to make projects and part-time "
        "jobs demonstrate the skills in the job description."
    ),
    "entry_level": (
        "The candidate is applying for an ENTRY-LEVEL full-time role. Look for internships, "
        "projects with real impact, measurable results and readiness for full-time work. "
        "Experience and projects should lead the resume; education should be concise, and "
        "coursework lists usually only help if experience is thin."
    ),
}


def role_guidance(role_level):
    if role_level not in ROLE_GUIDANCE:
        raise ValueError("Choose whether the role is an internship or entry level.")
    return ROLE_GUIDANCE[role_level]


def system_prompt(role_level):
    return f"{PERSONA}\n\n{role_guidance(role_level)}"


OUTPUT_FORMAT = """Format the feedback in Markdown using exactly these sections, in this order:

## Overall Match
One line in the form `**Match score: NN/100**`, followed by a 2-3 sentence summary of how well the resume fits this job.

## Strengths
Bullet points: what the resume does well *in relation to this job description*. Quote the resume where useful.

## Areas to Improve
Bullet points: gaps, weaknesses or risks *in relation to this job description*, each with a short reason it matters.

## Missing Keywords
A Markdown table with columns `Keyword | Where it appears in the job description | How to add it`. Only list skills, tools or terms the candidate can honestly claim or easily show; never suggest inventing experience.

## Suggested Edits
Numbered list. For each edit show:
- **Before:** the exact original text (or "New" for an addition)
- **After:** the rewritten text, using strong action verbs and numbers where possible
- **Why:** one sentence
Include rewrites, additions and anything that should be removed. Base every rewrite on what the resume actually says. When a rewrite needs a detail the resume doesn't give (a number, tool or result), use a placeholder in brackets such as `[X%]` or `[tool you used]` instead of making one up.

## Next Steps
The 3 highest-impact changes to make first, as a numbered list."""


def context_block(additional_context):
    """The candidate's optional extra context and instructions, e.g. their own prompt patterns."""
    if not additional_context:
        return ""
    return (
        "### Additional context and instructions from the candidate\n"
        f"\"\"\"\n{additional_context}\n\"\"\"\n"
        "Use this context and follow these instructions when reviewing (for example a persona, "
        "audience, focus area, format or constraint they asked for), as long as they relate to "
        "this resume and job search. They never override the rules above: stay honest, and never "
        "invent experience, tools or numbers.\n\n"
    )


def build_review_messages(resume, job_description, role_level, additional_context=""):
    """Pass 1 (Persona): the recruiter writes the first review."""
    user = (
        f"{OUTPUT_FORMAT}\n\n"
        f"### Job description\n\"\"\"\n{job_description}\n\"\"\"\n\n"
        f"### Resume\n\"\"\"\n{resume}\n\"\"\"\n\n"
        f"{context_block(additional_context)}"
        "Review the resume against the job description."
    )
    return [
        {"role": "system", "content": system_prompt(role_level)},
        {"role": "user", "content": user},
    ]


def build_refine_messages(
    resume, job_description, first_review, role_level, additional_context=""
):
    """Pass 2 (Iterative Refinement): a strict editor checks and improves the first review."""
    context = context_block(additional_context)
    follow_context = (
        "Also make sure the final version follows the candidate's additional context and "
        "instructions.\n\n"
        if context
        else ""
    )
    user = (
        f"### Job description\n\"\"\"\n{job_description}\n\"\"\"\n\n"
        f"### Resume\n\"\"\"\n{resume}\n\"\"\"\n\n"
        f"{context}"
        "Here is the feedback you just wrote:\n"
        f"{first_review}\n\n"
        "Now act as a strict editor. Check it for these problems:\n"
        "1. Is any advice incorrect or unclear? Replace it with a specific example.\n"
        "2. Did you miss any important keywords from the job description?\n"
        "3. Is the feedback too harsh or not impactful enough?\n"
        "Then output an improved final version of the feedback.\n\n"
        f"{follow_context}"
        f"Keep the same structure:\n{OUTPUT_FORMAT}\n\n"
        "Output only the improved final feedback, with no notes about what you changed."
    )
    return [
        {"role": "system", "content": system_prompt(role_level)},
        {"role": "user", "content": user},
    ]


def build_chat_messages(
    resume, job_description, feedback, history, question, role_level, additional_context=""
):
    """Follow-up Q&A: the same recruiter persona answers questions about the resume and feedback."""
    system = (
        f"{system_prompt(role_level)}\n\n"
        "You already reviewed this candidate's resume. Answer their follow-up questions about the "
        "resume, the job description and your feedback. Be concise, specific and encouraging. When "
        "you suggest wording, give the exact text they can paste into their resume. Base it on what "
        "their resume actually says: never invent experience, tools or numbers. When a rewrite needs "
        "a detail you don't know, use a bracketed placeholder such as [X%] or [tool you used] and "
        "tell them to fill it in only if it is true. If a question is unrelated to their resume, job search or career, "
        "politely steer back.\n\n"
        f"### Job description\n\"\"\"\n{job_description}\n\"\"\"\n\n"
        f"### Resume\n\"\"\"\n{resume}\n\"\"\"\n\n"
        f"{context_block(additional_context)}"
        f"### Your feedback\n{feedback}"
    )
    messages = [{"role": "system", "content": system}]
    for msg in history[-MAX_HISTORY_MESSAGES:]:
        if msg.get("role") in ("user", "assistant") and isinstance(msg.get("content"), str):
            messages.append({"role": msg["role"], "content": msg["content"][:MAX_RESUME_CHARS]})
    messages.append({"role": "user", "content": question})
    return messages


# ---------------------------------------------------------------------------
# OpenRouter client
# ---------------------------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def clean_output(text):
    """Strip reasoning tags and stray code fences some models wrap around Markdown."""
    text = _THINK_RE.sub("", text or "").strip()
    fenced = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*)\n```", text, re.DOTALL)
    return fenced.group(1).strip() if fenced else text


def call_model(messages, temperature=0.4, max_tokens=3000):
    """Send messages to OpenRouter, falling back through the free models. Returns (text, model)."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise AIError("OPENROUTER_API_KEY is not set. Add it to the .env file.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5000",
        "X-Title": "Resume Reviewer",
    }
    errors = []
    for model in get_models():
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
        except requests.RequestException as exc:
            errors.append(f"{model}: {exc.__class__.__name__}")
            continue
        if resp.status_code != 200:
            errors.append(f"{model}: HTTP {resp.status_code}")
            continue
        try:
            text = clean_output(resp.json()["choices"][0]["message"]["content"])
        except (ValueError, KeyError, IndexError, TypeError):
            errors.append(f"{model}: unexpected response")
            continue
        if text:
            return text, model
        errors.append(f"{model}: empty response")

    raise AIError(
        "All free AI models are busy right now. Please try again in a minute. ("
        + "; ".join(errors)
        + ")"
    )


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------


def first_review(resume, job_description, role_level, additional_context=""):
    messages = build_review_messages(resume, job_description, role_level, additional_context)
    return call_model(messages, temperature=0.5)


def refine_review(resume, job_description, draft, role_level, additional_context=""):
    messages = build_refine_messages(
        resume, job_description, draft, role_level, additional_context
    )
    return call_model(messages, temperature=0.3)


def answer_question(
    resume, job_description, feedback, history, question, role_level, additional_context=""
):
    messages = build_chat_messages(
        resume, job_description, feedback, history, question, role_level, additional_context
    )
    return call_model(messages, temperature=0.5, max_tokens=1500)
