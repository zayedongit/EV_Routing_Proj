import pytest

from evrp.instance import InstanceError
from evrp.stations import generate_stations


def test_no_stations_requested(tiny):
    assert generate_stations(tiny, 0) == ()


def test_first_station_sits_on_the_depot(tiny):
    stations = generate_stations(tiny, 3, seed=1)
    assert len(stations) == 3
    assert (stations[0].x, stations[0].y) == (tiny.depot.x, tiny.depot.y)


@pytest.mark.parametrize("strategy", ["kmeans", "grid", "random"])
def test_placement_is_reproducible(tiny, strategy):
    a = generate_stations(tiny, 3, strategy=strategy, seed=99)
    b = generate_stations(tiny, 3, strategy=strategy, seed=99)
    assert a == b


def test_kmeans_places_stations_among_the_customers(tiny):
    stations = generate_stations(tiny, 3, strategy="kmeans", seed=5)
    xs = [s.x for s in stations[1:]]
    assert all(0 <= x <= 30 for x in xs)


def test_unknown_strategy_is_rejected(tiny):
    with pytest.raises(InstanceError):
        generate_stations(tiny, 3, strategy="vibes")


def test_invalid_arguments_are_rejected(tiny):
    with pytest.raises(InstanceError):
        generate_stations(tiny, -1)
    with pytest.raises(InstanceError):
        generate_stations(tiny, 2, power_kw=0)


def test_more_stations_than_customers_is_handled(tiny):
    stations = generate_stations(tiny, 10, strategy="kmeans", seed=3)
    assert len(stations) <= 10
    assert len({(s.x, s.y) for s in stations}) >= 1


def test_station_ids_are_sequential(tiny):
    stations = generate_stations(tiny, 4, seed=2)
    assert [s.id for s in stations] == [0, 1, 2, 3]
