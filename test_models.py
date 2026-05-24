from sentence_transformers import CrossEncoder, SentenceTransformer


def main():
    print("Testing sentence-transformers...")
    model = SentenceTransformer("all-mpnet-base-v2")
    emb = model.encode(["hello world", "hi world"])
    print("Embeddings shape:", emb.shape)

    print("Testing CrossEncoder...")
    nli_model = CrossEncoder("cross-encoder/nli-deberta-v3-base")
    # cross-encoder/nli-deberta-v3-base output label order is typically:
    # 0: contradiction, 1: entailment, 2: neutral (or similar). Let's check!
    # Let's predict on a few pairs:
    pairs = [
        ("The dog is black", "The dog is dark colored"),  # entailment
        ("The dog is black", "The dog is white"),  # contradiction
        ("The dog is black", "The dog is running"),  # neutral
    ]
    scores = nli_model.predict(pairs)
    print("Scores:")
    for pair, score in zip(pairs, scores, strict=False):
        print(pair, "->", score)


if __name__ == "__main__":
    main()
