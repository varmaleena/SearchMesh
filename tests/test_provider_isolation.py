import pytest
from searchmesh.api import create_app
from searchmesh.provider import FixtureProvider, SerpApiProvider


def test_database_rejects_different_provider_mode(tmp_path):
    path=tmp_path/'isolation.sqlite'
    create_app(path,FixtureProvider())
    with pytest.raises(ValueError,match='separate --db'):
        create_app(path,SerpApiProvider('test-secret'))


def test_database_rejects_different_live_credential(tmp_path):
    path=tmp_path/'isolation.sqlite'
    create_app(path,SerpApiProvider('first-test-secret'))
    create_app(path,SerpApiProvider('first-test-secret'))
    with pytest.raises(ValueError,match='separate --db'):
        create_app(path,SerpApiProvider('second-test-secret'))
