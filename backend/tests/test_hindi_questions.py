"""Questions in Hindi, read by the offline rules.

A hosted model reads Hindi on its own; these cover the deterministic reader
that runs without one, and the date and place extraction that runs always.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.controller.task_understanding.context import extract_context, extract_locations
from app.controller.task_understanding.task_understanding import TaskUnderstanding


@pytest.mark.parametrize(
    "query, task, places",
    [
        ("पुणे में वनस्पति कितनी स्वस्थ है?", "ndvi", ["पुणे"]),
        ("अगस्त 2024 में कोच्चि के पास बाढ़ प्रभावित क्षेत्र दिखाइए", "flood_mapping", ["कोच्चि"]),
        ("होसुर में 2019 और 2025 के बीच कितनी हरियाली कम हुई?", "change_detection", ["होसुर"]),
        ("गुरुग्राम में शहरी क्षेत्र कहाँ हैं?", "ndbi", ["गुरुग्राम"]),
        ("नागपुर के आसपास भूमि आवरण बताइए", "segmentation", ["नागपुर"]),
        ("चिल्का झील के आसपास सतही जल दिखाइए", "ndwi", ["चिल्का झील"]),
        ("क्या वाराणसी के पास कोई नदी है?", "image_analysis", ["वाराणसी"]),
        ("भोपाल में पिछले साल क्या बदलाव हुआ?", "change_detection", ["भोपाल"]),
    ],
)
def test_hindi_questions_are_understood(query, task, places):
    understanding = TaskUnderstanding().understand(query)
    assert understanding.task_type == task
    assert understanding.context.locations == places


@pytest.mark.parametrize(
    "text, start, end",
    [
        ("अगस्त 2024 में", date(2024, 8, 1), date(2024, 8, 31)),
        ("फरवरी 2023", date(2023, 2, 1), date(2023, 2, 28)),
        ("सितम्बर 2025", date(2025, 9, 1), date(2025, 9, 30)),
    ],
)
def test_hindi_months_narrow_the_period(text, start, end):
    period = extract_context(text).time_range
    assert (period.start, period.end) == (start, end)


def test_words_that_are_not_places_are_left_out():
    assert extract_locations("इस क्षेत्र में पानी") == []
    assert extract_locations("झील के पास पानी") == []
    assert extract_locations("अगस्त 2024 में बाढ़") == []
