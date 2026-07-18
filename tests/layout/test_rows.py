from __future__ import annotations

from ccparser.evidence import Word
from ccparser.layout.rows import cluster_rows


def _word(text: str, bbox: tuple[float, float, float, float]) -> Word:
    return Word(text=text, bbox=bbox, source="digital", confidence=1.0)


def _scaled(word: Word, factor: float, x_shift: float = 0.0) -> Word:
    x0, y0, x1, y1 = word.bbox
    return word.model_copy(
        update={
            "bbox": (
                x0 * factor + x_shift,
                y0 * factor,
                x1 * factor + x_shift,
                y1 * factor,
            )
        }
    )


def test_cluster_rows_uses_vertical_overlap_and_merges_nearby_words_into_cells() -> None:
    words = (
        _word("01/02/2026", (0.0, 10.0, 28.0, 20.0)),
        _word("עולם", (48.0, 10.5, 68.0, 20.5)),
        _word("שלום", (73.0, 10.0, 93.0, 20.0)),
        _word("18.40", (0.0, 31.0, 25.0, 41.0)),
        _word("Market", (50.0, 30.5, 80.0, 40.5)),
    )

    rows = cluster_rows(tuple(reversed(words)), page_number=3)

    assert len(rows) == 2
    assert rows[0].page_number == 3
    assert tuple(cell.text for cell in rows[0].cells) == ("שלום עולם", "01/02/2026")
    assert rows[0].words == words[:3]
    assert rows[0].bbox == (0.0, 10.0, 93.0, 20.5)
    assert rows[0].diagnostics == ("dominant_direction:rtl",)
    assert tuple(cell.text for cell in rows[1].cells) == ("18.40", "Market")


def test_cluster_rows_is_invariant_to_uniform_scaling_and_horizontal_shift() -> None:
    words = (
        _word("Date", (0.0, 10.0, 25.0, 20.0)),
        _word("Amount", (70.0, 10.4, 100.0, 20.4)),
        _word("01/02", (0.0, 30.0, 25.0, 40.0)),
        _word("9.95", (75.0, 30.4, 100.0, 40.4)),
    )

    original = cluster_rows(words, page_number=1)
    transformed = cluster_rows(
        tuple(_scaled(word, factor=2.5, x_shift=41.0) for word in words),
        page_number=1,
    )

    assert tuple(tuple(cell.text for cell in row.cells) for row in transformed) == tuple(
        tuple(cell.text for cell in row.cells) for row in original
    )
    assert tuple(len(row.words) for row in transformed) == (2, 2)


def test_cluster_rows_returns_empty_for_empty_evidence() -> None:
    assert cluster_rows((), page_number=1) == ()


def test_cluster_rows_deduplicates_overlapping_digital_and_ocr_words() -> None:
    words = (
        Word(
            text="Amount",
            bbox=(10.0, 10.0, 40.0, 20.0),
            source="digital",
            confidence=1.0,
        ),
        Word(
            text="Amount",
            bbox=(10.2, 10.1, 40.2, 20.1),
            source="ocr",
            confidence=0.91,
        ),
    )

    rows = cluster_rows(words, page_number=1)

    assert tuple(cell.text for cell in rows[0].cells) == ("Amount",)
    assert rows[0].words == (words[0],)
