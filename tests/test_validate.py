from ridewise import validate


def test_normalise_citations_and_hyphens():
    out = validate.normalise_answer("See 【S3】 and ［S1］ and [S2, S4] – ok")
    assert "[S3]" in out and "[S1]" in out and "[S2][S4]" in out and "–" not in out


def test_number_not_in_evidence_fails():
    _, g = validate.check("The fee is 999 [S1]", "the fee is 150", 1)
    assert not g.ok and any("999" in e for e in g.errors)


def test_number_in_evidence_passes():
    _, g = validate.check("The fee is 150 [S1]", "fee 150", 1)
    assert g.ok


def test_action_claim_fails():
    _, g = validate.check("I have cancelled your booking [S1]", "booking B-0001", 1)
    assert not g.ok


def test_false_processed_fails_but_negation_passes():
    _, g1 = validate.check("Your refund was processed [S1]", "due 250 processed 0", 1,
                           processed_zero=True)
    assert not g1.ok
    _, g2 = validate.check("No refund has been processed yet [S1]", "due 250 processed 0", 1,
                           processed_zero=True)
    assert g2.ok


def test_requires_citation_when_sources_exist():
    _, g = validate.check("The policy allows 100 percent", "100%", 1)
    assert not g.ok


def test_id_must_be_in_evidence():
    _, g = validate.check("See booking B-0412 [S1]", "booking B-0001", 1)
    assert not g.ok
