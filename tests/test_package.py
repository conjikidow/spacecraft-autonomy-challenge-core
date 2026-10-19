import spacecraft_ops_challenge


def test_version_matches_distribution_metadata():
    assert spacecraft_ops_challenge.__version__ == "0.1.0"


def test_top_level_exports_strategy_api_only():
    exported = set(spacecraft_ops_challenge.__all__)
    assert {"Strategy", "Commander", "Telemetry", "MissionBrief", "SetPropulsionMode"} <= exported
    assert not {"SpacecraftState", "Simulation", "Scenario", "Timeline", "Modifier"} & exported
    for name in spacecraft_ops_challenge.__all__:
        assert hasattr(spacecraft_ops_challenge, name)
