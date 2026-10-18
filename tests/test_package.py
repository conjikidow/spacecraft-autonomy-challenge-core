import spacecraft_ops


def test_version_matches_distribution_metadata():
    assert spacecraft_ops.__version__ == "0.1.0"
