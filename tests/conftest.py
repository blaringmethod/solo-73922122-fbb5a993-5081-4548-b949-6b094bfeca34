import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app


@pytest.fixture()
def app(tmp_path):
    application = create_app(db_path=str(tmp_path / "test.db"))
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def svc(app):
    return app.extensions["catalog_service"]


@pytest.fixture()
def client(app):
    return app.test_client()
