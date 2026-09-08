import io

import numpy as np
import pytest

from evrp.config import EnergyConfig, VehicleSpec
from evrp.instance import (
    ChargingStation,
    Instance,
    InstanceError,
    Node,
    NodeKind,
    load_solomon,
    normalise_columns,
    read_solomon_frame,
)


def test_node_indexing_puts_stations_last(tiny_with_station):
    inst = tiny_with_station
    assert inst.customer_indices == (1, 2, 3)
    assert inst.station_indices == (4,)
    assert inst.nodes[4].kind is NodeKind.STATION
    assert inst.is_station(4) and not inst.is_station(2)


def test_distance_matrix_is_symmetric_with_zero_diagonal(tiny):
    d = tiny.distance
    assert np.allclose(d, d.T)
    assert np.allclose(np.diag(d), 0.0)
    assert d[0][1] == pytest.approx(10.0)
    assert d[1][3] == pytest.approx(20.0)


def test_travel_time_follows_the_solomon_convention(tiny):
    # speed 1 km/min means travel time equals distance, which is what makes
    # published Solomon results comparable.
    assert np.allclose(tiny.travel_time, tiny.distance)


def test_metric_selection_changes_distances():
    depot = Node(id=0, x=0, y=0, due_time=100, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=3, y=4, due_time=100)]
    euc = Instance.build("e", depot, customers, metric="euclidean")
    man = Instance.build("m", depot, customers, metric="manhattan")
    assert euc.distance[0][1] == pytest.approx(5.0)
    assert man.distance[0][1] == pytest.approx(7.0)


def test_haversine_metric_is_a_real_great_circle():
    # London to Paris is about 344 km; the old code shipped a "haversine"
    # function that actually returned Euclidean distance.
    depot = Node(id=0, x=51.5074, y=-0.1278, due_time=1000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=48.8566, y=2.3522, due_time=1000)]
    inst = Instance.build("geo", depot, customers, metric="haversine")
    assert 330.0 < inst.distance[0][1] < 360.0


def test_unknown_metric_is_rejected():
    depot = Node(id=0, x=0, y=0, due_time=10, kind=NodeKind.DEPOT)
    with pytest.raises(InstanceError):
        Instance.build("x", depot, [Node(id=1, x=1, y=1, due_time=10)], metric="taxicab")


def test_instance_requires_customers():
    depot = Node(id=0, x=0, y=0, due_time=10, kind=NodeKind.DEPOT)
    with pytest.raises(InstanceError):
        Instance.build("x", depot, [])


def test_node_rejects_inverted_time_window():
    with pytest.raises(InstanceError):
        Node(id=1, x=0, y=0, ready_time=50, due_time=10).validate()


def test_diagnostics_flag_insufficient_fleet_capacity(vehicle):
    depot = Node(id=0, x=0, y=0, due_time=1000, kind=NodeKind.DEPOT)
    customers = [Node(id=i, x=i, y=0, demand=90, due_time=1000) for i in range(1, 4)]
    inst = Instance.build("cap", depot, customers, vehicle=vehicle, fleet_size=1)
    issues = " ".join(inst.diagnostics())
    assert "total demand" in issues


def test_diagnostics_flag_unreachable_time_window(vehicle):
    depot = Node(id=0, x=0, y=0, due_time=1000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=500, y=0, demand=1, ready_time=0, due_time=5)]
    inst = Instance.build("tw", depot, customers, vehicle=vehicle, fleet_size=1)
    assert any("unreachable" in i for i in inst.diagnostics())


def test_range_diagnostics_spot_customers_outside_the_charging_network(vehicle):
    depot = Node(id=0, x=0, y=0, due_time=100000, kind=NodeKind.DEPOT)
    customers = [
        Node(id=1, x=10, y=0, demand=1, due_time=100000),
        Node(id=2, x=900, y=0, demand=1, due_time=100000),
    ]
    inst = Instance.build("range", depot, customers, vehicle=vehicle, fleet_size=1)
    issues = inst.diagnostics(EnergyConfig(base_kwh_per_km=0.1, payload_kwh_per_km_per_kg=0.0))
    assert any("out of range" in i for i in issues)


def test_charging_network_extends_reach(vehicle):
    depot = Node(id=0, x=0, y=0, due_time=100000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=90, y=0, demand=1, due_time=100000)]
    stations = [ChargingStation(id=0, x=50, y=0, due_time=100000)]
    cfg = EnergyConfig(base_kwh_per_km=0.1, payload_kwh_per_km_per_kg=0.0)

    without = Instance.build("a", depot, customers, vehicle=vehicle, fleet_size=1)
    with_cs = Instance.build("b", depot, customers, stations, vehicle=vehicle, fleet_size=1)
    # 100 km of range: 90 km out and back is impossible, but a charger at 50 km
    # splits it into two legs that fit.
    assert without.unreachable_customers(100.0) == [1]
    assert with_cs.unreachable_customers(100.0) == []


# -- parsing ---------------------------------------------------------------

CSV = (
    "CUST NO.,XCOORD.,YCOORD.,DEMAND,READY TIME,DUE DATE,SERVICE TIME\n"
    "1,40,50,0,0,1236,0\n"
    "2,45,68,10,912,967,90\n"
    "3,45,70,30,825,870,90\n"
)


def test_parser_accepts_solomon_header_spellings():
    frame = read_solomon_frame(io.StringIO(CSV))
    assert list(frame.columns) == [
        "id", "x", "y", "demand", "ready_time", "due_time", "service_time"
    ]


def test_parser_treats_the_first_row_as_the_depot_and_renumbers():
    inst = load_solomon(io.StringIO(CSV), name="mini", fleet_size=2)
    assert inst.depot.x == 40 and inst.depot.due_time == 1236
    assert inst.n_customers == 2
    assert [c.id for c in inst.customers] == [1, 2]
    assert inst.total_demand == 40


def test_parser_rejects_missing_columns():
    with pytest.raises(InstanceError):
        read_solomon_frame(io.StringIO("a,b\n1,2\n"))


def test_parser_rejects_non_numeric_cells():
    bad = CSV.replace("45,68", "abc,68")
    with pytest.raises(InstanceError):
        read_solomon_frame(io.StringIO(bad))


def test_parser_reports_a_missing_file():
    with pytest.raises(FileNotFoundError):
        load_solomon("does/not/exist.csv")


def test_real_solomon_instance_loads(solomon_path):
    inst = load_solomon(solomon_path, vehicle=VehicleSpec(payload_capacity=200), fleet_size=25)
    assert inst.n_customers == 100
    assert inst.total_demand == 1810  # the published C101 total
    assert inst.horizon == 1236


def test_with_stations_preserves_customers(tiny):
    rebuilt = tiny.with_stations([ChargingStation(id=0, x=5, y=5, due_time=1000)])
    assert rebuilt.n_customers == tiny.n_customers
    assert rebuilt.station_indices == (4,)
    assert rebuilt.distance.shape == (5, 5)
