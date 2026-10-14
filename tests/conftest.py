"""Use the same Qt base style as the real application entry point."""

import pytest


@pytest.fixture(scope="session")
def qapp_args():
    # app.main() explicitly selects Fusion. A bare pytest-qt QApplication on
    # Windows otherwise uses WindowsVista, whose popup chrome differs from
    # the style shipped in Picer. Keep pixel and input tests representative.
    return ["Picer", "-style", "Fusion"]
