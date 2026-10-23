# NemoTrace — YouTube Demo Video Script
**Target length: ~2:45 — leave breathing room before 3:00**

---

## THE STORY

### The Problem (0:00 – 0:20)

> *Screen: a wall of red error logs scrolling fast. Terminal chaos.*

**Narration:**
"It's 2am. Your payment service is down. Orders are failing. You have hundreds of thousands of error lines across five microservices — and somewhere in there is the one thing that started it all.

This is what a cascade failure looks like. And right now, finding the root cause takes your team hours."

---

### The Solution — Live Demo Starts (0:20 – 0:50)

> *Screen: NemoTrace portal opens. Header shows "● Connected". Demo cascade button.*

**Narration:**
"NemoTrace watches your services in real time. The moment an error spike is detected — automatically, no human needed — it triggers an AI investigation.

Watch. I'll start the demo cascade now."

> *Click Start Demo. Log events start flowing in the Logs tab — payment-service, order-service, api-gateway all lighting up red.*

"Three services. Hundreds of errors. NemoTrace ingested them all in under a second — straight into Redis Streams for processing."

---

### AI Pipeline — Classification (0:50 – 1:30)

> *Screen: Analysis tab. Progress bar starts moving. Topology graph appears — nodes connecting.*

**Narration:**
"Stage one: the system builds a service topology graph from trace IDs and timestamps. It figures out which service called which, and in what order.

Stage two: every single error event gets classified by **Nemotron Nano 8B** — running on **Nebius Token Factory**. That's twenty concurrent AI calls, batched, finishing in seconds.

You can see the progress bar filling. Each step — parsing, correlating, classifying — streamed live to the portal via Server-Sent Events."

> *Progress bar hits 100%. Incident card appears.*

---

### Root Cause — Ultra 253B Reasoning (1:30 – 2:00)

> *Screen: Incident report card. Confidence score visible. RCA text streaming word by word.*

**Narration:**
"And here's where it gets powerful. **Nemotron Ultra 253B** — a 253-billion parameter reasoning model, also on **Nebius Token Factory** — reads the full incident context and writes the root cause explanation. Word by word, streamed in real time.

Confidence: 94%. Root cause: a database connection pool exhaustion in the payment service triggered a cascade through order-service to the API gateway.

Remediation steps — fetched live from the web by **Tavily Search** — appear right below."

---

### Interactive Q&A (2:00 – 2:20)

> *Screen: Q&A input. Type a question.*

**Narration:**
"Every incident is also a conversation. Ask anything — the Ultra model has the full context.

'Was this a gradual degradation or a sudden failure?'"

> *Response streams in.*

"Instant answer. No copy-pasting logs. No context switching."

---

### Tech Stack Callout (2:20 – 2:45)

> *Screen: Split — architecture diagram on one side, portal on the other.*

**Narration:**
"NemoTrace is built entirely on open infrastructure.

**Nemotron Nano 8B** on **Nebius Token Factory** handles batch classification — up to 200 events per second. **Nemotron Ultra 253B** on **Token Factory** streams the reasoning. **Nebius Object Storage** keeps the raw log archive. **Tavily** pulls real-time remediation and CVE data.

The whole stack — FastAPI, Redis, Postgres, nginx — runs in Docker on a Nebius VM. One command to deploy.

This is what open AI infrastructure looks like when it's actually useful."

---

## KEY PHRASES TO SAY OUT LOUD
*(Hackathon rules require these to be named in audio)*

- "Nemotron Nano 8B on Nebius Token Factory"
- "Nemotron Ultra 253B on Nebius Token Factory"
- "Nebius Object Storage"
- "Tavily"

---

## RECORDING CHECKLIST

- [ ] Terminal or browser visible — not a slideshow
- [ ] Demo cascade actually runs live (not pre-recorded)
- [ ] SSE progress bar animates in real time (proves it works)
- [ ] RCA text streams word-by-word (shows Ultra reasoning)
- [ ] Confidence score > 0 visible on screen
- [ ] Q&A turn answered on screen
- [ ] All four key phrases spoken out loud
- [ ] Video is public on YouTube before submitting
- [ ] Length ≤ 3:00

---

## WHAT MAKES THIS WORTH WATCHING

**Who needs this:** Any engineering team running microservices — every company with more than two backend services has this problem. MTTR (mean time to resolution) for cascade failures is measured in hours. NemoTrace brings it to minutes.

**Why it's impressive:** It's not a chatbot wrapper. It's a full pipeline — stream ingestion, spike detection, topology inference, batched AI classification, multi-turn reasoning — all automated, all streaming, all open source.

**Why Nebius/NVIDIA:** The two-model strategy (Nano for speed, Ultra for depth) is the right engineering call. Token Factory makes it possible without managing a single GPU.
