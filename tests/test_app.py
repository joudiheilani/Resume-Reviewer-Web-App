"""Tests for the prompts, pipeline and API. The OpenRouter call is mocked, so no key is needed."""

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
import reviewer  # noqa: E402

RESUME = "Jane Doe\nB.S. Computer Science\nBuilt a Python web app used by 200 students.\n" * 2
JOB = "Software Engineering Intern. Requirements: Python, SQL, Git, REST APIs."
BODY = {"resume": RESUME, "job_description": JOB, "role_level": "internship"}


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


class FakeResponse:
    def __init__(self, status, content=None):
        self.status_code = status
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


# ---------- prompts ----------


def test_review_prompt_uses_persona():
    messages = reviewer.build_review_messages(RESUME, JOB, "internship")
    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith("Act as an experienced recruiter for entry-level")
    assert "INTERNSHIP" in messages[0]["content"]
    assert RESUME in messages[1]["content"] and JOB in messages[1]["content"]


def test_refine_prompt_contains_first_review_and_checklist():
    messages = reviewer.build_refine_messages(RESUME, JOB, "FIRST REVIEW TEXT", "entry_level")
    prompt = messages[1]["content"]
    assert "Here is the feedback you just wrote:\nFIRST REVIEW TEXT" in prompt
    assert "Now act as a strict editor" in prompt
    assert "1. Is any advice incorrect or unclear? Replace it with a specific example." in prompt
    assert "2. Did you miss any important keywords from the job description?" in prompt
    assert "3. Is the feedback too harsh or not impactful enough?" in prompt
    assert "output an improved final version of the feedback" in prompt
    assert "ENTRY-LEVEL" in messages[0]["content"]


def test_chat_prompt_includes_context_and_history():
    history = [{"role": "user", "content": "hi"}, {"role": "system", "content": "ignored"}]
    messages = reviewer.build_chat_messages(
        RESUME, JOB, "FEEDBACK", history, "What next?", "internship"
    )
    assert "FEEDBACK" in messages[0]["content"]
    assert [m["role"] for m in messages] == ["system", "user", "user"]
    assert messages[-1]["content"] == "What next?"


def test_additional_context_is_optional_and_used_in_every_prompt():
    plain = reviewer.build_review_messages(RESUME, JOB, "internship")
    assert "Additional context" not in plain[1]["content"]

    ctx = "Act as a hiring manager at a startup. Keep it to one page."
    review = reviewer.build_review_messages(RESUME, JOB, "internship", ctx)
    refine = reviewer.build_refine_messages(RESUME, JOB, "DRAFT", "internship", ctx)
    chat = reviewer.build_chat_messages(RESUME, JOB, "FB", [], "Q?", "internship", ctx)
    for content in (review[1]["content"], refine[1]["content"], chat[0]["content"]):
        assert ctx in content
        assert "never invent experience" in content
    assert "follows the candidate's additional context" in refine[1]["content"]


# ---------- model client ----------


def test_only_free_models_are_used(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-5, google/gemma-4-31b-it:free")
    assert reviewer.get_models() == ["google/gemma-4-31b-it:free"]
    monkeypatch.delenv("OPENROUTER_MODEL")
    assert all(m.endswith(":free") for m in reviewer.get_models())


def test_call_model_falls_back_when_rate_limited(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    responses = iter([FakeResponse(429), FakeResponse(200, "<think>x</think>## Overall Match\nok")])
    tried = []

    def fake_post(url, headers, json, timeout):
        tried.append(json["model"])
        assert headers["Authorization"] == "Bearer test-key"
        return next(responses)

    monkeypatch.setattr(reviewer.requests, "post", fake_post)
    text, model = reviewer.call_model([{"role": "user", "content": "hi"}])
    assert text == "## Overall Match\nok"
    assert model == reviewer.DEFAULT_MODELS[1] == tried[1]


def test_call_model_raises_when_all_fail(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(reviewer.requests, "post", lambda *a, **k: FakeResponse(429))
    with pytest.raises(reviewer.AIError):
        reviewer.call_model([{"role": "user", "content": "hi"}])


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(reviewer.AIError, match="OPENROUTER_API_KEY"):
        reviewer.call_model([])


def test_clean_output_strips_fences():
    assert reviewer.clean_output("```markdown\n## Hi\n```") == "## Hi"


# ---------- API ----------


def test_index(client):
    assert b"ResuMate" in client.get("/").data


def test_review_flow(client, monkeypatch):
    calls = []

    def fake_call(messages, **kwargs):
        calls.append(messages)
        return ("DRAFT" if len(calls) == 1 else "FINAL"), "model:free"

    monkeypatch.setattr(reviewer, "call_model", fake_call)
    draft = client.post("/api/review/draft", json=BODY)
    assert draft.status_code == 200 and draft.json["draft"] == "DRAFT"

    final = client.post(
        "/api/review/refine", json={**BODY, "draft": "DRAFT"}
    )
    assert final.status_code == 200 and final.json["feedback"] == "FINAL"
    assert "Here is the feedback you just wrote:\nDRAFT" in calls[1][1]["content"]


def test_review_validates_input(client):
    res = client.post("/api/review/draft", json={**BODY, "resume": "short"})
    assert res.status_code == 400
    assert "resume" in res.json["error"].lower()


def test_additional_context_reaches_both_passes(client, monkeypatch):
    seen = []
    monkeypatch.setattr(
        reviewer, "call_model", lambda messages, **k: (seen.append(messages) or "OUT", "m:free")
    )
    body = {**BODY, "additional_context": "  Focus on projects.  "}
    client.post("/api/review/draft", json=body)
    client.post("/api/review/refine", json={**body, "draft": "OUT"})
    assert all('"""\nFocus on projects.\n"""' in m[1]["content"] for m in seen)


@pytest.mark.parametrize("role", [None, "", "senior", 5])
def test_review_requires_role_level(client, role):
    res = client.post("/api/review/draft", json={**BODY, "role_level": role})
    assert res.status_code == 400
    assert "internship or entry level" in res.json["error"]


def test_ai_error_returns_503(client, monkeypatch):
    def boom(*a, **k):
        raise reviewer.AIError("busy")

    monkeypatch.setattr(reviewer, "call_model", boom)
    res = client.post("/api/review/draft", json=BODY)
    assert res.status_code == 503 and res.json["error"] == "busy"


def test_chat(client, monkeypatch):
    monkeypatch.setattr(reviewer, "call_model", lambda messages, **k: ("Answer", "m:free"))
    res = client.post(
        "/api/chat",
        json={
            **BODY,
            "feedback": "Some feedback",
            "history": [],
            "question": "How do I add SQL?",
        },
    )
    assert res.status_code == 200 and res.json["answer"] == "Answer"


def test_extract_txt_and_docx(client):
    res = client.post(
        "/api/extract",
        data={"file": (io.BytesIO(b"Hello resume"), "resume.txt")},
        content_type="multipart/form-data",
    )
    assert res.json["text"] == "Hello resume"

    from docx import Document

    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph("Docx resume line")
    doc.save(buf)
    buf.seek(0)
    res = client.post(
        "/api/extract", data={"file": (buf, "resume.docx")}, content_type="multipart/form-data"
    )
    assert "Docx resume line" in res.json["text"]


def test_extract_rejects_other_types(client):
    res = client.post(
        "/api/extract",
        data={"file": (io.BytesIO(b"x"), "resume.exe")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 400
