(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const el = {
    inputSection: $("#input-section"),
    progressSection: $("#progress-section"),
    resultsSection: $("#results-section"),
    dropzone: $("#dropzone"),
    fileInput: $("#file-input"),
    fileStatus: $("#file-status"),
    resume: $("#resume"),
    job: $("#job"),
    resumeCount: $("#resume-count"),
    jobCount: $("#job-count"),
    reviewBtn: $("#review-btn"),
    sampleBtn: $("#sample-btn"),
    inputError: $("#input-error"),
    stage1: $("#stage-1"),
    stage2: $("#stage-2"),
    feedback: $("#feedback"),
    viewNote: $("#view-note"),
    resultsMeta: $("#results-meta"),
    score: $("#score"),
    scoreBar: $("#score-bar"),
    scoreValue: $("#score-value"),
    modelName: $("#model-name"),
    chatLog: $("#chat-log"),
    chatForm: $("#chat-form"),
    chatInput: $("#chat-input"),
    chips: $("#chips"),
    toast: $("#toast"),
  };

  const state = {
    mode: "upload",
    filename: "",
    draft: "",
    feedback: "",
    view: "final",
    history: [],
    busy: false,
  };

  // ---------- helpers ----------

  async function api(path, options) {
    let res;
    try {
      res = await fetch(path, options);
    } catch {
      throw new Error("Could not reach the server. Is the app still running?");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status}).`);
    return data;
  }

  function postJSON(path, body) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  function renderMarkdown(md) {
    return DOMPurify.sanitize(marked.parse(md || ""));
  }

  let toastTimer;
  function toast(message) {
    el.toast.textContent = message;
    el.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.toast.hidden = true), 2200);
  }

  function setStep(n) {
    $$(".step").forEach((s) => {
      const step = Number(s.dataset.step);
      s.classList.toggle("is-active", step === n);
      s.classList.toggle("is-done", step < n);
    });
  }

  function show(section) {
    for (const s of [el.inputSection, el.progressSection, el.resultsSection]) {
      s.hidden = s !== section;
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function showError(message) {
    el.inputError.textContent = message;
    el.inputError.hidden = !message;
  }

  function updateCounts() {
    el.resumeCount.textContent = `${el.resume.value.length.toLocaleString()} characters`;
    el.jobCount.textContent = `${el.job.value.length.toLocaleString()} characters`;
  }

  // ---------- resume input: upload or paste ----------

  function setMode(mode) {
    state.mode = mode;
    $$("[data-mode]").forEach((b) => {
      const on = b.dataset.mode === mode;
      b.classList.toggle("is-on", on);
      b.setAttribute("aria-selected", on);
    });
    const hasText = el.resume.value.trim().length > 0;
    el.dropzone.hidden = mode !== "upload" || (state.filename && hasText);
    el.fileStatus.hidden = mode !== "upload" || !state.filename;
    el.resume.hidden = mode === "upload" && !(state.filename && hasText);
    if (mode === "paste") el.resume.focus();
  }

  function setFileStatus(html, isError) {
    el.fileStatus.innerHTML = html;
    el.fileStatus.classList.toggle("is-error", !!isError);
    el.fileStatus.hidden = false;
  }

  async function handleFile(file) {
    if (!file) return;
    showError("");
    state.filename = file.name;
    setFileStatus(`Reading <strong></strong>…`);
    el.fileStatus.querySelector("strong").textContent = file.name;
    el.dropzone.hidden = true;
    const form = new FormData();
    form.append("file", file);
    try {
      const data = await api("/api/extract", { method: "POST", body: form });
      el.resume.value = data.text;
      setFileStatus(
        `✓ <span>Loaded <strong></strong>. Check the text below and edit if needed.</span>` +
          `<button type="button" class="btn btn-ghost btn-sm" id="replace-file">Replace</button>`
      );
      el.fileStatus.querySelector("strong").textContent = file.name;
      el.resume.hidden = false;
    } catch (err) {
      state.filename = "";
      el.resume.value = "";
      setFileStatus(`<span></span>`, true);
      el.fileStatus.querySelector("span").textContent = err.message;
      el.dropzone.hidden = false;
    }
    updateCounts();
  }

  el.fileStatus.addEventListener("click", (e) => {
    if (e.target.id !== "replace-file") return;
    state.filename = "";
    el.resume.value = "";
    el.fileInput.value = "";
    updateCounts();
    setMode("upload");
    el.fileInput.click();
  });

  $$("[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  el.fileInput.addEventListener("change", () => handleFile(el.fileInput.files[0]));
  ["dragenter", "dragover"].forEach((type) =>
    el.dropzone.addEventListener(type, (e) => {
      e.preventDefault();
      el.dropzone.classList.add("is-over");
    })
  );
  ["dragleave", "drop"].forEach((type) =>
    el.dropzone.addEventListener(type, (e) => {
      e.preventDefault();
      el.dropzone.classList.remove("is-over");
    })
  );
  el.dropzone.addEventListener("drop", (e) => handleFile(e.dataTransfer.files[0]));
  el.resume.addEventListener("input", updateCounts);
  el.job.addEventListener("input", updateCounts);

  // ---------- review pipeline ----------

  function validate() {
    const resume = el.resume.value.trim();
    const job = el.job.value.trim();
    if (resume.length < 50) return "Add your resume first: upload a file or paste at least a few lines of text.";
    if (job.length < 30) return "Paste the job description so the feedback can be tailored to the role.";
    return "";
  }

  function setStage(stageEl, status) {
    stageEl.classList.toggle("is-active", status === "active");
    stageEl.classList.toggle("is-done", status === "done");
  }

  async function runReview() {
    const problem = validate();
    if (problem) return showError(problem);
    if (state.busy) return;
    showError("");
    state.busy = true;

    const payload = { resume: el.resume.value.trim(), job_description: el.job.value.trim() };
    setStep(2);
    show(el.progressSection);
    setStage(el.stage1, "active");
    setStage(el.stage2, "");

    try {
      // Pass 1: Persona (recruiter) writes the first review.
      const first = await postJSON("/api/review/draft", payload);
      state.draft = first.draft;
      setStage(el.stage1, "done");
      setStage(el.stage2, "active");

      // Pass 2: Iterative Refinement (strict editor) improves it.
      let models = [first.model];
      try {
        const refined = await postJSON("/api/review/refine", { ...payload, draft: first.draft });
        state.feedback = refined.feedback;
        models.push(refined.model);
        setStage(el.stage2, "done");
      } catch (err) {
        // Still useful: fall back to the first review rather than losing it.
        state.feedback = first.draft;
        toast("The editor pass failed, so you're seeing the first review.");
      }

      el.modelName.textContent = models[models.length - 1];
      el.resultsMeta.textContent = `Generated by ${[...new Set(models)].join(" and ")}`;
      state.history = [];
      resetChat();
      setView("final");
      setStep(3);
      show(el.resultsSection);
    } catch (err) {
      setStep(1);
      show(el.inputSection);
      showError(err.message);
    } finally {
      state.busy = false;
    }
  }

  el.reviewBtn.addEventListener("click", runReview);
  $("#rerun-btn").addEventListener("click", runReview);
  $("#edit-btn").addEventListener("click", () => {
    setStep(1);
    show(el.inputSection);
  });
  $("#reset-btn").addEventListener("click", () => {
    el.resume.value = "";
    el.job.value = "";
    el.fileInput.value = "";
    state.filename = "";
    el.fileStatus.hidden = true;
    state.draft = state.feedback = "";
    updateCounts();
    setMode("upload");
    setStep(1);
    show(el.inputSection);
  });

  // ---------- results rendering ----------

  function sectionClass(heading) {
    const h = heading.toLowerCase();
    if (h.includes("strength") || h.includes("pros")) return "fb-good";
    if (h.includes("improve") || h.includes("cons") || h.includes("weakness") || h.includes("gap")) return "fb-warn";
    if (h.includes("keyword")) return "fb-info";
    return "";
  }

  function renderFeedback(md) {
    const tmp = document.createElement("div");
    tmp.innerHTML = renderMarkdown(md);

    // Group each <h2> and its following content into a coloured card.
    const out = document.createDocumentFragment();
    let section = null;
    for (const node of [...tmp.childNodes]) {
      if (node.nodeName === "H1" || node.nodeName === "H2") {
        const h2 = document.createElement("h2");
        h2.innerHTML = node.innerHTML;
        section = document.createElement("section");
        section.className = `fb-section ${sectionClass(node.textContent)}`;
        section.appendChild(h2);
        out.appendChild(section);
      } else if (section) {
        section.appendChild(node);
      } else if (node.nodeType !== Node.TEXT_NODE || node.textContent.trim()) {
        section = document.createElement("section");
        section.className = "fb-section";
        section.appendChild(node);
        out.appendChild(section);
      }
    }
    out.querySelectorAll("table").forEach((t) => {
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      t.replaceWith(wrap);
      wrap.appendChild(t);
    });
    el.feedback.replaceChildren(out);

    const match = md.match(/match score[^0-9]{0,10}(\d{1,3})\s*\/\s*100/i);
    if (match) {
      const score = Math.min(100, Number(match[1]));
      el.score.hidden = false;
      el.score.dataset.level = score >= 75 ? "good" : score >= 50 ? "warn" : "bad";
      el.scoreValue.textContent = score;
      el.score.title = `Match score: ${score}/100`;
      el.scoreBar.setAttribute("stroke-dasharray", "0 100");
      requestAnimationFrame(() => el.scoreBar.setAttribute("stroke-dasharray", `${score} 100`));
    } else {
      el.score.hidden = true;
    }
  }

  function setView(view) {
    state.view = view;
    $$("[data-view]").forEach((b) => {
      const on = b.dataset.view === view;
      b.classList.toggle("is-on", on);
      b.setAttribute("aria-selected", on);
    });
    el.viewNote.textContent =
      view === "final"
        ? "Refined by a second AI pass acting as a strict editor."
        : "The recruiter's first review, before the editor pass. Compare it with the final version.";
    renderFeedback(view === "final" ? state.feedback : state.draft);
  }

  $$("[data-view]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));

  function currentText() {
    return state.view === "final" ? state.feedback : state.draft;
  }

  $("#copy-btn").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(currentText());
      toast("Feedback copied to clipboard");
    } catch {
      toast("Couldn't copy. Select the text and copy it manually.");
    }
  });

  $("#download-btn").addEventListener("click", () => {
    const blob = new Blob([currentText()], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = state.view === "final" ? "resume-feedback.md" : "resume-feedback-draft.md";
    a.click();
    URL.revokeObjectURL(a.href);
  });

  // ---------- follow-up chat ----------

  function addMessage(role, content, { markdown = false, error = false } = {}) {
    const msg = document.createElement("div");
    msg.className = `msg ${role === "user" ? "msg-user" : "msg-ai"}${error ? " msg-error" : ""}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    if (markdown) bubble.innerHTML = renderMarkdown(content);
    else bubble.textContent = content;
    msg.appendChild(bubble);
    el.chatLog.appendChild(msg);
    el.chatLog.scrollTop = el.chatLog.scrollHeight;
    return msg;
  }

  function resetChat() {
    el.chatLog.replaceChildren();
    addMessage(
      "assistant",
      "Hi! I've reviewed your resume. Ask me anything, such as how to reword a bullet or where a keyword should go."
    );
    el.chips.hidden = false;
  }

  async function ask(question) {
    question = question.trim();
    if (!question || state.busy) return;
    state.busy = true;
    el.chips.hidden = true;
    el.chatInput.value = "";
    autoGrow();
    addMessage("user", question);
    const typing = addMessage("assistant", "");
    typing.querySelector(".bubble").innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
    const sendBtn = el.chatForm.querySelector("button");
    sendBtn.disabled = true;

    try {
      const data = await postJSON("/api/chat", {
        resume: el.resume.value.trim(),
        job_description: el.job.value.trim(),
        feedback: state.feedback,
        history: state.history,
        question,
      });
      typing.remove();
      addMessage("assistant", data.answer, { markdown: true });
      state.history.push({ role: "user", content: question }, { role: "assistant", content: data.answer });
    } catch (err) {
      typing.remove();
      addMessage("assistant", err.message, { error: true });
    } finally {
      state.busy = false;
      sendBtn.disabled = false;
      el.chatInput.focus();
    }
  }

  function autoGrow() {
    el.chatInput.style.height = "auto";
    el.chatInput.style.height = `${Math.min(el.chatInput.scrollHeight, 140)}px`;
    el.chatInput.style.overflowY = el.chatInput.scrollHeight > 140 ? "auto" : "hidden";
  }

  el.chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    ask(el.chatInput.value);
  });
  el.chatInput.addEventListener("input", autoGrow);
  el.chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      ask(el.chatInput.value);
    }
  });
  el.chips.addEventListener("click", (e) => {
    if (e.target.classList.contains("chip")) ask(e.target.textContent);
  });

  // ---------- sample data ----------

  const SAMPLE_RESUME = `Alex Rivera
alex.rivera@email.com | (555) 123-4567 | linkedin.com/in/alexrivera | github.com/arivera

EDUCATION
State University, B.S. Computer Science, Expected May 2027
GPA: 3.6/4.0. Relevant coursework: Data Structures, Databases, Web Development, Statistics

EXPERIENCE
IT Help Desk Assistant, State University IT Services (Sep 2025 - Present)
- Helped students and staff with computer problems
- Responsible for resetting passwords and setting up laptops
- Wrote some guides for common issues

Cashier, FreshMart Grocery (Jun 2023 - Aug 2025)
- Handled cash and card transactions
- Worked in a fast paced environment

PROJECTS
Budget Tracker Web App
- Made a website to track spending using JavaScript and HTML
- Used a database to save data

Movie Recommendation Script
- Python script that recommends movies based on ratings

SKILLS
Python, JavaScript, HTML/CSS, Microsoft Office, Teamwork, Communication`;

  const SAMPLE_JOB = `Software Engineering Intern (Summer 2027) - BrightPath Analytics

About the role
Join our product engineering team to build features for our data analytics platform used by 2,000+ businesses. You'll ship real code, participate in code reviews and work in an Agile team.

Responsibilities
- Build and maintain REST APIs and front-end components using Python (Flask/Django) and React
- Write unit tests and contribute to our CI/CD pipeline
- Work with SQL databases (PostgreSQL) to query and model data
- Collaborate with designers and product managers in two-week sprints
- Document your work and present a project demo at the end of the internship

Qualifications
- Pursuing a B.S. in Computer Science or related field, graduating 2027 or 2028
- Experience with Python and JavaScript through coursework or projects
- Familiarity with Git and version control
- Understanding of data structures and algorithms
- Strong communication and problem-solving skills

Nice to have
- Experience with React, REST APIs or cloud platforms (AWS, GCP)
- Exposure to data analysis libraries such as pandas`;

  el.sampleBtn.addEventListener("click", () => {
    state.filename = "";
    el.resume.value = SAMPLE_RESUME;
    el.job.value = SAMPLE_JOB;
    el.fileStatus.hidden = true;
    setMode("paste");
    updateCounts();
    showError("");
    toast("Sample resume and job description added");
  });

  // ---------- init ----------
  marked.setOptions({ gfm: true, breaks: false });
  setMode("upload");
  updateCounts();
})();
