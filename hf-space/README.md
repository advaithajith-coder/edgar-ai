---
title: EDGAR.AI
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: Ask questions of any US company's annual report (10-K)
---

# EDGAR.AI

Pick a US-listed company and EDGAR.AI reads its latest annual report (10-K) from SEC EDGAR, lays out
the key figures, and answers questions in plain English with tables, charts and quotes from the
filing's risk factors and MD&A.

![How EDGAR.AI answers a question](https://raw.githubusercontent.com/advaithajith-coder/edgar-ai/main/demo-screenshots/00-how-edgar-ai-answers.png)

Live demo: https://edgar-ai.onrender.com/

Source code: https://github.com/advaithajith-coder/edgar-ai

This Space needs one secret, `GROQ_API_KEY` (Settings → Variables and secrets). Optionally set
`SEC_USER_AGENT` to "YourName your@email.com", which SEC EDGAR asks automated tools to send.
