from demandsense.config import load_config


def test_smoke_config_resolves_project_paths() -> None:
    config = load_config("configs/smoke.yaml")

    assert config.data.profile == "smoke"
    assert config.data.series_limit == 30
    assert config.paths.raw_dir.is_absolute()
    assert config.forecast.horizon == 28


def test_release_config_has_no_series_limit() -> None:
    config = load_config("configs/portfolio.yaml")

    assert config.data.profile == "release"
    assert config.data.series_limit is None
