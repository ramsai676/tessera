import pytest

from tessera.names import Matcher, edit_distance, normalise, similarity


class TestNormalise:
    def test_lowercases_and_collapses_whitespace(self):
        assert normalise("  BANGALORE   Urban  ") == "bangalore urban"

    def test_strips_punctuation(self):
        assert normalise("Bangalore (Urban)") == "bangalore urban"
        assert normalise("St. Mary's") == "st marys"

    def test_strips_accents(self):
        assert normalise("Bengalūru") == "bengaluru"
        assert normalise("Kraków") == "krakow"

    def test_drops_structural_noise_words(self):
        assert normalise("Mysuru District") == "mysuru"
        assert normalise("Belagavi Taluk") == "belagavi"

    def test_keeps_the_name_when_it_is_entirely_noise(self):
        # Better to return something matchable than an empty key.
        assert normalise("District") != ""

    def test_variants_converge_on_one_key(self):
        forms = ["Bengaluru Urban", "BENGALURU URBAN ", "Bengaluru  (Urban)", "bengaluru urban district"]
        assert len({normalise(f) for f in forms}) == 1


class TestEditDistance:
    def test_identical_strings_are_zero_apart(self):
        assert edit_distance("mysuru", "mysuru") == 0

    def test_counts_single_edits(self):
        assert edit_distance("mysuru", "mysure") == 1
        assert edit_distance("abc", "") == 3

    def test_is_symmetric(self):
        assert edit_distance("kitten", "sitting") == edit_distance("sitting", "kitten")

    def test_cap_short_circuits_without_changing_the_verdict(self):
        # Anything over the cap only needs to be reported as "over the cap".
        assert edit_distance("aaaaaaaaaa", "bbbbbbbbbb", cap=2) > 2

    def test_similarity_is_bounded(self):
        assert similarity("abc", "abc") == 1.0
        assert 0.0 <= similarity("abc", "xyz") <= 1.0


class TestMatcher:
    @pytest.fixture
    def matcher(self):
        return Matcher(["Bengaluru Urban", "Mysuru", "Belagavi", "Kalaburagi"])

    def test_exact_match_after_normalising(self, matcher):
        result = matcher.match("  bengaluru urban DISTRICT ")
        assert result.matched == "Bengaluru Urban"
        assert result.method == "exact"
        assert result.score == 1.0

    def test_typo_within_threshold_matches_fuzzily(self, matcher):
        result = matcher.match("Bangaluru Urban")
        assert result.matched == "Bengaluru Urban"
        assert result.method == "fuzzy"
        assert result.score < 1.0

    def test_unrelated_name_is_refused_rather_than_guessed(self, matcher):
        result = matcher.match("Atlantis")
        assert result.matched is None
        assert result.method == "none"
        assert not result.ok

    def test_a_rename_is_refused_without_an_alias(self, matcher):
        # Mysore -> Mysuru is a real rename, not a typo; edit distance can't
        # bridge it, and no honest threshold should pretend otherwise.
        assert matcher.match("Mysore").matched is None

    def test_an_alias_resolves_a_rename(self):
        matcher = Matcher(["Mysuru", "Belagavi"], aliases={"Mysore": "Mysuru"})
        result = matcher.match("mysore")
        assert result.matched == "Mysuru"
        assert result.method == "alias"

    def test_alias_pointing_at_an_unknown_region_is_rejected_at_construction(self):
        with pytest.raises(ValueError, match="not a canonical name"):
            Matcher(["Mysuru"], aliases={"Mysore": "Nowhere"})

    def test_a_stricter_threshold_refuses_a_borderline_match(self):
        loose = Matcher(["Stonebridge"], threshold=0.80)
        strict = Matcher(["Stonebridge"], threshold=0.95)
        assert loose.match("Stonebrigde").ok
        assert not strict.match("Stonebrigde").ok

    def test_margin_guards_against_an_ambiguous_middle(self):
        # "Weston" sits between two real places; with a margin requirement the
        # matcher declines instead of coin-flipping.
        matcher = Matcher(["Weston North", "Weston South"], threshold=0.5, min_margin=0.2)
        assert not matcher.match("Weston").ok

    def test_threshold_must_be_a_valid_proportion(self):
        with pytest.raises(ValueError):
            Matcher(["A"], threshold=0)
        with pytest.raises(ValueError):
            Matcher(["A"], threshold=1.5)

    def test_len_reports_the_canonical_set_size(self, matcher):
        assert len(matcher) == 4
