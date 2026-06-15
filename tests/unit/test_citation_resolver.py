from company_research.validation.citations import _quote_in_text


def test_quote_found():
    assert _quote_in_text("Revenue was $100M", "Our Revenue was $100M in fiscal 2024.")


def test_quote_case_insensitive():
    assert _quote_in_text("revenue was $100m", "Revenue was $100M in fiscal 2024.")


def test_quote_not_found():
    assert not _quote_in_text("Net income was $50M", "Revenue was $100M in fiscal 2024.")


def test_empty_quote():
    assert not _quote_in_text("", "Some text here.")


def test_partial_match_uses_30_chars():
    # quote[:30] = "Revenue was $100M x x x x x x " — verify source must contain that prefix
    long_quote = "Revenue was $100M" + " x" * 50
    prefix = long_quote[:30]
    source_text = f"According to results: {prefix} and more."
    assert _quote_in_text(long_quote, source_text)
