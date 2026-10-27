# Running the research platforms

> [!abstract] Purpose
> How an agent runs the per-platform research prompts for a standard RESYNTH
> round (the default mode, not light) in the owner's own browser. RESYNTH
> itself never calls a platform. The agent drives the browser, the owner
> reviews the settings before anything is sent.

## The procedure

1. Write one tailored prompt per platform into `prompts/RESEARCH-PROMPTS.md`
   and keep a paste-ready copy of each.
2. Open one tab per research platform the owner uses (table below), in a tab
   group the agent can drive. If the agent cannot reach tabs the owner opened,
   it opens its own tabs on the same sites. Never sign in, type a password,
   accept terms or click consent banners for the owner.
3. On each tab, in this order:
   1. **Turn on the deep research mode first.** Some platforms lock the model
      and effort once deep research is on. That is fine, leave them locked.
   2. **Then, only if still selectable, set the model and effort.** Use the
      platform's recommended latest model for deep reasoning, at the highest
      effort that is not a heavy spend. Levels that multiply usage (for
      example a "Max" level at several times the credits) are never the
      default. Use the account defaults below unless the owner says otherwise.
   3. If a setting leads to an upgrade, subscription or payment page, go back
      without clicking anything there and report it.
4. **Pause.** Type nothing and send nothing. Tell the owner which tab has
   which mode, model and effort, and wait for a go. This is the one review
   step the owner signs off on before a round.
5. On go, re-check each mode just before submitting (a new chat can reset
   it), paste each prompt and submit. Approve a research plan if the
   platform shows one.
6. Wait with a scheduled check, not a tight loop. Deep research runs take
   about 5 to 40 minutes. If a platform stalls, reload the tab once and check
   its chat history before re-running. Re-run a prompt at most once.
7. Save each finished report as markdown, one file per platform, with its
   source links, then ingest it with `resynth intake <project> --source <file>`.
   Prefer the platform's own copy button and read the clipboard. Do not
   download files, share, publish or rename chats. Leave the tabs open.

## Account defaults

Set by the owner on 27 October 2026. Change this table when the owner changes
a pick. "Locked" means deep research fixes it and nothing is chosen.

| Platform | Deep research mode | Model | Effort |
| --- | --- | --- | --- |
| ChatGPT | Deep research (tools menu) | Locked by deep research | Pro (top of the thinking effort slider), while spare credits last |
| Claude | Research on (+ menu) | Opus 5.5 (Fable is kept for visual and creative work) | High (not Extra or Max) |
| Gemini | Deep research (+ menu) | Auto, unless a heavier model is unlocked on the account | Thinking level High |
| Grok | DeepSearch where offered | Expert (Heavy is not on the owner's plan) | Not offered |
| Consensus | Deep pill active in the search box | Not offered | Not offered |

## Capture notes

- Long prompts paste reliably through a synthetic paste event on the editor.
  Gemini's editor needs `document.execCommand('insertText')`. Claude turns a
  long paste into an attachment, so add a one-line instruction with it.
- ChatGPT deep research reports sit in a cross-origin frame. Use its own copy
  button, then strip citation markers and private-use characters.
- Claude's Research copy button drops links. Append the panel's links as a
  source list.
- Gemini Deep Research can look hung after it has finished. Reload the tab
  before waiting longer.
