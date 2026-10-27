import spacecraft_autonomy_challenge


def test_top_level_exports_strategy_api_only():
    exported = set(spacecraft_autonomy_challenge.__all__)
    assert {"Strategy", "Commander", "Telemetry", "MissionBrief", "SetPropulsionMode"} <= exported
    assert not {"SpacecraftState", "Simulation", "Scenario", "Timeline", "Modifier"} & exported
    for name in spacecraft_autonomy_challenge.__all__:
        assert hasattr(spacecraft_autonomy_challenge, name)
