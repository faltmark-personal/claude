import pytest

from runna_playlist.app import create_app
from runna_playlist.service import AppState
from runna_playlist.sources.demo import DemoCatalog


@pytest.fixture
def state(tmp_path):
    # Demo catalog stands in for Deezer so tests never touch the network.
    return AppState(tmp_path, catalog=DemoCatalog())


@pytest.fixture
def client(state):
    from fastapi.testclient import TestClient

    return TestClient(create_app(state))
