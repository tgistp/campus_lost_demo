# Local semantic answer model

Base model: [sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2), Apache License 2.0.

ONNX conversion: [Xenova/paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/Xenova/paraphrase-multilingual-MiniLM-L12-v2).

Pinned revision: `2c4055b12046f11709e9df2c122e59ffbdc2f900`.

- `model_quantized.onnx`: SHA-256 `66fc00f5f29afcaff34092e1bdd20008ca3918265a82fb9695a551e510cc4ebc` (118,308,126 bytes).
- `tokenizer.json`: SHA-256 `b60b6b43406a48bf3638526314f3d232d97058bc93472ff2de930d43686fa441`.
- `config.json`: SHA-256 `05b570bff786faa5c4604152aa16f19f77ed6dfc31e47dd0f3dd987078693ac7`.

The app runs these local files with ONNX Runtime CPU and mean pooling of token embeddings. No Python model repository code, pickle or remote custom code is executed. Answers are not sent to Hugging Face or another inference service. The app compares raw sentences plus normalised variants, with separate contradiction/identifier safeguards. The score is cosine similarity, not a probability of ownership.

The current threshold 0.80 is a prototype setting checked with development examples, not a validated security or ownership accuracy claim. Uncertain or conflicting answers remain pending for manual review.
