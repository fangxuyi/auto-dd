from company_research.parsing.xbrl import _period_label


def test_annual_period():
    entry = {"start": "2023-10-01", "end": "2024-09-30"}
    label, period_type = _period_label(entry)
    assert label == "FY_2024"
    assert period_type == "fiscal"


def test_quarterly_period():
    entry = {"start": "2024-07-01", "end": "2024-09-30"}
    label, period_type = _period_label(entry)
    assert "Q_" in label
    assert period_type == "fiscal"


def test_point_in_time():
    entry = {"end": "2024-09-30"}
    label, period_type = _period_label(entry)
    assert label == "as_of_2024-09-30"


def test_invalid_dates_fallback():
    entry = {"start": "bad", "end": "2024-09-30"}
    label, period_type = _period_label(entry)
    assert "as_of" in label
