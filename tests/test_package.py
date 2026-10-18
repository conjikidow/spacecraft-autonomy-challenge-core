import spacecraft_ops


def test_version_matches_distribution_metadata():
    assert spacecraft_ops.__version__ == "0.1.0"


def test_top_level_exports_strategy_api_only():
    assert {"Strategy", "Commander", "Telemetry", "MissionBrief", "SetPropulsionMode"} <= set(spacecraft_ops.__all__)
    assert not {"SpacecraftState", "Simulation", "Scenario", "Timeline", "Modifier"} & set(spacecraft_ops.__all__)
    for name in spacecraft_ops.__all__:
        assert hasattr(spacecraft_ops, name)
