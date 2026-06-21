---
version: "1.0.0"
model: claude-haiku-4-5-20251001
max_tokens: 30
description: >
  Extract a 3-7 word product or service label from a SEC filing excerpt
  describing a supply or customer relationship between two companies.
---

{{ excerpt }}

Filer company: {{ filer_name }}
Target company: {{ target_name }}
Relationship direction: {{ direction }}

What product or service does the filer provide to or receive from the target company?
Reply with 3-7 words only. No punctuation, no explanation. If genuinely unclear reply with the single word: unknown
