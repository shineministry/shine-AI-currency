from shinefx.db import cosine_similarity
from shinefx.vectors import hashing_embedding


def test_hashing_embedding_is_deterministic():
    a = hashing_embedding("convert 100 USD to EUR please")
    b = hashing_embedding("convert 100 USD to EUR please")
    assert a == b
    assert len(a) == 384


def test_cosine_similarity_same():
    a = hashing_embedding("currency rate USD EUR")
    assert cosine_similarity(a, a) > 0.999


def test_cosine_similarity_different():
    a = hashing_embedding("what is the dollar rate")
    b = hashing_embedding("baking soda recipes at home")
    assert cosine_similarity(a, b) < 0.5


def test_cosine_similarity_related():
    a = hashing_embedding("USD to EUR conversion rate today")
    b = hashing_embedding("current exchange rate of dollar to euro")
    c = hashing_embedding("solar system planet names list")
    assert cosine_similarity(a, b) > cosine_similarity(a, c)
