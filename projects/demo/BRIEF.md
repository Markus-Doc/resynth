# Research Brief: demo

> [!abstract] Research question
> How should passwords be stored and protected securely?

## Intended flow

1. The operator turns this brief into one tailored prompt per research platform, see prompts/RESEARCH-PROMPTS.md.
2. The user runs each prompt on its platform and saves every report as a file.
3. Each report enters the pipeline through resynth intake demo --source <file>.
4. The five stage pipeline consolidates the reports into output/MASTER.md with full provenance.
5. resynth export demo produces output/MASTER.json for downstream AI agents.
