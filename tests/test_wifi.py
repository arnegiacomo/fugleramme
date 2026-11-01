"""The Wi-Fi setup (#308): how nmcli's output reads, and when the hotspot opens and closes.
NetworkManager itself is Pi-only, so the commands are faked and the rules are what is tested."""

from __future__ import annotations

import subprocess

import pytest

from fugleramme import wifi
from fugleramme.wifi import GRACE, RETRY, Network, Nmcli, Setup


def test_fields_unescape_colons_and_backslashes():
    assert wifi.fields(r"Cafe\: upstairs:WPA2:71") == ["Cafe: upstairs", "WPA2", "71"]
    assert wifi.fields(r"back\\slash::") == ["back\\slash", "", ""]


def test_networks_keep_the_strongest_of_each_name_and_drop_what_a_password_cannot_join():
    # The third is hidden, the fourth Enterprise.
    listing = """Home:WPA2:40
Home:WPA2:80
:WPA2:90
Office:WPA2 802.1X:70
Cafe:--:60
Flat:WPA3:20"""
    assert wifi.networks(listing) == (
        Network("Home", "WPA2", 80),
        Network("Cafe", "", 60),
        Network("Flat", "WPA3", 20),
    )


def test_only_a_wpa3_only_network_needs_sae():
    assert wifi.key_mgmt("WPA3") == "sae"
    assert wifi.key_mgmt("WPA2 WPA3") == "wpa-psk"
    assert wifi.key_mgmt("WPA2") == "wpa-psk"


def test_the_hotspot_is_named_for_the_end_of_the_mac():
    assert wifi.hotspot_name("98:fe:54:62:a2:15") == "Fugleramme-A215"


@pytest.mark.parametrize(
    ("address", "expected"),
    [("10.42.0.34", True), ("::ffff:10.42.0.34", True), ("192.168.1.4", False), ("x", False)],
)
def test_on_hotspot(address, expected):
    assert wifi.on_hotspot(address) is expected


def _runner(outputs: dict[str, tuple[int, str]], calls: list[tuple[str, ...]]):
    """A fake `sudo`, answering by the command's words."""

    def run(args, stdin=None):
        calls.append(tuple(args))
        code, out = next((v for k, v in outputs.items() if k in " ".join(args)), (0, ""))
        return subprocess.CompletedProcess(args, code, out, "")

    return run


def test_online_is_a_default_route():
    assert not Nmcli(8080, read=_runner({"route": (0, "")}, [])).online()
    route = "default via 192.168.1.1 dev wlan0 proto dhcp metric 600"
    assert Nmcli(8080, read=_runner({"route": (0, route)}, [])).online()


def test_a_network_that_does_not_connect_is_deleted_again():
    calls: list[tuple[str, ...]] = []
    uuid = "5f1b8b1e-0000-4000-8000-000000000000"
    nm = Nmcli(
        8080,
        _runner(
            {
                "connection add": (0, f"Connection 'Home' ({uuid}) successfully added."),
                "connection up": (4, ""),
            },
            calls,
        ),
    )
    assert not nm.join("wlan0", "Home", "wrong", "WPA2", hidden=False)
    assert ("nmcli", "connection", "delete", "uuid", uuid) in calls


class FakeNm:
    """NetworkManager as the rules see it."""

    def __init__(self, saved=("Home",), online=False):
        self.saved_ssids = tuple(saved)
        self.is_online = online
        self.is_started = True
        self.in_range: tuple[Network, ...] = (Network("Neighbour", "WPA2", 50),)
        self.has_phones = False
        self.joins = True
        self.connects = False
        self.hotspot = False
        self.calls: list[str] = []

    def allowed(self):
        return True

    def device(self):
        return "wlan0"

    def started(self):
        return self.is_started

    def online(self):
        return self.is_online

    def saved(self):
        return self.saved_ssids

    def scan(self):
        return self.in_range

    def mac(self, device):
        return "98:fe:54:62:a2:15"

    def phones(self, device):
        return self.has_phones

    def open(self, device, name, password):
        self.calls.append("open")
        self.hotspot = True
        return True

    def close(self):
        self.calls.append("close")
        self.hotspot = False

    def connect(self, device):
        self.calls.append("connect")
        self.is_online = self.connects
        return self.connects

    def join(self, device, ssid, password, security, hidden):
        self.calls.append(f"join {ssid}")
        self.is_online = self.joins
        return self.joins


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _setup(nm, enabled=True, password=""):
    clock = Clock()
    published = []
    setup = Setup(
        nm,
        enabled=lambda: enabled,
        password=lambda: password,
        publish=published.append,
        clock=clock,
        sleep=lambda seconds: None,
    )
    assert setup.start()
    return setup, clock


def test_with_no_saved_network_it_opens_once_networkmanager_has_started():
    nm = FakeNm(saved=())
    nm.is_started = False
    setup, _ = _setup(nm)
    setup.step(None)
    assert not setup.state.up
    nm.is_started = True
    setup.step(None)
    assert setup.state.up
    assert setup.state.name == "Fugleramme-A215"
    assert setup.state.networks == nm.in_range


def test_saved_networks_get_the_grace_period_first():
    nm = FakeNm()
    setup, clock = _setup(nm)
    clock.now = GRACE - 1
    setup.step(None)
    assert not setup.state.up
    clock.now = GRACE
    setup.step(None)
    assert setup.state.up


def test_never_on_its_own_once_the_frame_has_been_online():
    nm = FakeNm(saved=(), online=True)
    setup, clock = _setup(nm)
    setup.step(None)
    nm.is_online = False
    clock.now = GRACE * 10
    setup.step(None)
    assert not setup.state.up


def test_a_boot_hotspot_closes_when_another_interface_comes_up():
    nm = FakeNm(saved=())
    setup, _ = _setup(nm)
    setup.step(None)
    nm.is_online = True
    setup.step(None)
    assert not setup.state.up
    assert not nm.hotspot


def test_it_retries_a_saved_network_only_once_it_is_in_range_and_nobody_is_on_the_hotspot():
    nm = FakeNm()
    setup, clock = _setup(nm)
    clock.now = GRACE
    setup.step(None)
    clock.now += RETRY
    setup.step(None)  # nothing saved in range: the hotspot stays
    assert setup.state.up
    assert "connect" not in nm.calls

    nm.in_range = (Network("Home", "WPA2", 70),)
    nm.has_phones = True
    clock.now += RETRY
    setup.step(None)
    assert "connect" not in nm.calls

    nm.has_phones = False
    nm.connects = True
    clock.now += RETRY
    setup.step(None)
    assert nm.calls[-2:] == ["close", "connect"]
    assert not setup.state.up


def test_a_failed_retry_reopens_the_hotspot():
    nm = FakeNm()
    nm.in_range = (Network("Home", "WPA2", 70),)
    setup, clock = _setup(nm)
    clock.now = GRACE
    setup.step(None)
    clock.now += RETRY
    setup.step(None)
    assert nm.calls[-3:] == ["close", "connect", "open"]
    assert setup.state.up


def test_holding_a_opens_it_while_online_and_again_closes_it():
    nm = FakeNm(online=True)
    setup, clock = _setup(nm)
    setup.step(wifi._TOGGLE)
    assert setup.state.up
    clock.now = RETRY * 10
    setup.step(None)  # held open: no retries, and being online does not close it
    assert setup.state.up
    setup.step(wifi._TOGGLE)
    assert not setup.state.up
    assert nm.calls[-2:] == ["close", "connect"]


def test_a_join_that_fails_reopens_the_hotspot_and_says_so():
    nm = FakeNm(saved=())
    nm.joins = False
    setup, _ = _setup(nm)
    setup.step(None)
    setup.step(wifi._Join("Home", "wrong", hidden=False))
    assert nm.calls[-3:] == ["close", "join Home", "open"]
    assert setup.state.up
    assert setup.state.error == "Couldn't join Home"


def test_a_join_that_works_closes_it():
    nm = FakeNm(saved=())
    setup, _ = _setup(nm)
    setup.step(None)
    setup.step(wifi._Join("Home", "right", hidden=False))
    assert not setup.state.up
    assert setup.state.error == ""


def test_switched_off_it_closes_and_ignores_a_hold():
    nm = FakeNm(saved=())
    enabled = [True]
    setup = Setup(
        nm,
        enabled=lambda: enabled[0],
        password=lambda: "",
        publish=lambda state: None,
        sleep=lambda seconds: None,
    )
    assert setup.start()
    setup.step(None)
    assert setup.state.up
    enabled[0] = False
    setup.step(None)
    assert not setup.state.up
    setup.step(wifi._TOGGLE)
    assert not setup.state.up


def test_without_sudo_it_says_why():
    nm = FakeNm()
    nm.allowed = lambda: False
    setup = Setup(nm, enabled=lambda: True, password=lambda: "", publish=lambda state: None)
    assert not setup.start()
    assert setup.state.problem == "sudo refuses nmcli"
    assert not setup.state.available
