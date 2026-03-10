import pytest
from hypothesis import given, settings
from hypothesis.strategies import text, dictionaries, lists, sampled_from, characters, dates
from citations.models import IncorrectCitation, UserProfile
from django.contrib.auth.models import User
from django.db import IntegrityError, DataError, transaction

@pytest.fixture(scope="module")
def random_user(django_db_blocker):
    with django_db_blocker.unblock():
        user, _ = User.objects.get_or_create(username="testuser_hypothesis")
        return user

@pytest.mark.django_db(transaction=True)
@settings(max_examples=500, deadline=None)
@given(
    doi_original=text(min_size=1, max_size=255),
    doi_incorrect=text(min_size=1, max_size=255),
    incorrect_reason=text(max_size=5000),
    metadata_original=dictionaries(keys=text(), values=text()),
    metadata_incorrect=dictionaries(keys=text(), values=text()),
    citation_contexts=lists(dictionaries(keys=text(), values=text())),
    citation_type=sampled_from(["not said", "misinterpretation", "contextual misattribution"]),
    publication_area=sampled_from(["", "CS", "PHY", "MATH", "BIO"])
)
def test_incorrect_citation_robustness(
    random_user, doi_original, doi_incorrect, incorrect_reason, metadata_original, metadata_incorrect, citation_contexts, citation_type, publication_area
):
    try:
        with transaction.atomic():
            ic = IncorrectCitation.objects.create(
                author=random_user,
                doi_original=doi_original[:255],
                doi_incorrect=doi_incorrect[:255],
                incorrect_reason=incorrect_reason,
                metadata_original=metadata_original,
                metadata_incorrect=metadata_incorrect,
                citation_contexts=citation_contexts,
                citation_type=citation_type,
                publication_area=publication_area[:4]
            )
            assert ic.id is not None
            assert str(ic) == f"{doi_original[:255]} citado incorrectamente por {doi_incorrect[:255]}"
    except Exception as e:
        assert type(e).__name__ in ['DataError', 'IntegrityError', 'ValidationError', 'ValueError']

@pytest.mark.django_db(transaction=True)
@settings(max_examples=500, deadline=None)
@given(
    username=text(min_size=1, max_size=150, alphabet=characters(whitelist_categories=('Lu', 'Ll', 'Nd', 'Pc', 'Pd', 'Po'))),
    dblp_url=text(max_size=200),
    date_of_birth=dates(),
    country=text(max_size=100),
    preferred_language=sampled_from(["", "es", "en"]),
    research_area=text(max_size=200),
    profession=text(max_size=200),
)
def test_user_profile_robustness(
    username, dblp_url, date_of_birth, country, preferred_language, research_area, profession
):
    try:
        with transaction.atomic():
            user = User.objects.create(username=username[:150])
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.dblp_url = dblp_url[:200]
            profile.date_of_birth = date_of_birth
            profile.country = country[:100]
            profile.preferred_language = preferred_language
            profile.research_area = research_area[:200]
            profile.profession = profession[:200]
            profile.save()
            assert profile.user.username == username[:150]
    except Exception as e:
        assert type(e).__name__ in ['DataError', 'IntegrityError', 'ValidationError', 'ValueError']
