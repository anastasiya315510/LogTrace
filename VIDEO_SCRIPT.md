wipu# LogTrace — Demo Video Script
**Target length: ~2:45 — stay under 3:00**

---

## SCENE 1 — The Problem (0:00 – 0:20)

> *Screen: red error logs scrolling fast in a terminal.*

**Say:**
"It's 2am. Your payment service is down. Orders are failing.
You have hundreds of error lines across five services — and somewhere in there is the one thing that started it all.

Finding it takes your team hours. LogTrace fixes that."

---

## SCENE 2 — Start Demo + Architecture (0:20 – 1:20)

> *Screen: LogTrace portal, Live Demo tab.*

**Say:**
"Let me start the demo now — I'll trigger a cascade failure across three services."

> *Click Start Demo. Then immediately switch to the architecture diagram.*

"While the producers spin up, let me show you what's happening under the hood."

> *Screen: architecture diagram. Point at each part as you say it.*

"Your services send logs to LogTrace — ingested in under 50 milliseconds straight into **Redis Streams** on a **Nebius VM**.

A stream processor watches continuously. The moment it sees an error spike — ten errors in sixty seconds — it fires automatically. No one has to click anything.

Then the AI pipeline runs.
**Nemotron Nano 8B on Nebius Token Factory** batch-classifies every event.
**Nemotron Ultra 253B on Nebius Token Factory** reads the full incident and writes the root cause.
**Tavily** pulls live fix suggestions from the web.
Raw logs are archived in **Nebius Object Storage**."

> *Switch back to portal — logs are now flooding in, all three services red.*

"And here it is — the cascade is live."

---

## SCENE 3 — Watching It Run (1:20 – 1:50)

> *Screen: portal, logs tab flooding with red events.*

**Say:**
"payment-service, order-service, api-gateway — all failing at the same time.
The spike detector already fired. Stage 1 is running — grouping events by trace ID, building the service dependency map, storing the incident in **PostgreSQL**.

Watch the progress bar — every step streams live over **Server-Sent Events**."

> *Progress bar reaches 100%. Incident card appears.*

---

## SCENE 4 — Root Cause Analysis (1:30 – 2:10)

> *Screen: Incident report. RCA text streaming word by word. Confidence score visible.*

> 🔧 **Tech in play:** Nemotron Nano 8B · Nemotron Ultra 253B · Nebius Token Factory · Tavily · SSE

**Say:**
"Stage 2 starts with **Nemotron Nano 8B on Nebius Token Factory** — it batch-classifies every single error event. Fast, parallel, done in seconds.

Then **Nemotron Ultra 253B on Nebius Token Factory** takes over — 253 billion parameters reasoning through the full incident. You can see it writing word by word, streamed live.

Root cause: the database connection pool in the payment service ran out. That crashed the order service. That crashed the API gateway. A full cascade.

Below the analysis — fix suggestions pulled live from the web by **Tavily**.

From first error to full report: under two minutes."

---

## SCENE 5 — This Is Production-Ready (2:10 – 2:30)

> *Screen: Streamlit portal sidebar showing a list of past incidents.*

**Say:**
"Here's what makes this useful in a real environment.

There's no reset button in production. The moment the debounce window clears — two minutes after the last spike — LogTrace is watching again. A second incident triggers a second report, automatically. Every spike gets its own root cause analysis, stored in Postgres, visible here in the sidebar.

Your on-call engineer wakes up to a list of incidents — each one already diagnosed. Not raw logs. Not alerts. Answers."

---

## SCENE 6 — Closing (2:30 – 2:45)

> *Screen: stay on the completed incident report.*

> 🔧 **Tech in play:** Nebius VM · Docker · all of the above

**Say:**
"This is not a chatbot. It's a full automated pipeline — log ingestion, spike detection, service topology, AI classification, multi-turn reasoning — no human in the loop.

The whole stack — FastAPI, Redis, Postgres, Nginx — runs in Docker on a **Nebius VM**. One command to start.

LogTrace brings mean time to resolution from hours to minutes."

---

## KEY PHRASES — say these out loud
*(required by hackathon rules)*

- "Nemotron Nano 8B on Nebius Token Factory"
- "Nemotron Ultra 253B on Nebius Token Factory"
- "Nebius Object Storage"
- "Tavily"

---

## BEFORE YOU RECORD — checklist

- [ ] Architecture diagram is open and readable on screen
- [ ] Demo cascade runs live (not pre-recorded)
- [ ] Progress bar animates in real time
- [ ] RCA text streams word by word
- [ ] Confidence score is visible and > 0
- [ ] Streamlit sidebar shows list of past incidents (Scene 5)
- [ ] All four key phrases spoken out loud
- [ ] Audio is clean, no background noise
- [ ] Video is public on YouTube before submitting
- [ ] Total length ≤ 3:00