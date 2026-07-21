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


def test_cluster_rows_deduplicates_same_ocr_text_when_one_box_contains_the_other() -> None:
    words = (
        Word(
            text="06/01/23",
            bbox=(100.0, 10.0, 140.0, 20.0),
            source="ocr",
            confidence=0.95,
        ),
        Word(
            text="06/01/23",
            bbox=(100.0, 10.0, 160.0, 20.0),
            source="ocr",
            confidence=0.90,
        ),
    )

    rows = cluster_rows(words, page_number=1)

    assert tuple(cell.text for cell in rows[0].cells) == ("06/01/23",)
    assert rows[0].words == (words[0],)


def test_cluster_rows_uses_identity_text_for_word_deduplication() -> None:
    words = (
        _word("Caf\u00e9", (10.0, 10.0, 40.0, 20.0)),
        _word("Cafe\u0301", (10.0, 10.0, 40.0, 20.0)),
    )

    rows = cluster_rows(words, page_number=1)

    assert len(rows[0].words) == 2
    assert {word.text for word in rows[0].words} == {"Caf\u00e9", "Cafe\u0301"}


def test_cluster_rows_confidence_measures_vertical_coherence_within_cluster() -> None:
    aligned = cluster_rows(
        (
            _word("Date", (0.0, 10.0, 25.0, 20.0)),
            _word("Amount", (70.0, 10.0, 100.0, 20.0)),
        ),
        page_number=1,
    )
    incoherent = cluster_rows(
        (
            _word("Date", (0.0, 10.0, 25.0, 20.0)),
            _word("Amount", (70.0, 14.0, 100.0, 24.0)),
        ),
        page_number=1,
    )

    assert len(aligned) == len(incoherent) == 1
    assert aligned[0].confidence == 1.0
    assert 0.0 < incoherent[0].confidence < aligned[0].confidence


def test_cluster_rows_does_not_let_tall_side_text_bridge_dense_table_lines() -> None:
    words = (
        _word("sidebar", (0.0, 0.0, 20.0, 40.0)),
        _word("10.00", (70.0, 0.0, 100.0, 10.0)),
        _word("20.00", (70.0, 10.5, 100.0, 20.5)),
        _word("30.00", (70.0, 21.0, 100.0, 31.0)),
    )

    rows = cluster_rows(words, page_number=1)

    assert len(rows) == 4
    assert sorted(
        tuple(cell.text for cell in row.cells)
        for row in rows
        if any(cell.text.endswith(".00") for cell in row.cells)
    ) == [("10.00",), ("20.00",), ("30.00",)]


def test_cluster_rows_does_not_expand_a_line_band_through_medium_side_annotations() -> None:
    words = (
        _word("01/01", (30.0, 0.5, 45.0, 9.5)),
        _word("First", (55.0, 0.5, 70.0, 9.5)),
        _word("10.00", (80.0, 0.5, 100.0, 9.5)),
        _word("note-a", (0.0, 3.8, 20.0, 16.8)),
        _word("02/01", (30.0, 11.5, 45.0, 20.5)),
        _word("Second", (55.0, 11.5, 70.0, 20.5)),
        _word("20.00", (80.0, 11.5, 100.0, 20.5)),
        _word("note-b", (0.0, 14.8, 20.0, 27.8)),
        _word("03/01", (30.0, 22.5, 45.0, 31.5)),
        _word("Third", (55.0, 22.5, 70.0, 31.5)),
        _word("30.00", (80.0, 22.5, 100.0, 31.5)),
    )

    rows = cluster_rows(words, page_number=1)

    transaction_rows = [row for row in rows if any(cell.text.endswith(".00") for cell in row.cells)]
    assert len(transaction_rows) == 3
    assert [
        tuple(cell.text for cell in row.cells if cell.text.endswith(".00"))
        for row in transaction_rows
    ] == [("10.00",), ("20.00",), ("30.00",)]


def test_cluster_rows_separates_overlapping_multiline_rtl_header_baselines() -> None:
    words = (
        _word("החיוב", (10.0, 10.0, 30.0, 20.0)),
        _word("סכום", (32.0, 10.0, 50.0, 20.0)),
        _word("₪", (20.0, 16.5, 24.0, 26.5)),
        _word("-", (24.0, 16.5, 28.0, 26.5)),
        _word("ב", (28.0, 16.5, 32.0, 26.5)),
    )

    rows = cluster_rows(words, page_number=1)

    assert tuple(tuple(cell.text for cell in row.cells) for row in rows) == (
        ("סכום החיוב",),
        ("ב - ₪",),
    )
