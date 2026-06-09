# ArXiv Papers: LLM Hallucinations & Reliability

**Query:** `all:LLM hallucination OR all:"large language model" hallucination` | **Date:** https://export.arxiv.org/api/query?search_query=all%3ALLM+hallucination+OR+all%3A%22large+language+model%22+hallucination
**Retrieved:** 10 papers | **Relevant:** 3 papers

---

## How reliable are LLMs when it comes to playing dice?

**Authors:** Luca Avena, Gianmarco Bet, Bernardo Busoni
**arXiv:** [2606.07515v1](https://arxiv.org/abs/2606.07515v1) | [PDF](https://arxiv.org/pdf/2606.07515v1)
**Published:** 2026-06-05T17:59:42Z

**Summary:** We investigate the probabilistic reasoning capabilities of large language models through a controlled benchmarking study on discrete probability problems. We constructed two datasets, respectively a set of standard exercises and a set of counterintuitive exercises, designed to trigger heuristic reasoning, and evaluated 8 state-of-the-art models, each tested with and without Chain-of-Thought prompting. Models achieve an average accuracy of 0.96 on standard problems but only 0.59 on counterintuitive ones. We further provide empirical evidence of token bias: performance drops by over 20% when canonical formulations are replaced by disguised variants. Embedding misleading suggestions in the prompt reduces performance by up to 34%, with no model proving immune. Taken together, the reported find...

---

## Whisper Hallucination Detection and Mitigation via Hidden Representation Steering and Sparse AutoEncoders

**Authors:** Georgii Aparin, Vadim Popov, Tasnima Sadekova, Assel Yermekova
**arXiv:** [2606.07473v1](https://arxiv.org/abs/2606.07473v1) | [PDF](https://arxiv.org/pdf/2606.07473v1)
**Published:** 2026-06-05T17:26:23Z

**Summary:** Whisper, a widely adopted ASR model, is known to suffer from hallucinations - coherent transcriptions generated for non-speech audio entirely disconnected from the input. We investigate whether hallucinations can be detected and mitigated through Whisper's internal representations. We extract audio encoder activations and evaluate two representation spaces: raw Whisper activations and Sparse AutoEncoder (SAE) latents. We show that both spaces encode linearly separable hallucination-related information, with discriminative power concentrated in a sparse feature subset and increasing toward deeper encoder layers. We propose two steering strategies: activation-space steering and SAE latent-space steering. SAE-based steering reduces hallucination rate from 72.63% to 14.11% for Whisper small an...

---

## Sycophantic Praise: Evaluating Excessive Praise in Language Models

**Authors:** Daniel Vennemeyer, Phan Anh Duong, Meryl Ye, Ruihong Huang, Tianyu Jiang
**arXiv:** [2606.07441v1](https://arxiv.org/abs/2606.07441v1) | [PDF](https://arxiv.org/pdf/2606.07441v1)
**Published:** 2026-06-05T16:38:45Z

**Summary:** Sycophancy in language models is typically studied as excessive agreement or validation, while explicit praise and flattery have received comparatively little attention. We argue that sycophantic praise is a distinct alignment problem that cannot be reliably measured using current methods. We introduce a parameterized framework that measures whether praise is excessive relative to contribution quality and expected user ability. We show that our framework substantially outperforms generic LLM judges in agreement with human annotations, and that sycophantic praise occurs far more frequently in social and interpretive domains than in objective reasoning settings. Together, these findings position praise calibration as a distinct alignment challenge....

---
